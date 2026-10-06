import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.project import Project, SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.models.source_event import SourceEvent
from app.services.context_resolution_service import ContextResolutionService
from app.services.pipeline_coordinator import PipelineCoordinator
from app.services.whisper_transcription_service import WhisperFallbackError, WhisperTranscriptionService

logger = logging.getLogger(__name__)


class VexaSarvamError(RuntimeError):
    pass


def parse_google_meet_code(meeting_url: str) -> str:
    """Extract the native meeting code from a Google Meet join URL.

    The code shape is validated rather than merely split on, because a wrong
    code sends the bot to a meeting that does not exist and the failure then
    looks like a Vexa join problem rather than a bad link. Google issues codes
    as hyphen-separated groups (xxx-xxxx-xxx), so require that grouping and a
    minimum length, while keeping the character set permissive.
    """
    value = str(meeting_url or "").strip()
    match = re.fullmatch(
        r"https?://(?:www\.)?meet\.google\.com/([a-zA-Z0-9_-]+)(?:[/?#].*)?",
        value,
    )
    if not match:
        raise VexaSarvamError(
            "Enter a standard Google Meet URL such as https://meet.google.com/abc-defg-hij."
        )

    code = match.group(1)
    if code.count("-") < 2 or len(code) < 10:
        raise VexaSarvamError(
            f"'{code}' is not a valid Google Meet code. "
            "Enter a standard Google Meet URL such as https://meet.google.com/abc-defg-hij."
        )
    return code


def _json_loads(value: Optional[str]) -> Dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _json_dump(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _set_capture_metadata(meeting: Meeting, updates: Dict[str, Any]) -> None:
    metadata = _json_loads(meeting.metadata_json)
    capture = metadata.setdefault("vexa_capture", {})
    capture.update(updates)
    meeting.metadata_json = _json_dump(metadata)


def get_capture_metadata(meeting: Meeting) -> Dict[str, Any]:
    metadata = _json_loads(meeting.metadata_json)
    capture = metadata.get("vexa_capture")
    return capture if isinstance(capture, dict) else {}


class VexaSarvamService:
    """
    Post-meeting path:
    Google Meet -> Vexa recording -> Sarvam Saaras STT -> Synora.

    Sarvam is primary. Self-hosted faster-whisper is used only when Sarvam
    is unavailable or fails.
    """

    def __init__(
        self,
        vexa_base_url: Optional[str] = None,
        vexa_api_key: Optional[str] = None,
        sarvam_api_key: Optional[str] = None,
    ):
        # An explicitly passed argument always wins, including an empty string.
        # Previously `or` was used, so passing "" meant "no key" in intent but
        # silently inherited the configured key instead. Any caller - including a
        # test asserting the no-Sarvam fallback path - then reached the live
        # Sarvam API instead of the branch it meant to exercise.
        # None means "inherit from configuration"; "" means "explicitly disabled".
        self.vexa_base_url = (vexa_base_url or settings.VEXA_BASE_URL).rstrip("/") + "/"
        self.vexa_api_key = (
            settings.VEXA_API_KEY if vexa_api_key is None else vexa_api_key
        ).strip()
        self.sarvam_api_key = (
            settings.SARVAM_API_KEY if sarvam_api_key is None else sarvam_api_key
        ).strip()

    def _vexa_headers(self) -> Dict[str, str]:
        if not self.vexa_api_key:
            raise VexaSarvamError("VEXA_API_KEY is not configured.")
        return {"X-API-Key": self.vexa_api_key}

    def _sarvam_headers(self) -> Dict[str, str]:
        if not self.sarvam_api_key:
            raise VexaSarvamError("SARVAM_API_KEY is not configured.")
        return {
            "api-subscription-key": self.sarvam_api_key,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path_or_url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await client.request(
                method, path_or_url, headers=headers, **kwargs
            )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise VexaSarvamError(f"Network error calling {path_or_url}: {exc}") from exc
        if response.status_code >= 400:
            raise VexaSarvamError(
                f"{path_or_url} returned HTTP {response.status_code}: {response.text[:800]}"
            )
        return response

    async def start_capture(self, meeting_code: str, bot_name: str) -> Dict[str, Any]:
        payload = {
            "platform": "google_meet",
            "native_meeting_id": meeting_code,
            "bot_name": bot_name,
            "recording_enabled": True,
            "transcribe_enabled": False,
        }
        async with httpx.AsyncClient(
            base_url=self.vexa_base_url,
            timeout=httpx.Timeout(settings.VEXA_HTTP_TIMEOUT_SECONDS),
        ) as client:
            response = await self._request(
                client,
                "POST",
                "bots",
                headers={**self._vexa_headers(), "Content-Type": "application/json"},
                json=payload,
            )
            return response.json()

    async def stop_capture(self, meeting_code: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.vexa_base_url,
            timeout=httpx.Timeout(settings.VEXA_HTTP_TIMEOUT_SECONDS),
        ) as client:
            response = await self._request(
                client,
                "DELETE",
                f"bots/google_meet/{meeting_code}",
                headers=self._vexa_headers(),
            )
            return response.json() if response.content else {"stopped": True}

    async def get_meeting_artifacts(self, meeting_code: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.vexa_base_url,
            timeout=httpx.Timeout(settings.VEXA_HTTP_TIMEOUT_SECONDS),
        ) as client:
            response = await self._request(
                client,
                "GET",
                f"transcripts/google_meet/{meeting_code}",
                headers=self._vexa_headers(),
            )
            data = response.json()
            return data if isinstance(data, dict) else {}

    async def wait_for_completed_recording(
        self,
        meeting_code: str,
        *,
        poll_seconds: Optional[int] = None,
        max_wait_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        poll = max(2, int(poll_seconds or settings.VEXA_POLL_INTERVAL_SECONDS))
        deadline = datetime.now(timezone.utc) + timedelta(
            seconds=int(max_wait_seconds or settings.VEXA_MAX_WAIT_SECONDS)
        )
        while datetime.now(timezone.utc) < deadline:
            data = await self.get_meeting_artifacts(meeting_code)
            for recording in data.get("recordings") or []:
                status = str(recording.get("status", "") or "").strip().lower()
                if status in {"completed", "complete", "done"} or recording.get("completed_at"):
                    return recording
            await asyncio.sleep(poll)
        raise VexaSarvamError(
            f"No completed Vexa recording appeared within {settings.VEXA_MAX_WAIT_SECONDS} seconds."
        )

    async def _resolve_audio_url(self, recording: Dict[str, Any]) -> Tuple[str, str]:
        recording_id = str(
            recording.get("recording_id") or recording.get("id") or ""
        ).strip()
        if not recording_id:
            raise VexaSarvamError("Vexa returned a recording without a recording ID.")

        media_file_id = str(
            recording.get("media_file_id") or recording.get("file_id") or ""
        ).strip()
        raw_url = str(recording.get("raw_url") or "").strip()

        if not raw_url:
            async with httpx.AsyncClient(
                base_url=self.vexa_base_url,
                timeout=httpx.Timeout(settings.VEXA_HTTP_TIMEOUT_SECONDS),
            ) as client:
                response = await self._request(
                    client,
                    "GET",
                    f"recordings/{recording_id}/master?type=audio",
                    headers=self._vexa_headers(),
                )
                master = response.json()
            media_file_id = media_file_id or str(
                master.get("media_file_id") or master.get("file_id") or ""
            ).strip()
            raw_url = raw_url or str(master.get("raw_url") or "").strip()

        if raw_url:
            raw_url = urljoin(self.vexa_base_url, raw_url)

        # Current Vexa returns a playable raw_url from the master endpoint.
        # Only require media_file_id when we must construct that URL ourselves.
        if not raw_url and not media_file_id:
            raise VexaSarvamError("Vexa recording has no audio media file ID or raw URL.")
        if not raw_url:
            raw_url = urljoin(
                self.vexa_base_url,
                f"recordings/{recording_id}/media/{media_file_id}/raw?type=audio",
            )
        return recording_id, raw_url

    async def download_recording(self, recording: Dict[str, Any]) -> Tuple[str, bytes, str]:
        recording_id, raw_url = await self._resolve_audio_url(recording)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=30.0,
                read=settings.VEXA_RECORDING_DOWNLOAD_TIMEOUT_SECONDS,
                write=60.0,
                pool=30.0,
            )
        ) as client:
            response = await self._request(
                client,
                "GET",
                raw_url,
                headers=self._vexa_headers(),
            )
        return recording_id, response.content, response.headers.get(
            "content-type", "audio/webm"
        )

    async def transcribe_with_sarvam(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> Tuple[Dict[str, Any], str]:
        if not audio_bytes:
            raise VexaSarvamError("Vexa returned an empty audio recording.")

        job_parameters: Dict[str, Any] = {
            "model": settings.SARVAM_STT_MODEL,
            "mode": settings.SARVAM_STT_MODE,
            "with_diarization": settings.SARVAM_WITH_DIARIZATION,
            "with_timestamps": True,
        }
        if settings.SARVAM_LANGUAGE_CODE.strip():
            job_parameters["language_code"] = settings.SARVAM_LANGUAGE_CODE.strip()
        if settings.SARVAM_NUM_SPEAKERS:
            job_parameters["num_speakers"] = settings.SARVAM_NUM_SPEAKERS
        if settings.SARVAM_KEYTERMS.strip():
            job_parameters["keyterms"] = [
                item.strip()
                for item in settings.SARVAM_KEYTERMS.split(",")
                if item.strip()
            ]

        async with httpx.AsyncClient(
            base_url="https://api.sarvam.ai",
            timeout=httpx.Timeout(settings.SARVAM_HTTP_TIMEOUT_SECONDS),
        ) as client:
            response = await self._request(
                client,
                "POST",
                "speech-to-text/job/v1",
                headers=self._sarvam_headers(),
                json={"job_parameters": job_parameters},
            )
            job_id = str(response.json().get("job_id") or "").strip()
            if not job_id:
                raise VexaSarvamError("Sarvam did not return a batch job ID.")

            upload_response = await self._request(
                client,
                "POST",
                "speech-to-text/job/v1/upload-files",
                headers=self._sarvam_headers(),
                json={"job_id": job_id, "files": [filename]},
            )
            upload_data = upload_response.json()
            upload_url = (
                (upload_data.get("upload_urls") or {}).get(filename, {}) or {}
            ).get("file_url")
            if not upload_url:
                raise VexaSarvamError("Sarvam did not return an upload URL.")

            try:
                # The upload URL is an Azure Blob Storage SAS URL. Azure
                # requires x-ms-blob-type on Put Blob; without it the upload
                # fails with 400 MissingRequiredHeader and the whole primary
                # path falls back to Whisper. Seen live on 2026-10-06.
                put_response = await client.put(
                    upload_url,
                    content=audio_bytes,
                    headers={
                        "Content-Type": content_type or "audio/webm",
                        "x-ms-blob-type": "BlockBlob",
                    },
                    timeout=httpx.Timeout(
                        connect=30.0,
                        read=settings.SARVAM_UPLOAD_TIMEOUT_SECONDS,
                        write=settings.SARVAM_UPLOAD_TIMEOUT_SECONDS,
                        pool=30.0,
                    ),
                )
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                raise VexaSarvamError(
                    f"Network error uploading audio to Sarvam: {exc}"
                ) from exc
            if put_response.status_code >= 400:
                raise VexaSarvamError(
                    f"Sarvam upload returned HTTP {put_response.status_code}: {put_response.text[:800]}"
                )

            await self._request(
                client,
                "POST",
                f"speech-to-text/job/v1/{job_id}/start",
                headers=self._sarvam_headers(),
            )

            deadline = datetime.now(timezone.utc) + timedelta(
                seconds=settings.SARVAM_MAX_WAIT_SECONDS
            )
            while datetime.now(timezone.utc) < deadline:
                status_response = await self._request(
                    client,
                    "GET",
                    f"speech-to-text/job/v1/{job_id}/status",
                    headers=self._sarvam_headers(),
                )
                status_data = status_response.json()
                state = str(status_data.get("job_state") or "").lower()
                successful = int(status_data.get("successful_files_count", 0) or 0)

                if state == "completed":
                    break
                if state in {"failed", "partiallyfailed", "partiallycompleted"}:
                    if successful == 0:
                        raise VexaSarvamError(
                            "Sarvam transcription failed: "
                            + str(
                                status_data.get("error_message")
                                or status_data.get("message")
                                or state
                            )
                        )
                    break
                await asyncio.sleep(settings.SARVAM_POLL_INTERVAL_SECONDS)
            else:
                raise VexaSarvamError(
                    f"Sarvam transcription did not complete within {settings.SARVAM_MAX_WAIT_SECONDS} seconds."
                )

            outputs: List[str] = []
            for detail in status_data.get("job_details") or []:
                for output in detail.get("outputs") or []:
                    name = str(output.get("file_name") or "").strip()
                    if name:
                        outputs.append(name)
            if not outputs:
                raise VexaSarvamError("Sarvam completed without a transcript output.")

            download_response = await self._request(
                client,
                "POST",
                "speech-to-text/job/v1/download-files",
                headers=self._sarvam_headers(),
                json={"job_id": job_id, "files": outputs},
            )
            download_data = download_response.json()
            output_url = (
                (download_data.get("download_urls") or {}).get(outputs[0], {}) or {}
            ).get("file_url")
            if not output_url:
                raise VexaSarvamError("Sarvam did not return a transcript download URL.")

            transcript_response = await self._request(
                client,
                "GET",
                output_url,
                headers={},
            )
            result = transcript_response.json()
            if not isinstance(result, dict):
                raise VexaSarvamError("Sarvam returned an unexpected transcript payload.")
            return result, job_id

    @staticmethod
    def extract_sarvam_entries(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        diarized = result.get("diarized_transcript") or {}
        entries = diarized.get("entries") if isinstance(diarized, dict) else None
        if not isinstance(entries, list):
            entries = result.get("entries") or []

        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                continue
            text = str(
                item.get("transcript")
                or item.get("text")
                or item.get("content")
                or ""
            ).strip()
            if not text:
                continue

            def number(*keys: str) -> float:
                for key in keys:
                    if item.get(key) is not None:
                        try:
                            return float(item.get(key))
                        except (TypeError, ValueError):
                            continue
                return 0.0

            normalized.append(
                {
                    "id": str(item.get("id") or item.get("entry_id") or f"seg_{index:06d}"),
                    "text": text,
                    "speaker": str(
                        item.get("speaker_id")
                        or item.get("speaker")
                        or "Unknown Speaker"
                    ).strip(),
                    "start_seconds": number("start_time_seconds", "start"),
                    "end_seconds": number("end_time_seconds", "end"),
                }
            )

        if normalized:
            return normalized

        transcript_text = str(result.get("transcript") or "").strip()
        return (
            [{
                "id": "seg_000000",
                "text": transcript_text,
                "speaker": "Unknown Speaker",
                "start_seconds": 0.0,
                "end_seconds": 0.0,
            }]
            if transcript_text
            else []
        )

    def _get_projects(self, db: Session) -> List[Project]:
        return (
            db.query(Project)
            .filter(Project.workspace_id == "ws_default", Project.is_system.is_(False))
            .all()
        )

    def _resolve_project(
        self,
        text: str,
        speaker: str,
        meeting: Meeting,
        db: Session,
        projects: List[Project],
    ) -> str:
        projects = [
            project
            for project in projects
            if project.id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
        ]
        if not projects:
            return SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID

        try:
            result = ContextResolutionService().resolve_context(
                source="google_meet",
                content=text,
                sender_participants=[speaker],
                meeting_metadata={
                    "meeting_id": meeting.id,
                    "conference_id": meeting.provider_conference_id,
                    "title": meeting.title,
                    "capture_provider": "vexa",
                    "transcription_provider": "sarvam_saaras",
                },
                candidate_projects=projects,
                tenant_id="default_tenant",
                workspace_id=meeting.workspace_id,
                authorization_constraints={
                    "authorized_project_ids": [project.id for project in projects]
                },
                db=db,
                record=True,
            )
        except Exception as exc:
            logger.warning(
                "vexa_context_resolution_failed: meeting=%s error=%s",
                meeting.id,
                exc,
            )
            return SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID

        target = getattr(result, "project_id", None)
        decision = str(getattr(result, "decision", "") or "")
        confidence = float(getattr(result, "confidence", 0.0) or 0.0)
        allowed = {project.id for project in projects}
        if (
            target in allowed
            and decision in {"resolved", "resolve", "assigned"}
            and confidence >= float(settings.CONTEXT_RESOLUTION_MIN_CONFIDENCE)
        ):
            return target
        return SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID

    def _persist_transcript(
        self,
        meeting: Meeting,
        segments: List[Dict[str, Any]],
        transcription_provider: str,
        transcription_model: str,
        transcription_job_id: str,
        transcription_language_code: str,
        recording_id: str,
        db: Session,
        fallback_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        provider_transcript_id = f"vexa_{meeting.id}"
        existing = (
            db.query(Transcript)
            .filter(
                Transcript.provider_transcript_id.in_(
                    [
                        provider_transcript_id,
                        f"vexa_sarvam_{meeting.id}",
                        f"vexa_whisper_{meeting.id}",
                    ]
                )
            )
            .first()
        )
        if existing:
            capture = get_capture_metadata(meeting)
            evidence_projects = (
                db.query(Evidence.project_id)
                .filter(
                    Evidence.meeting_id == meeting.id,
                    Evidence.project_id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
                )
                .distinct()
                .all()
            )
            resolved_projects = sorted(
                str(row[0]) for row in evidence_projects if row[0]
            )
            if not bool(capture.get("pipeline_processed")):
                meeting.project_id = (
                    resolved_projects[0]
                    if len(resolved_projects) == 1
                    else SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
                )
                PipelineCoordinator().process_meeting_with_context(
                    meeting_id=meeting.id,
                    project_id=meeting.project_id,
                    db=db,
                    actor_id=meeting.user_id,
                    workspace_id=meeting.workspace_id,
                    tenant_id="default_tenant",
                    correlation_id=f"vexa:{meeting.id}:retry",
                )
                _set_capture_metadata(meeting, {"pipeline_processed": True})
            _set_capture_metadata(
                meeting,
                {
                    "status": "completed",
                    "processed": True,
                    "transcription_provider": transcription_provider,
                    "transcription_model": transcription_model,
                    "transcription_job_id": transcription_job_id,
                    "transcription_fallback_used": transcription_provider != "sarvam_saaras",
                    "transcription_fallback_reason": fallback_reason,
                    "sarvam_job_id": (
                        transcription_job_id
                        if transcription_provider == "sarvam_saaras"
                        else capture.get("sarvam_job_id")
                    ),
                    "whisper_job_id": (
                        transcription_job_id
                        if transcription_provider == "whisper_faster_whisper"
                        else capture.get("whisper_job_id")
                    ),
                    "recording_id": recording_id or capture.get("recording_id"),
                    "entries_count": len(existing.entries),
                    "resolved_projects": resolved_projects,
                },
            )
            meeting.end_time = meeting.end_time or datetime.now(timezone.utc)
            meeting.status = "ENDED"
            db.commit()
            return {
                "transcript_id": existing.id,
                "entries_count": len(existing.entries),
                "resolved_projects": resolved_projects,
            }

        if not segments:
            raise VexaSarvamError(
                f"{transcription_provider} returned no transcript segments."
            )

        transcript = Transcript(
            meeting_id=meeting.id,
            provider="google",
            provider_transcript_id=provider_transcript_id,
            state="AVAILABLE",
            start_time=meeting.start_time or datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            metadata_json=_json_dump(
                {
                    "capture_provider": "vexa",
                    "transcription_provider": transcription_provider,
                    "transcription_job_id": transcription_job_id,
                    "transcription_fallback_used": transcription_provider != "sarvam_saaras",
                    "transcription_fallback_reason": fallback_reason,
                    "recording_id": recording_id,
                    "model": transcription_model,
                    "mode": (
                        settings.SARVAM_STT_MODE
                        if transcription_provider == "sarvam_saaras"
                        else None
                    ),
                }
            ),
        )
        db.add(transcript)
        db.flush()

        projects = self._get_projects(db)
        participants: Dict[str, Participant] = {}
        routed_projects = set()

        for index, segment in enumerate(segments):
            speaker = segment["speaker"]
            participant = participants.get(speaker)
            if participant is None:
                participant = Participant(
                    meeting_id=meeting.id,
                    provider_participant_id=f"vexa:{speaker}",
                    display_name=speaker,
                    metadata_json=_json_dump(
                        {
                            "capture_provider": "vexa",
                            "speaker_source": (
                                "sarvam_diarization"
                                if transcription_provider == "sarvam_saaras"
                                else "whisper_no_diarization"
                            ),
                        }
                    ),
                )
                db.add(participant)
                db.flush()
                participants[speaker] = participant

            base_time = meeting.start_time or datetime.now(timezone.utc)
            start_time = base_time + timedelta(seconds=max(0.0, segment["start_seconds"]))
            end_time = base_time + timedelta(seconds=max(0.0, segment["end_seconds"]))
            entry_key = segment["id"] or f"seg_{index:06d}"

            entry = TranscriptEntry(
                transcript_id=transcript.id,
                provider="google",
                provider_entry_id=f"vexa_{transcription_provider}:{entry_key}",
                participant_id=participant.id,
                text=segment["text"],
                language_code=transcription_language_code or "unknown",
                start_time=start_time,
                end_time=end_time,
                metadata_json=_json_dump(
                    {
                        "capture_provider": "vexa",
                        "transcription_provider": transcription_provider,
                        "transcription_model": transcription_model,
                        "speaker_id": speaker,
                        "segment_start_seconds": segment["start_seconds"],
                        "segment_end_seconds": segment["end_seconds"],
                    }
                ),
            )
            db.add(entry)
            db.flush()

            target_project = self._resolve_project(
                segment["text"], speaker, meeting, db, projects
            )
            routed_projects.add(target_project)

            source_event_id = f"vexa:{meeting.provider_conference_id}:{entry.provider_entry_id}"
            source_event = (
                db.query(SourceEvent)
                .filter(
                    SourceEvent.source == "google_meet",
                    SourceEvent.source_event_id == source_event_id,
                )
                .first()
            )
            if source_event is None:
                source_event = SourceEvent(
                    tenant_id="default_tenant",
                    project_id=target_project,
                    source="google_meet",
                    source_event_id=source_event_id,
                    event_type="transcript_entry",
                    actor_id=speaker,
                    occurred_at=start_time,
                    payload_json=_json_dump(
                        {
                            "text": segment["text"],
                            "speaker_name": speaker,
                            "start_time": start_time.isoformat(),
                            "end_time": end_time.isoformat(),
                            "meeting_id": meeting.id,
                            "conference_id": meeting.provider_conference_id,
                            "capture_provider": "vexa",
                            "transcription_provider": transcription_provider,
                            "transcription_model": transcription_model,
                        }
                    ),
                    status="received",
                )
                db.add(source_event)
                db.flush()

            existing_evidence = (
                db.query(Evidence)
                .filter(Evidence.source_event_id == source_event.event_id)
                .first()
            )
            if existing_evidence is None:
                db.add(
                    Evidence(
                        project_id=source_event.project_id,
                        source="google_meet",
                        source_event_id=source_event.event_id,
                        meeting_id=meeting.id,
                        transcript_id=transcript.id,
                        transcript_entry_id=entry.id,
                        actor_id=speaker,
                        occurred_at=start_time,
                        content=segment["text"],
                        metadata_json=_json_dump(
                            {
                                "capture_provider": "vexa",
                                "transcription_provider": transcription_provider,
                                "transcription_model": transcription_model,
                                "speaker_id": speaker,
                            }
                        ),
                    )
                )

        db.commit()

        resolved_projects = sorted(
            project_id
            for project_id in routed_projects
            if project_id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
        )
        meeting.project_id = (
            resolved_projects[0]
            if len(resolved_projects) == 1
            else SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
        )
        meeting.end_time = datetime.now(timezone.utc)
        db.commit()

        PipelineCoordinator().process_meeting_with_context(
            meeting_id=meeting.id,
            project_id=meeting.project_id,
            db=db,
            actor_id=meeting.user_id,
            workspace_id=meeting.workspace_id,
            tenant_id="default_tenant",
            correlation_id=f"vexa:{meeting.id}",
        )

        _set_capture_metadata(
            meeting,
            {
                "status": "completed",
                "processed": True,
                "pipeline_processed": True,
                "transcription_provider": transcription_provider,
                "transcription_model": transcription_model,
                "transcription_job_id": transcription_job_id,
                "transcription_fallback_used": transcription_provider != "sarvam_saaras",
                "transcription_fallback_reason": fallback_reason,
                "sarvam_job_id": (
                    transcription_job_id
                    if transcription_provider == "sarvam_saaras"
                    else None
                ),
                "whisper_job_id": (
                    transcription_job_id
                    if transcription_provider == "whisper_faster_whisper"
                    else None
                ),
                "recording_id": recording_id,
                "entries_count": len(segments),
                "resolved_projects": resolved_projects,
            },
        )
        meeting.status = "ENDED"
        db.commit()

        return {
            "transcript_id": transcript.id,
            "entries_count": len(segments),
            "resolved_projects": resolved_projects,
        }

    async def _transcribe_with_fallback(
        self,
        audio_bytes: bytes,
        filename: str,
        content_type: str,
        meeting_id: str,
    ) -> Tuple[List[Dict[str, Any]], str, str, str, str, Optional[str]]:
        """Try Sarvam first, then self-hosted Whisper on the same audio."""
        fallback_reason: Optional[str] = None

        if self.sarvam_api_key:
            try:
                result, job_id = await self.transcribe_with_sarvam(
                    audio_bytes,
                    filename,
                    content_type,
                )
                segments = self.extract_sarvam_entries(result)
                if segments:
                    return (
                        segments,
                        "sarvam_saaras",
                        settings.SARVAM_STT_MODEL,
                        job_id,
                        str(result.get("language_code") or "unknown"),
                        None,
                    )
                fallback_reason = "Sarvam returned no usable transcript segments."
            except Exception as exc:
                fallback_reason = str(exc)[:1000]
                logger.warning(
                    "sarvam_primary_failed_using_whisper_fallback: meeting=%s error=%s",
                    meeting_id,
                    fallback_reason,
                )
        else:
            fallback_reason = "SARVAM_API_KEY is not configured."

        if not settings.WHISPER_ENABLED:
            raise VexaSarvamError(
                f"Sarvam transcription was unavailable: {fallback_reason}; "
                "WHISPER_ENABLED is false, so no local fallback is available."
            )

        try:
            result, job_id = await WhisperTranscriptionService().transcribe(
                audio_bytes,
                filename,
            )
            segments = list(result.get("segments") or [])
            if not segments:
                raise WhisperFallbackError("Whisper returned no usable transcript segments.")
            return (
                segments,
                "whisper_faster_whisper",
                settings.WHISPER_MODEL,
                job_id,
                str(result.get("language_code") or "unknown"),
                fallback_reason,
            )
        except Exception as whisper_exc:
            raise VexaSarvamError(
                f"Sarvam primary failed: {fallback_reason}; "
                f"Whisper fallback failed: {whisper_exc}"
            ) from whisper_exc

    async def process_meeting(self, meeting_id: str, db: Session) -> Dict[str, Any]:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            raise VexaSarvamError(f"Meeting '{meeting_id}' not found.")

        capture = get_capture_metadata(meeting)
        if capture.get("processed"):
            return {"status": "completed", "meeting_id": meeting_id}

        meeting_code = str(
            capture.get("meeting_code") or meeting.provider_conference_id
        )

        try:
            _set_capture_metadata(meeting, {"status": "waiting_for_recording"})
            db.commit()

            recording = await self.wait_for_completed_recording(meeting_code)
            _set_capture_metadata(
                meeting,
                {
                    "status": "recording_ready",
                    "recording_id": recording.get("recording_id") or recording.get("id"),
                },
            )
            db.commit()

            recording_id, audio_bytes, content_type = await self.download_recording(recording)
            _set_capture_metadata(
                meeting,
                {
                    "status": (
                        "transcribing_sarvam"
                        if self.sarvam_api_key
                        else "transcribing_whisper"
                    ),
                    "transcription_provider": (
                        "sarvam_saaras"
                        if self.sarvam_api_key
                        else "whisper_faster_whisper"
                    ),
                },
            )
            db.commit()

            content_type_lower = str(content_type or "").lower()
            if "wav" in content_type_lower:
                audio_extension = ".wav"
            elif "webm" in content_type_lower:
                audio_extension = ".webm"
            elif "mp3" in content_type_lower or "mpeg" in content_type_lower:
                audio_extension = ".mp3"
            elif "ogg" in content_type_lower:
                audio_extension = ".ogg"
            else:
                audio_extension = ".audio"

            audio_filename = f"{meeting.id}{audio_extension}"
            (
                segments,
                transcription_provider,
                transcription_model,
                transcription_job_id,
                transcription_language_code,
                fallback_reason,
            ) = await self._transcribe_with_fallback(
                audio_bytes,
                audio_filename,
                content_type,
                meeting.id,
            )

            _set_capture_metadata(
                meeting,
                {
                    "status": "ingesting",
                    "transcription_provider": transcription_provider,
                    "transcription_model": transcription_model,
                    "transcription_job_id": transcription_job_id,
                    "transcription_fallback_used": transcription_provider != "sarvam_saaras",
                    "transcription_fallback_reason": fallback_reason,
                    "sarvam_job_id": (
                        transcription_job_id
                        if transcription_provider == "sarvam_saaras"
                        else None
                    ),
                    "whisper_job_id": (
                        transcription_job_id
                        if transcription_provider == "whisper_faster_whisper"
                        else None
                    ),
                },
            )
            db.commit()

            return self._persist_transcript(
                meeting,
                segments,
                transcription_provider,
                transcription_model,
                transcription_job_id,
                transcription_language_code,
                recording_id,
                db,
                fallback_reason=fallback_reason,
            )
        except Exception as exc:
            # Do not accidentally commit partial transcript/evidence rows from a failed
            # transaction. The meeting capture state is recorded separately below.
            db.rollback()
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first() or meeting
            _set_capture_metadata(
                meeting,
                {
                    "status": "failed",
                    "error": str(exc)[:1000],
                    "processed": False,
                    "pipeline_processed": False,
                },
            )
            db.commit()
            raise


async def process_vexa_meeting_background(meeting_id: str) -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        await VexaSarvamService().process_meeting(meeting_id=meeting_id, db=db)
    except Exception as exc:
        logger.error(
            "vexa_sarvam_processing_failed: meeting=%s error=%s",
            meeting_id,
            exc,
        )
    finally:
        db.close()
