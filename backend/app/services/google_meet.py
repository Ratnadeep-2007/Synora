import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConnectionNotFoundError,
    CredentialsExpiredError,
    GoogleMeetError,
    GoogleMeetPermissionError,
    GoogleMeetRateLimitError,
    GoogleMeetResourceNotFoundError,
    GoogleMeetTransientError,
    TranscriptUnavailableError,
)
from app.models.meeting import (
    Meeting,
    Participant,
    Transcript,
    TranscriptEntry,
)
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.schemas.meeting import MeetingRead, MeetingSyncResponse
from app.services.google_oauth import GoogleOAuthService

logger = logging.getLogger(__name__)


def _parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Helper to parse ISO-8601 timestamps from Google API responses."""
    if not dt_str:
        return None
    try:
        # Standardize 'Z' to '+00:00' for Python fromisoformat
        clean_str = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str)
    except Exception:
        return None


class GoogleMeetService:
    """
    Dedicated Google Meet REST API v2 connector and synchronization service.
    Encapsulates all Google Meet communication, pagination, error mapping,
    and normalization into internal domain models.
    """

    BASE_URL = "https://meet.googleapis.com/v2"

    def __init__(self, oauth_service: Optional[GoogleOAuthService] = None):
        self.oauth_service = oauth_service or GoogleOAuthService()

    async def _execute_request(
        self,
        method: str,
        path: str,
        access_token: str,
        params: Optional[Dict[str, Any]] = None,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        Execute an HTTP request to the Google Meet REST API with retry handling
        and transparent 401 token refresh.
        """
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        current_token = access_token
        attempt = 0
        backoff = 0.5
        refreshed_once = False

        while attempt < max_retries:
            attempt += 1
            headers = {
                "Authorization": f"Bearer {current_token}",
                "Accept": "application/json",
            }

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        params=params,
                    )
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                logger.warning(
                    f"Transient network error on Meet API {method} {path} (attempt {attempt}/{max_retries}): {exc}"
                )
                if attempt >= max_retries:
                    raise GoogleMeetTransientError(f"Network error communicating with Google Meet API: {exc}") from exc
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            # 1. Success
            if response.status_code == 200:
                try:
                    return response.json()
                except Exception as exc:
                    raise GoogleMeetError(f"Malformed JSON response from Google Meet API: {response.text}") from exc

            # 2. Token Expired (401)
            if response.status_code == 401:
                if not refreshed_once and connection and db:
                    logger.info("Received 401 from Google Meet API. Attempting token refresh...")
                    try:
                        connection = await self.oauth_service.refresh_credentials(connection, db=db, force=True)
                        creds = self.oauth_service.get_decrypted_credentials(connection)
                        current_token = creds.get("access_token", "")
                        refreshed_once = True
                        # Retry immediately with refreshed token
                        continue
                    except Exception as refresh_exc:
                        logger.error(f"Automatic token refresh failed: {refresh_exc}")
                        raise CredentialsExpiredError("Google credentials expired and could not be refreshed.") from refresh_exc
                else:
                    raise CredentialsExpiredError("Google OAuth token is expired or unauthorized.")

            # 3. Permissions / Scope (403)
            if response.status_code == 403:
                err_detail = ""
                try:
                    err_detail = response.json().get("error", {}).get("message", response.text)
                except Exception:
                    err_detail = response.text
                logger.error(f"Google Meet API 403 Forbidden: {err_detail}")
                raise GoogleMeetPermissionError(
                    f"Insufficient permissions for Google Meet API: {err_detail}"
                )

            # 4. Resource Not Found (404)
            if response.status_code == 404:
                raise GoogleMeetResourceNotFoundError(
                    f"Requested Google Meet resource '{path}' was not found."
                )

            # 5. Rate Limit (429)
            if response.status_code == 429:
                retry_after_hdr = response.headers.get("Retry-After")
                retry_after = int(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else int(backoff)
                logger.warning(
                    f"Google Meet API rate limit 429 received. Backing off for {retry_after}s (attempt {attempt}/{max_retries})"
                )
                if attempt >= max_retries:
                    raise GoogleMeetRateLimitError("Google Meet API rate limit exceeded.", retry_after=retry_after)
                await asyncio.sleep(retry_after)
                backoff *= 2
                continue

            # 6. Server Errors (5xx)
            if response.status_code >= 500:
                logger.warning(
                    f"Google Meet API 5xx server error ({response.status_code}) on {path} (attempt {attempt}/{max_retries})"
                )
                if attempt >= max_retries:
                    raise GoogleMeetTransientError(
                        f"Google Meet API service error ({response.status_code}): {response.text}"
                    )
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            # Other 4xx client errors
            raise GoogleMeetError(
                f"Google Meet API request failed ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )

        raise GoogleMeetTransientError(f"Exceeded max retries ({max_retries}) for Google Meet API request.")

    # ==========================================================================
    # Google Meet Low-Level Resource Operations
    # ==========================================================================

    async def list_conference_records(
        self,
        access_token: str,
        page_size: int = 20,
        page_token: Optional[str] = None,
        filter_query: Optional[str] = None,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        List Google Meet conference records accessible to the authenticated user.
        GET /v2/conferenceRecords
        """
        params: Dict[str, Any] = {"pageSize": min(page_size, 100)}
        if page_token:
            params["pageToken"] = page_token
        if filter_query:
            params["filter"] = filter_query

        return await self._execute_request(
            method="GET",
            path="conferenceRecords",
            access_token=access_token,
            params=params,
            connection=connection,
            db=db,
        )

    async def get_conference_record(
        self,
        access_token: str,
        name: str,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Get details of a single conference record by resource name (e.g. 'conferenceRecords/abc').
        GET /v2/{conferenceRecord}
        """
        clean_name = name.lstrip("/")
        return await self._execute_request(
            method="GET",
            path=clean_name,
            access_token=access_token,
            connection=connection,
            db=db,
        )

    async def list_participants(
        self,
        access_token: str,
        conference_record_name: str,
        page_size: int = 50,
        page_token: Optional[str] = None,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        List participants for a conference record.
        GET /v2/{conferenceRecord}/participants
        """
        clean_conf = conference_record_name.strip("/")
        params: Dict[str, Any] = {"pageSize": min(page_size, 100)}
        if page_token:
            params["pageToken"] = page_token

        return await self._execute_request(
            method="GET",
            path=f"{clean_conf}/participants",
            access_token=access_token,
            params=params,
            connection=connection,
            db=db,
        )

    async def list_transcripts(
        self,
        access_token: str,
        conference_record_name: str,
        page_size: int = 20,
        page_token: Optional[str] = None,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        List transcript resources for a conference record.
        GET /v2/{conferenceRecord}/transcripts
        """
        clean_conf = conference_record_name.strip("/")
        params: Dict[str, Any] = {"pageSize": min(page_size, 50)}
        if page_token:
            params["pageToken"] = page_token

        return await self._execute_request(
            method="GET",
            path=f"{clean_conf}/transcripts",
            access_token=access_token,
            params=params,
            connection=connection,
            db=db,
        )

    async def get_transcript(
        self,
        access_token: str,
        transcript_name: str,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Get transcript metadata by resource name.
        GET /v2/{transcript-resource-name}
        """
        clean_name = transcript_name.strip("/")
        return await self._execute_request(
            method="GET",
            path=clean_name,
            access_token=access_token,
            connection=connection,
            db=db,
        )

    async def list_transcript_entries(
        self,
        access_token: str,
        transcript_name: str,
        page_size: int = 100,
        page_token: Optional[str] = None,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        List transcript entries (speech segments) for a transcript resource.
        GET /v2/{transcript-resource-name}/entries
        """
        clean_name = transcript_name.strip("/")
        params: Dict[str, Any] = {"pageSize": min(page_size, 100)}
        if page_token:
            params["pageToken"] = page_token

        return await self._execute_request(
            method="GET",
            path=f"{clean_name}/entries",
            access_token=access_token,
            params=params,
            connection=connection,
            db=db,
        )

    # ==========================================================================
    # Pagination Helpers
    # ==========================================================================

    async def fetch_all_participants(
        self,
        access_token: str,
        conference_record_name: str,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
        max_pages: int = 5,
    ) -> List[Dict[str, Any]]:
        """Fetch all participants across paginated results with page bounds."""
        items: List[Dict[str, Any]] = []
        page_token = None
        pages = 0

        while pages < max_pages:
            pages += 1
            resp = await self.list_participants(
                access_token=access_token,
                conference_record_name=conference_record_name,
                page_token=page_token,
                connection=connection,
                db=db,
            )
            participants = resp.get("participants", [])
            items.extend(participants)

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return items

    async def fetch_all_transcripts(
        self,
        access_token: str,
        conference_record_name: str,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
        max_pages: int = 5,
    ) -> List[Dict[str, Any]]:
        """Fetch all transcripts for a conference record with page bounds."""
        items: List[Dict[str, Any]] = []
        page_token = None
        pages = 0

        while pages < max_pages:
            pages += 1
            resp = await self.list_transcripts(
                access_token=access_token,
                conference_record_name=conference_record_name,
                page_token=page_token,
                connection=connection,
                db=db,
            )
            transcripts = resp.get("transcripts", [])
            items.extend(transcripts)

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return items

    async def fetch_all_transcript_entries(
        self,
        access_token: str,
        transcript_name: str,
        connection: Optional[SourceConnection] = None,
        db: Optional[Session] = None,
        max_pages: int = 20,
    ) -> List[Dict[str, Any]]:
        """Fetch all transcript entries across paginated results with page bounds."""
        items: List[Dict[str, Any]] = []
        page_token = None
        pages = 0

        while pages < max_pages:
            pages += 1
            resp = await self.list_transcript_entries(
                access_token=access_token,
                transcript_name=transcript_name,
                page_token=page_token,
                connection=connection,
                db=db,
            )
            entries = resp.get("transcriptEntries", [])
            items.extend(entries)

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return items

    # ==========================================================================
    # High-Level Idempotent Synchronization Orchestrator
    # ==========================================================================

    async def sync_conferences(
        self,
        user_id: str,
        db: Session,
        max_conferences: int = 10,
        filter_query: Optional[str] = None,
        project_id: str = "proj_default",
    ) -> MeetingSyncResponse:
        """
        Synchronizes Google Meet conferences, participants, transcripts, and transcript entries
        for the given user. Idempotent: running multiple times updates existing records without duplication.
        """
        # 1. Retrieve user's active Google SourceConnection
        connection = (
            db.query(SourceConnection)
            .filter(
                SourceConnection.user_id == user_id,
                SourceConnection.provider == "google",
                SourceConnection.status == ConnectionStatus.ACTIVE.value,
            )
            .first()
        )
        if not connection:
            raise ConnectionNotFoundError(
                f"No active Google connection found for user '{user_id}'. Please connect via /auth/google first."
            )

        # 2. Get decrypted access credentials
        creds = self.oauth_service.get_decrypted_credentials(connection)
        access_token = creds.get("access_token", "")
        if not access_token:
            raise CredentialsExpiredError("No access token found in stored credentials. Please re-authenticate via /auth/google.")

        # Check if the connection has the necessary Meet scope
        granted_scope = creds.get("scope") or ""
        if granted_scope and "meetings" not in granted_scope and "space" not in granted_scope:
            raise GoogleMeetPermissionError(
                "Your Google account is connected, but the Google Meet reading scope (meetings.space.readonly) was not granted. "
                "Please re-authorize your Google account to grant Meet permissions, or use 'Import / Paste Transcript' or sample meetings."
            )

        logger.info(f"Sync started: user_id={user_id}, provider=google, project_id={project_id}")

        # 3. Retrieve conference records with pagination
        discovered_conferences: List[Dict[str, Any]] = []
        page_token = None
        pages = 0
        max_pages = 5

        while len(discovered_conferences) < max_conferences and pages < max_pages:
            pages += 1
            batch = await self.list_conference_records(
                access_token=access_token,
                page_size=min(max_conferences - len(discovered_conferences), 20),
                page_token=page_token,
                filter_query=filter_query,
                connection=connection,
                db=db,
            )
            records = batch.get("conferenceRecords", [])
            discovered_conferences.extend(records)

            page_token = batch.get("nextPageToken")
            if not page_token or not records:
                break

        total_conferences_discovered = len(discovered_conferences)
        logger.info(f"Discovered {total_conferences_discovered} conference records from Google Meet API.")

        synced_meetings: List[Meeting] = []
        total_transcripts_synced = 0
        total_entries_synced = 0

        # 4. Ingest each conference record
        for conf_raw in discovered_conferences:
            conf_name = conf_raw.get("name", "")
            if not conf_name:
                continue

            space_name = conf_raw.get("space")
            start_time = _parse_iso_datetime(conf_raw.get("startTime"))
            end_time = _parse_iso_datetime(conf_raw.get("endTime"))

            # Derive title from space code if possible
            meeting_title = f"Google Meet {conf_name.split('/')[-1]}"

            # 4.1 Upsert Meeting (idempotent lookup)
            meeting = (
                db.query(Meeting)
                .filter(
                    Meeting.provider == "google",
                    Meeting.provider_conference_id == conf_name,
                )
                .first()
            )

            if meeting:
                meeting.meeting_space_id = space_name or meeting.meeting_space_id
                meeting.start_time = start_time or meeting.start_time
                meeting.end_time = end_time or meeting.end_time
                meeting.status = "ENDED" if end_time else "ACTIVE"
                meeting.metadata_json = json.dumps(conf_raw)
                meeting.updated_at = datetime.now(timezone.utc)
            else:
                meeting = Meeting(
                    project_id=project_id,
                    user_id=user_id,
                    provider="google",
                    provider_conference_id=conf_name,
                    meeting_space_id=space_name,
                    title=meeting_title,
                    start_time=start_time,
                    end_time=end_time,
                    status="ENDED" if end_time else "ACTIVE",
                    metadata_json=json.dumps(conf_raw),
                )
                db.add(meeting)

            db.flush()  # Ensure meeting.id is populated for child relations
            logger.info(f"Conference discovered & persisted: {conf_name} -> meeting_id={meeting.id}")

            # 4.2 Ingest Participants
            participant_id_map: Dict[str, str] = {}  # provider_participant_id -> internal Participant.id
            try:
                participants_raw = await self.fetch_all_participants(
                    access_token=access_token,
                    conference_record_name=conf_name,
                    connection=connection,
                    db=db,
                )
                for part_raw in participants_raw:
                    part_name = part_raw.get("name", "")
                    if not part_name:
                        continue

                    # Extract display name from signedIn, anonymous, or phone user
                    display_name = None
                    email = None
                    if "signedinUser" in part_raw:
                        display_name = part_raw["signedinUser"].get("displayName")
                    elif "anonymousUser" in part_raw:
                        display_name = part_raw["anonymousUser"].get("displayName")
                    elif "phoneUser" in part_raw:
                        display_name = part_raw["phoneUser"].get("displayName")

                    # Upsert Participant
                    participant = (
                        db.query(Participant)
                        .filter(
                            Participant.meeting_id == meeting.id,
                            Participant.provider_participant_id == part_name,
                        )
                        .first()
                    )
                    if participant:
                        participant.display_name = display_name or participant.display_name
                        participant.email = email or participant.email
                        participant.metadata_json = json.dumps(part_raw)
                        participant.updated_at = datetime.now(timezone.utc)
                    else:
                        participant = Participant(
                            meeting_id=meeting.id,
                            provider_participant_id=part_name,
                            display_name=display_name,
                            email=email,
                            metadata_json=json.dumps(part_raw),
                        )
                        db.add(participant)

                    db.flush()
                    participant_id_map[part_name] = participant.id

            except Exception as part_err:
                logger.warning(f"Could not retrieve participants for {conf_name}: {part_err}")

            # 4.3 Ingest Transcripts
            try:
                transcripts_raw = await self.fetch_all_transcripts(
                    access_token=access_token,
                    conference_record_name=conf_name,
                    connection=connection,
                    db=db,
                )

                if not transcripts_raw:
                    # Explicitly represent unavailable transcript state
                    existing_trsc = (
                        db.query(Transcript)
                        .filter(
                            Transcript.meeting_id == meeting.id,
                            Transcript.provider_transcript_id == f"{conf_name}/transcripts/none",
                        )
                        .first()
                    )
                    if not existing_trsc:
                        unavail_trsc = Transcript(
                            meeting_id=meeting.id,
                            provider="google",
                            provider_transcript_id=f"{conf_name}/transcripts/none",
                            state="NOT_AVAILABLE",
                        )
                        db.add(unavail_trsc)

                for trans_raw in transcripts_raw:
                    trans_name = trans_raw.get("name", "")
                    if not trans_name:
                        continue

                    trans_state = trans_raw.get("state", "AVAILABLE")
                    t_start = _parse_iso_datetime(trans_raw.get("startTime"))
                    t_end = _parse_iso_datetime(trans_raw.get("endTime"))
                    docs_url = trans_raw.get("docsDestination", {}).get("exportUri")

                    # Upsert Transcript
                    transcript = (
                        db.query(Transcript)
                        .filter(
                            Transcript.provider == "google",
                            Transcript.provider_transcript_id == trans_name,
                        )
                        .first()
                    )

                    if transcript:
                        transcript.state = trans_state
                        transcript.start_time = t_start or transcript.start_time
                        transcript.end_time = t_end or transcript.end_time
                        transcript.docs_destination_url = docs_url or transcript.docs_destination_url
                        transcript.metadata_json = json.dumps(trans_raw)
                        transcript.updated_at = datetime.now(timezone.utc)
                    else:
                        transcript = Transcript(
                            meeting_id=meeting.id,
                            provider="google",
                            provider_transcript_id=trans_name,
                            state=trans_state,
                            start_time=t_start,
                            end_time=t_end,
                            docs_destination_url=docs_url,
                            metadata_json=json.dumps(trans_raw),
                        )
                        db.add(transcript)

                    db.flush()
                    total_transcripts_synced += 1
                    logger.info(f"Transcript discovered: {trans_name} (state={trans_state}) -> transcript_id={transcript.id}")

                    # 4.4 Ingest Transcript Entries if transcript is ready
                    if trans_state in ("ENDED", "AVAILABLE", "FILE_MUTATED"):
                        entries_raw = await self.fetch_all_transcript_entries(
                            access_token=access_token,
                            transcript_name=trans_name,
                            connection=connection,
                            db=db,
                        )
                        entries_count = 0

                        for ent_raw in entries_raw:
                            ent_name = ent_raw.get("name", "")
                            text = ent_raw.get("text", "")
                            if not ent_name or not text:
                                continue

                            provider_part_ref = ent_raw.get("participant")
                            resolved_part_id = participant_id_map.get(provider_part_ref) if provider_part_ref else None

                            e_start = _parse_iso_datetime(ent_raw.get("startTime"))
                            e_end = _parse_iso_datetime(ent_raw.get("endTime"))
                            lang = ent_raw.get("languageCode", "en-US")

                            # Upsert TranscriptEntry
                            entry = (
                                db.query(TranscriptEntry)
                                .filter(
                                    TranscriptEntry.transcript_id == transcript.id,
                                    TranscriptEntry.provider_entry_id == ent_name,
                                )
                                .first()
                            )
                            if entry:
                                entry.text = text
                                entry.participant_id = resolved_part_id or entry.participant_id
                                entry.language_code = lang
                                entry.start_time = e_start or entry.start_time
                                entry.end_time = e_end or entry.end_time
                                entry.metadata_json = json.dumps(ent_raw)
                                entry.updated_at = datetime.now(timezone.utc)
                            else:
                                entry = TranscriptEntry(
                                    transcript_id=transcript.id,
                                    provider="google",
                                    provider_entry_id=ent_name,
                                    participant_id=resolved_part_id,
                                    text=text,
                                    language_code=lang,
                                    start_time=e_start,
                                    end_time=e_end,
                                    metadata_json=json.dumps(ent_raw),
                                )
                                db.add(entry)

                            entries_count += 1

                        db.flush()
                        total_entries_synced += entries_count
                        logger.info(f"Entries ingested: count={entries_count}, transcript_id={transcript.id}")

            except Exception as trans_err:
                logger.warning(f"Could not retrieve transcripts for {conf_name}: {trans_err}")

            synced_meetings.append(meeting)

        db.commit()
        for m in synced_meetings:
            db.refresh(m)

        logger.info(
            f"Sync completed: meetings_synced={len(synced_meetings)}, "
            f"transcripts_synced={total_transcripts_synced}, entries_synced={total_entries_synced}"
        )

        return MeetingSyncResponse(
            success=True,
            message="Google Meet synchronization completed successfully.",
            total_conferences_discovered=total_conferences_discovered,
            total_conferences_synced=len(synced_meetings),
            total_transcripts_synced=total_transcripts_synced,
            total_entries_synced=total_entries_synced,
            meetings=[MeetingRead.model_validate(m) for m in synced_meetings],
        )
