import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    CredentialsExpiredError,
    GoogleMeetError,
    GoogleMeetPermissionError,
    GoogleMeetRateLimitError,
    GoogleMeetResourceNotFoundError,
    GoogleMeetTransientError,
    TranscriptUnavailableError,
)
from app.models.meet_event_record import MeetEventRecord
from app.models.meet_subscription import MeetSubscription, MeetSubscriptionStatus
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, Project
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.source_event import SourceEvent
from app.schemas.source_event import SourceEventCreate
from app.services.context_intelligence import ContextIntelligenceService
from app.services.google_meet import GoogleMeetService, _parse_iso_datetime
from app.services.google_oauth import GoogleOAuthService
from app.services.ingestion_service import IngestionService
from app.services.meeting_session_intelligence import MeetingSessionIntelligenceService
from app.services.metrics import metrics
from app.services.unknown_context_service import UnknownContextService

logger = logging.getLogger(__name__)

TRANSCRIPT_READY_EVENT = "google.workspace.meet.transcript.v2.fileGenerated"

UNASSIGNED_PROJECT_ID = "proj_unassigned"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def verify_pubsub_request(authorization_header: Optional[str]) -> bool:
    """Verify a Pub/Sub push request using the shared verification token.

    When PUBSUB_VERIFICATION_TOKEN is unconfigured, verification is skipped
    (local development) but the event is still marked as unverified in logs.
    """
    token = (authorization_header or "").removeprefix("Bearer ").strip()
    expected = settings.PUBSUB_VERIFICATION_TOKEN
    if not expected:
        logger.warning("meet_pubsub_unverified: PUBSUB_VERIFICATION_TOKEN is not configured")
        return True
    return hmac.compare_digest(token, expected)


def parse_pubsub_envelope(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a Pub/Sub push envelope into the Workspace Events payload.

    Raises ValueError for malformed envelopes so the caller can reject
    without acknowledging durable handling.
    """
    if not isinstance(envelope, dict) or "message" not in envelope:
        raise ValueError("Pub/Sub envelope must contain a 'message' object.")
    message = envelope["message"]
    if not isinstance(message, dict) or "data" not in message:
        raise ValueError("Pub/Sub message must contain base64 'data'.")
    message_id = message.get("messageId") or message.get("message_id") or ""
    try:
        payload = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Pub/Sub message data is not valid JSON: {exc}") from exc
    return {"message_id": message_id, "payload": payload, "attributes": message.get("attributes", {})}


def extract_transcript_notification(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the transcript resource references from a Workspace Events payload.

    Supports the documented transcript fileGenerated shape as well as the
    generic CloudEvents wrapper Google delivers over Pub/Sub.
    """
    event_type = (
        payload.get("eventType")
        or payload.get("event_type")
        or payload.get("type")
        or ""
    )
    data = payload.get("data") or payload.get("eventData") or {}
    transcript_resource = (
        data.get("transcript")
        or data.get("transcriptName")
        or data.get("resourceName")
        or payload.get("transcript")
        or payload.get("resourceName")
        or ""
    )
    conference_record_id = (
        data.get("conferenceRecord")
        or data.get("conferenceRecordName")
        or payload.get("conferenceRecord")
        or ""
    )
    if transcript_resource and not conference_record_id:
        parts = transcript_resource.split("/transcripts/")
        if len(parts) == 2:
            conference_record_id = parts[0]
    event_id = (
        payload.get("id")
        or payload.get("eventId")
        or payload.get("event_id")
        or transcript_resource
    )
    occurred_at = payload.get("time") or payload.get("occurredAt") or payload.get("occurred_at")
    subscription = payload.get("subscription") or data.get("subscription")
    return {
        "event_type": event_type,
        "event_id": event_id,
        "transcript_resource": transcript_resource,
        "conference_record_id": conference_record_id,
        "occurred_at": occurred_at,
        "subscription": subscription,
    }


class MeetEventWorker:
    """Event-driven transcript pipeline worker.

    Flow per notification (notification != content):
      Workspace Events -> Pub/Sub -> validate -> deduplicate ->
      Meet REST retrieval (metadata, entries, participants) ->
      normalize -> SourceEvent -> Evidence -> downstream agent pipeline.

    Heavy AI work stays out of the Pub/Sub handler: the handler records the
    event durably and the retrieval/processing stages run as idempotent
    units that are safe to retry on redelivery.
    """

    def __init__(
        self,
        meet_service: Optional[GoogleMeetService] = None,
        oauth_service: Optional[GoogleOAuthService] = None,
        ingestion_service: Optional[IngestionService] = None,
        context_service: Optional[ContextIntelligenceService] = None,
        unknown_service: Optional[UnknownContextService] = None,
    ):
        self.meet_service = meet_service or GoogleMeetService()
        self.oauth_service = oauth_service or GoogleOAuthService()
        self.ingestion = ingestion_service or IngestionService()
        # Meet uses the SAME Context Intelligence engine as every other source.
        self.context_service = context_service or ContextIntelligenceService()
        self.unknown_service = unknown_service or UnknownContextService(
            context_service=self.context_service
        )

    # ------------------------------------------------------------------
    # Stage 1: Pub/Sub intake (lightweight, durable)
    # ------------------------------------------------------------------
    def handle_pubsub_push(
        self,
        envelope: Dict[str, Any],
        db: Session,
        authorization_header: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate and durably record a Pub/Sub push message.

        Returns a result dict; raises ValueError for malformed envelopes
        (caller must NOT acknowledge) and WorkspaceLookupError-free results
        for duplicates (safe to acknowledge).
        """
        if not verify_pubsub_request(authorization_header):
            metrics.increment("meet_sync_failed_total", labels={"reason": "pubsub_unauthorized"})
            logger.warning("meet_event_rejected: reason=pubsub_unauthorized")
            raise ValueError("Invalid Pub/Sub verification token.")

        parsed = parse_pubsub_envelope(envelope)
        payload = parsed["payload"]
        notification = extract_transcript_notification(payload)

        if notification["event_type"] and notification["event_type"] != TRANSCRIPT_READY_EVENT:
            logger.info(
                "meet_event_ignored: event_type=%s message_id=%s",
                notification["event_type"],
                parsed["message_id"],
            )
            return {"acknowledged": True, "action": "ignored", "reason": "unsupported_event_type"}

        provider_event_id = notification["event_id"] or parsed["message_id"]
        if not provider_event_id:
            raise ValueError("Workspace event has no stable event identifier.")

        existing = (
            db.query(MeetEventRecord)
            .filter(MeetEventRecord.provider_event_id == provider_event_id)
            .first()
        )
        if existing:
            metrics.increment("meet_events_duplicate_total", labels={"provider": "google_meet"})
            logger.info(
                "meet_event_duplicate: provider_event_id=%s status=%s",
                provider_event_id,
                existing.status,
            )
            return {"acknowledged": True, "action": "duplicate", "event_record_id": existing.id}

        record = MeetEventRecord(
            provider_event_id=provider_event_id,
            event_type=notification["event_type"] or TRANSCRIPT_READY_EVENT,
            conference_record_id=notification["conference_record_id"] or None,
            transcript_resource=notification["transcript_resource"] or None,
            status="received",
            attempts="0",
            user_id="",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        metrics.increment("meet_events_received_total", labels={"provider": "google_meet"})
        logger.info(
            "meet_event_received: provider_event_id=%s conference=%s transcript=%s",
            provider_event_id,
            notification["conference_record_id"],
            notification["transcript_resource"],
        )
        return {"acknowledged": False, "action": "recorded", "event_record_id": record.id}

    def bind_event_identity(
        self,
        event_record_id: str,
        user_id: str,
        subscription_id: Optional[str],
        project_id: Optional[str],
        db: Session,
    ) -> MeetEventRecord:
        record = db.query(MeetEventRecord).filter(MeetEventRecord.id == event_record_id).first()
        if not record:
            raise ValueError(f"Meet event record '{event_record_id}' not found.")
        record.user_id = user_id
        record.subscription_id = subscription_id
        record.project_id = project_id
        if subscription_id:
            subscription = (
                db.query(MeetSubscription).filter(MeetSubscription.id == subscription_id).first()
            )
            if subscription:
                subscription.last_event_at = _now()
        db.commit()
        db.refresh(record)
        return record

    # ------------------------------------------------------------------
    # Stage 2: Retrieval + persistence (idempotent, retry-safe)
    # ------------------------------------------------------------------
    def _get_connection(self, user_id: str, db: Session) -> SourceConnection:
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
            # Zero-touch bootstrap from .env if configured
            connection = self.oauth_service.ensure_env_connection(db, user_id=user_id or "usr_default")

        if not connection:
            # Fallback to any active google connection across the workspace
            connection = (
                db.query(SourceConnection)
                .filter(
                    SourceConnection.provider == "google",
                    SourceConnection.status == ConnectionStatus.ACTIVE.value,
                )
                .first()
            )

        if not connection:
            metrics.increment("meet_sync_failed_total", labels={"reason": "no_connection"})
            logger.warning("meet_sync_failed: reason=no_connection user_id=%s", user_id)
            raise CredentialsExpiredError(
                f"No active Google connection found for user '{user_id}'. "
                "Configure GOOGLE_REFRESH_TOKEN in .env or connect via /auth/google."
            )
        return connection


    def _resolve_project(
        self,
        db: Session,
        user_id: str,
        subscription: Optional[MeetSubscription],
        conference_record_id: str,
    ) -> tuple[Optional[str], str]:
        """Deterministic trusted mapping for a transcript notification.

        Honours explicit connector bindings (a subscription pinned to a project,
        or an already-owned meeting). Never guesses: when no trusted mapping
        exists the caller falls back to segment-level Context Intelligence and,
        if that is inconclusive, to Unknown Context.

        Returns (project_id | None, reason).
        """
        if subscription and subscription.project_id:
            project = db.query(Project).filter(Project.id == subscription.project_id).first()
            if project and not project.is_system:
                return project.id, "trusted_subscription_mapping"
            logger.warning(
                "meet_subscription_project_unavailable: subscription=%s project_id=%s",
                subscription.id,
                subscription.project_id,
            )
        owned = (
            db.query(Meeting)
            .filter(
                Meeting.provider == "google",
                Meeting.provider_conference_id == conference_record_id,
                Meeting.user_id == user_id,
            )
            .first()
        )
        if owned and owned.project_id and owned.project_id not in (
            UNASSIGNED_PROJECT_ID,
            SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        ):
            return owned.project_id, "existing_meeting_mapping"
        return None, "unmapped"

    # ------------------------------------------------------------------
    # Bounded context routing (one meeting may span projects)
    # ------------------------------------------------------------------
    def _segment_entries(
        self, entries: List[TranscriptEntry], window_size: int = 12, gap_seconds: int = 45
    ) -> List[List[TranscriptEntry]]:
        """Create routing/timeline windows; never run intelligence per window.

        The completed transcript is fetched and persisted first. The bounded
        windows below are only a context-routing aid for meetings that may span
        multiple projects. After routing, each project receives its full
        persisted evidence set in the shared intelligence pipeline.
        """
        return MeetingSessionIntelligenceService.segment_entries(
            entries=entries,
            window_size=window_size,
            gap_seconds=gap_seconds,
        )

    def _route_transcript_segments(
        self,
        meeting: Meeting,
        transcript: Transcript,
        db: Session,
        trusted_project_id: Optional[str],
    ) -> Dict[str, Any]:
        """Route each transcript segment to a project or Unknown Context.

        The single Meeting row and its association are preserved; only the
        evidence boundary differs per segment.
        """
        entries = (
            db.query(TranscriptEntry)
            .filter(TranscriptEntry.transcript_id == transcript.id)
            .order_by(TranscriptEntry.start_time.asc())
            .all()
        )
        # The transcript is already complete and persisted before routing begins.
        # These windows are a routing aid only; no per-window intelligence pass is
        # performed here. A trusted project mapping does not need segmentation at
        # all, so the complete transcript routes as one context.
        windows = (
            [entries]
            if trusted_project_id and entries
            else self._segment_entries(entries)
        )
        routed: Dict[str, int] = {}
        unknown_segments = 0
        events_created = 0

        for index, window in enumerate(windows):
            text = " ".join(e.text for e in window if e.text)
            if not text.strip():
                continue

            if trusted_project_id:
                target_project_id: Optional[str] = trusted_project_id
                reason = "trusted_subscription_mapping"
            else:
                neighbour_text = self._neighbouring_text(windows, index)
                cross_source = ""
                try:
                    from app.services.conversation_continuity import build_meet_continuity

                    cross_source = build_meet_continuity(db, meeting_id=meeting.id)
                except Exception:
                    cross_source = ""
                continuity = "\n".join(p for p in (neighbour_text, cross_source) if p)[:1500]
                resolution = self.context_service.resolve(
                    source="google_meet",
                    payload={"text": text, "meeting_id": meeting.id},
                    db=db,
                    trusted_project_id=None,
                    continuity_context=continuity or None,
                    source_event_id=f"{transcript.id}:seg{index}",
                    record=True,
                )
                target_project_id = resolution.project_id
                reason = resolution.reason

            if target_project_id:
                routed[target_project_id] = routed.get(target_project_id, 0) + len(window)
            else:
                target_project_id = SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
                unknown_segments += 1

            for entry in window:
                events_created += self._emit_entry_evidence(
                    entry=entry,
                    meeting=meeting,
                    transcript=transcript,
                    project_id=target_project_id,
                    db=db,
                    metadata={"segment_index": index, "routing_reason": reason},
                )

            if target_project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID:
                self.unknown_service.create_item(
                    source="google_meet",
                    payload={
                        "text": text,
                        "meeting_id": meeting.id,
                        "conference_record_id": meeting.provider_conference_id,
                        "transcript_id": transcript.id,
                    },
                    db=db,
                    source_event_id=f"{transcript.id}:seg{index}",
                    meeting_id=meeting.id,
                    actor_id="google_meet",
                    content=text,
                    occurred_at=window[0].start_time if window else None,
                )

        logger.info(
            "meet_segments_routed: meeting=%s windows=%d projects=%s unknown_segments=%d",
            meeting.id,
            len(windows),
            list(routed.keys()),
            unknown_segments,
        )
        return {
            "segments": len(windows),
            "routed_projects": routed,
            "unknown_segments": unknown_segments,
            "events_created": events_created,
        }

    @staticmethod
    def _neighbouring_text(
        windows: List[List[TranscriptEntry]], index: int, limit: int = 2
    ) -> str:
        """Neighbouring transcript segments, used as a continuity signal."""
        parts: List[str] = []
        for offset in range(1, limit + 1):
            for neighbour in (index - offset, index + offset):
                if 0 <= neighbour < len(windows):
                    parts.extend(e.text for e in windows[neighbour] if e.text)
        return " ".join(parts)[:1500]

    def _emit_entry_evidence(
        self,
        entry: TranscriptEntry,
        meeting: Meeting,
        transcript: Transcript,
        project_id: str,
        db: Session,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Emit idempotent evidence while preserving revised transcript text.

        Google Meet transcript entries are upserted by provider_entry_id. When
        the provider revises the text of an existing entry, the original
        evidence remains immutable and a content-hashed revision event/evidence
        record is added. Re-running the same text is still fully idempotent.
        """
        import hashlib

        speaker_name = entry.participant.display_name if entry.participant else None
        base_event_id = entry.provider_entry_id
        event_id = base_event_id

        existing_event = (
            db.query(SourceEvent)
            .filter(
                SourceEvent.project_id == project_id,
                SourceEvent.source == "google_meet",
                SourceEvent.source_event_id == base_event_id,
            )
            .first()
        )
        if existing_event:
            try:
                existing_payload = json.loads(existing_event.payload_json or "{}")
            except (TypeError, ValueError):
                existing_payload = {}
            existing_text = str(existing_payload.get("text") or "").strip()
            current_text = str(entry.text or "").strip()
            if existing_text != current_text:
                digest = hashlib.sha1(current_text.encode("utf-8")).hexdigest()[:12]
                event_id = f"{base_event_id}:rev:{digest}"

        event_in = SourceEventCreate(
            tenant_id="tenant_default",
            project_id=project_id,
            source="google_meet",
            source_event_id=event_id,
            event_type="transcript_entry" if event_id == base_event_id else "transcript_entry_revision",
            actor_id=speaker_name or "Unknown Speaker",
            occurred_at=entry.start_time,
            payload={
                "text": entry.text,
                "language_code": entry.language_code,
                "start_time": entry.start_time.isoformat() if entry.start_time else None,
                "speaker_name": speaker_name,
                "meeting_id": meeting.id,
                "transcript_id": transcript.id,
                "conference_id": meeting.provider_conference_id,
                "revision_of": base_event_id if event_id != base_event_id else None,
            },
            status="received",
        )
        event = self.ingestion.ingest_event(event_in, db, commit=False)
        db.flush()
        self.ingestion.create_evidence_from_event(
            event=event,
            db=db,
            meeting_id=meeting.id,
            transcript_id=transcript.id,
            transcript_entry_id=entry.id,
            content=entry.text,
            metadata={
                "speaker_display_name": speaker_name,
                "transcript_revision": event_id != base_event_id,
                **(metadata or {}),
            },
            commit=False,
        )
        db.flush()
        return 1

    def process_event_record(
        self,
        event_record_id: str,
        db: Session,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Retrieve transcript content for a recorded event and persist it."""
        record = db.query(MeetEventRecord).filter(MeetEventRecord.id == event_record_id).first()
        if not record:
            raise ValueError(f"Meet event record '{event_record_id}' not found.")
        if record.status == "processed":
            metrics.increment("meet_events_duplicate_total", labels={"provider": "google_meet"})
            return {"status": "duplicate", "event_record_id": record.id}
        if not record.user_id:
            raise ValueError("Event record has no bound user identity; bind it before processing.")

        attempts = int(record.attempts or "0")
        record.status = "processing"
        record.attempts = str(attempts + 1)
        db.commit()

        try:
            result = self._retrieve_and_persist(record, db)
        except (GoogleMeetTransientError, GoogleMeetRateLimitError) as exc:
            record.status = "pending_retry" if attempts + 1 < max_retries else "failed"
            record.last_error = str(exc)[:2000]
            db.commit()
            metrics.increment("meet_sync_failed_total", labels={"reason": "transient"})
            logger.warning(
                "meet_transcript_fetch_retry: provider_event_id=%s attempt=%d error=%s",
                record.provider_event_id,
                attempts + 1,
                exc,
            )
            raise
        except (TranscriptUnavailableError, GoogleMeetResourceNotFoundError) as exc:
            record.status = "awaiting_transcript"
            record.last_error = str(exc)[:2000]
            db.commit()
            metrics.increment("meet_sync_failed_total", labels={"reason": "transcript_pending"})
            logger.info(
                "meet_transcript_pending: provider_event_id=%s error=%s",
                record.provider_event_id,
                exc,
            )
            raise
        except (CredentialsExpiredError, GoogleMeetPermissionError) as exc:
            record.status = "failed"
            record.last_error = str(exc)[:2000]
            db.commit()
            metrics.increment("meet_sync_failed_total", labels={"reason": "auth"})
            logger.error(
                "meet_sync_failed: provider_event_id=%s reason=auth error=%s",
                record.provider_event_id,
                exc,
            )
            raise
        except GoogleMeetError as exc:
            record.status = "failed"
            record.last_error = str(exc)[:2000]
            db.commit()
            metrics.increment("meet_sync_failed_total", labels={"reason": "retrieval_failure"})
            logger.error(
                "meet_sync_failed: provider_event_id=%s reason=retrieval error=%s",
                record.provider_event_id,
                exc,
            )
            raise

        record.status = "processed"
        record.processed_at = _now()
        record.meeting_id = result["meeting_id"]
        record.source_event_id = result.get("source_event_id")
        db.commit()
        db.refresh(record)
        metrics.increment("meet_transcript_persisted_total", labels={"provider": "google_meet"})
        logger.info(
            "meet_transcript_persisted: provider_event_id=%s meeting_id=%s entries=%d",
            record.provider_event_id,
            result["meeting_id"],
            result["entries_synced"],
        )
        return {"status": "processed", **result, "event_record_id": record.id}

    def _retrieve_and_persist(self, record: MeetEventRecord, db: Session) -> Dict[str, Any]:
        if not record.transcript_resource:
            raise TranscriptUnavailableError("Event carries no transcript resource reference.")
        if not record.conference_record_id:
            raise TranscriptUnavailableError("Event carries no conference record reference.")

        logger.info(
            "meet_transcript_ready: provider_event_id=%s conference=%s transcript=%s",
            record.provider_event_id,
            record.conference_record_id,
            record.transcript_resource,
        )

        connection = self._get_connection(record.user_id, db)
        creds = self.oauth_service.get_decrypted_credentials(connection)
        access_token = creds.get("access_token", "")
        if not access_token:
            raise CredentialsExpiredError("No access token in stored credentials. Re-authenticate via /auth/google.")

        subscription = None
        if record.subscription_id:
            subscription = (
                db.query(MeetSubscription).filter(MeetSubscription.id == record.subscription_id).first()
            )
        trusted_project_id, mapping_reason = self._resolve_project(
            db, record.user_id, subscription, record.conference_record_id
        )
        # The meeting itself is anchored to the trusted mapping when present,
        # otherwise to Unknown Context until segment routing resolves it.
        project_id = trusted_project_id or SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
        record.project_id = project_id

        logger.info(
            "meet_transcript_fetch_started: transcript=%s conference=%s project_id=%s mapping=%s",
            record.transcript_resource,
            record.conference_record_id,
            project_id,
            mapping_reason,
        )

        transcript_meta = asyncio.run(
            self.meet_service.get_transcript(
                access_token=access_token,
                transcript_name=record.transcript_resource,
                connection=connection,
                db=db,
            )
        )
        transcript_state = transcript_meta.get("state", "AVAILABLE")
        if transcript_state not in ("ENDED", "AVAILABLE", "FILE_MUTATED"):
            raise TranscriptUnavailableError(
                f"Transcript '{record.transcript_resource}' is in state '{transcript_state}'; not yet retrievable."
            )

        meeting = self._upsert_meeting(
            db=db,
            user_id=record.user_id,
            project_id=project_id,
            connection_id=connection.id,
            conference_record_id=record.conference_record_id,
            access_token=access_token,
            connection=connection,
        )
        transcript = self._upsert_transcript(
            db=db,
            meeting=meeting,
            transcript_resource=record.transcript_resource,
            transcript_meta=transcript_meta,
        )
        participant_map = self._sync_participants(
            db=db,
            meeting=meeting,
            conference_record_id=record.conference_record_id,
            access_token=access_token,
            connection=connection,
        )
        entries = asyncio.run(
            self.meet_service.fetch_all_transcript_entries(
                access_token=access_token,
                transcript_name=record.transcript_resource,
                connection=connection,
                db=db,
            )
        )
        entries_synced = self._upsert_entries(
            db=db,
            transcript=transcript,
            entries_raw=entries,
            participant_map=participant_map,
        )
        logger.info(
            "meet_transcript_fetch_completed: transcript=%s entries=%d",
            record.transcript_resource,
            entries_synced,
        )

        # Segment-level routing: one meeting may produce evidence for several
        # projects, with inconclusive segments preserved in Unknown Context.
        routing = self._route_transcript_segments(
            meeting=meeting,
            transcript=transcript,
            db=db,
            trusted_project_id=trusted_project_id,
        )

        # Record one completed external synchronization phase. The session
        # intelligence service and ProjectMemory pipeline consume only these
        # persisted DB records; they do not call Google after this point.
        try:
            sync_metadata = json.loads(meeting.metadata_json or "{}")
        except (TypeError, ValueError):
            sync_metadata = {}
        sync_metadata["synora_meet_sync"] = {
            "retrieval_mode": "completed_meeting_once",
            "retrieval_completed_at": _now().isoformat(),
            "transcript_resource": record.transcript_resource,
            "conference_record_id": record.conference_record_id,
            "transcript_entry_count": entries_synced,
            "routing_window_count": int(routing.get("segments", 0) or 0),
            "trusted_project_mapping": bool(trusted_project_id),
            "intelligence_input": "full_persisted_transcript",
            "google_api_calls_after_persistence": 0,
        }
        meeting.metadata_json = json.dumps(sync_metadata, ensure_ascii=False)
        db.add(meeting)
        db.flush()

        events_created = self._create_transcript_ready_event(
            db=db,
            record=record,
            project_id=project_id,
            meeting=meeting,
            transcript=transcript,
        )
        db.commit()
        return {
            "meeting_id": meeting.id,
            "transcript_id": transcript.id,
            "entries_synced": entries_synced,
            "sync_mode": "completed_meeting_once",
            "intelligence_input": "full_persisted_transcript",
            "google_api_calls_after_persistence": 0,
            "events_created": events_created,
            "project_id": project_id,
            "trusted_project_id": trusted_project_id,
            "routing": routing,
            "source_event_id": None,
        }

    def _upsert_meeting(
        self,
        db: Session,
        user_id: str,
        project_id: str,
        connection_id: str,
        conference_record_id: str,
        access_token: str,
        connection: SourceConnection,
    ) -> Meeting:
        conf_meta: Dict[str, Any] = {}
        try:
            conf_meta = asyncio.run(
                self.meet_service.get_conference_record(
                    access_token=access_token,
                    name=conference_record_id,
                    connection=connection,
                    db=db,
                )
            )
        except GoogleMeetResourceNotFoundError:
            conf_meta = {}
        start_time = _parse_iso_datetime(conf_meta.get("startTime"))
        end_time = _parse_iso_datetime(conf_meta.get("endTime"))

        meeting = (
            db.query(Meeting)
            .filter(
                Meeting.provider == "google",
                Meeting.provider_conference_id == conference_record_id,
            )
            .first()
        )
        title = f"Google Meet {conference_record_id.split('/')[-1]}"
        if meeting:
            meeting.start_time = start_time or meeting.start_time
            meeting.end_time = end_time or meeting.end_time
            meeting.status = "ENDED" if end_time else meeting.status
            meeting.source_connection_id = connection_id
            if conf_meta:
                import json as _json

                meeting.metadata_json = _json.dumps(conf_meta)
            meeting.updated_at = _now()
        else:
            meeting = Meeting(
                project_id=project_id,
                user_id=user_id,
                provider="google",
                provider_conference_id=conference_record_id,
                meeting_space_id=conf_meta.get("space"),
                title=title,
                start_time=start_time,
                end_time=end_time,
                status="ENDED" if end_time else "ACTIVE",
                source_connection_id=connection_id,
            )
            if conf_meta:
                import json as _json

                meeting.metadata_json = _json.dumps(conf_meta)
            db.add(meeting)
        db.flush()
        return meeting

    def _upsert_transcript(
        self,
        db: Session,
        meeting: Meeting,
        transcript_resource: str,
        transcript_meta: Dict[str, Any],
    ) -> Transcript:
        import json as _json

        transcript = (
            db.query(Transcript)
            .filter(
                Transcript.provider == "google",
                Transcript.provider_transcript_id == transcript_resource,
            )
            .first()
        )
        state = transcript_meta.get("state", "AVAILABLE")
        start = _parse_iso_datetime(transcript_meta.get("startTime"))
        end = _parse_iso_datetime(transcript_meta.get("endTime"))
        docs_url = transcript_meta.get("docsDestination", {}).get("exportUri")
        if transcript:
            transcript.state = state
            transcript.start_time = start or transcript.start_time
            transcript.end_time = end or transcript.end_time
            transcript.docs_destination_url = docs_url or transcript.docs_destination_url
            transcript.metadata_json = _json.dumps(transcript_meta)
            transcript.updated_at = _now()
        else:
            transcript = Transcript(
                meeting_id=meeting.id,
                provider="google",
                provider_transcript_id=transcript_resource,
                state=state,
                start_time=start,
                end_time=end,
                docs_destination_url=docs_url,
                metadata_json=_json.dumps(transcript_meta),
            )
            db.add(transcript)
        db.flush()
        return transcript

    def _sync_participants(
        self,
        db: Session,
        meeting: Meeting,
        conference_record_id: str,
        access_token: str,
        connection: SourceConnection,
    ) -> Dict[str, str]:
        import json as _json

        participant_map: Dict[str, str] = {}
        try:
            participants_raw = asyncio.run(
                self.meet_service.fetch_all_participants(
                    access_token=access_token,
                    conference_record_name=conference_record_id,
                    connection=connection,
                    db=db,
                )
            )
        except (GoogleMeetError, CredentialsExpiredError) as exc:
            logger.warning(
                "meet_participant_lookup_failed: conference=%s error=%s",
                conference_record_id,
                exc,
            )
            metrics.increment("meet_sync_failed_total", labels={"reason": "participant_lookup"})
            return participant_map

        for part_raw in participants_raw:
            part_name = part_raw.get("name", "")
            if not part_name:
                continue
            display_name = None
            if "signedinUser" in part_raw:
                display_name = part_raw["signedinUser"].get("displayName")
            elif "anonymousUser" in part_raw:
                display_name = part_raw["anonymousUser"].get("displayName")
            elif "phoneUser" in part_raw:
                display_name = part_raw["phoneUser"].get("displayName")
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
                participant.metadata_json = _json.dumps(part_raw)
                participant.updated_at = _now()
            else:
                participant = Participant(
                    meeting_id=meeting.id,
                    provider_participant_id=part_name,
                    display_name=display_name,
                    metadata_json=_json.dumps(part_raw),
                )
                db.add(participant)
            db.flush()
            participant_map[part_name] = participant.id
        return participant_map

    def _upsert_entries(
        self,
        db: Session,
        transcript: Transcript,
        entries_raw: List[Dict[str, Any]],
        participant_map: Dict[str, str],
    ) -> int:
        import json as _json

        count = 0
        for ent_raw in sorted(entries_raw, key=lambda e: e.get("startTime", "")):
            ent_name = ent_raw.get("name", "")
            text = ent_raw.get("text", "")
            if not ent_name or not text:
                continue
            provider_part_ref = ent_raw.get("participant")
            resolved_part_id = participant_map.get(provider_part_ref) if provider_part_ref else None
            start = _parse_iso_datetime(ent_raw.get("startTime"))
            end = _parse_iso_datetime(ent_raw.get("endTime"))
            lang = ent_raw.get("languageCode", "en-US")
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
                entry.start_time = start or entry.start_time
                entry.end_time = end or entry.end_time
                entry.metadata_json = _json.dumps(ent_raw)
                entry.updated_at = _now()
            else:
                entry = TranscriptEntry(
                    transcript_id=transcript.id,
                    provider="google",
                    provider_entry_id=ent_name,
                    participant_id=resolved_part_id,
                    text=text,
                    language_code=lang,
                    start_time=start,
                    end_time=end,
                    metadata_json=_json.dumps(ent_raw),
                )
                db.add(entry)
            count += 1
        db.flush()
        return count

    def _create_transcript_ready_event(
        self,
        db: Session,
        record: MeetEventRecord,
        project_id: str,
        meeting: Meeting,
        transcript: Transcript,
    ) -> int:
        """Normalize the notification itself into the Synesis source-event model."""
        source_event_id = f"meet-event:{record.provider_event_id}"
        existing = (
            db.query(SourceEvent)
            .filter(
                SourceEvent.project_id == project_id,
                SourceEvent.source == "google_meet",
                SourceEvent.source_event_id == source_event_id,
            )
            .first()
        )
        if existing:
            return 0
        event_in = SourceEventCreate(
            tenant_id="tenant_default",
            project_id=project_id,
            source="google_meet",
            source_event_id=source_event_id,
            event_type="transcript_ready",
            actor_id="google_workspace_events",
            occurred_at=_now(),
            payload={
                "conference_record_id": record.conference_record_id,
                "transcript_resource": record.transcript_resource,
                "meeting_id": meeting.id,
                "transcript_id": transcript.id,
                "provider_event_id": record.provider_event_id,
            },
            status="received",
        )
        self.ingestion.ingest_event(event_in, db, commit=False)
        db.flush()
        return 1
