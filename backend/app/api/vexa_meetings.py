import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.meeting import Meeting
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.models.user import User
from app.services.vexa_sarvam_service import (
    VexaSarvamError,
    VexaSarvamService,
    _set_capture_metadata,
    get_capture_metadata,
    parse_google_meet_code,
    process_vexa_meeting_background,
)

router = APIRouter(prefix="/vexa", tags=["Vexa Google Meet"])


class VexaMeetingStartRequest(BaseModel):
    meeting_url: str = Field(..., min_length=1)


@router.post("/meetings/start")
async def start_vexa_capture(
    payload: VexaMeetingStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.VEXA_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vexa capture is disabled. Set VEXA_ENABLED=true.",
        )
    if not settings.SARVAM_API_KEY.strip() and not settings.WHISPER_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No transcription provider is configured. Set SARVAM_API_KEY or enable WHISPER_ENABLED.",
        )

    try:
        meeting_code = parse_google_meet_code(payload.meeting_url)
    except VexaSarvamError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.user_id == current_user.id,
            Meeting.provider == "google",
            Meeting.provider_conference_id == meeting_code,
        )
        .order_by(Meeting.created_at.desc())
        .first()
    )

    # A Meet link can be reused for a later session. Start a fresh Synora
    # meeting record once the previous capture has been fully processed.
    if meeting and get_capture_metadata(meeting).get("processed"):
        meeting = None

    if not meeting:
        meeting = Meeting(
            workspace_id="ws_default",
            project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
            user_id=current_user.id,
            provider="google",
            provider_conference_id=meeting_code,
            title="Google Meet (Vexa capture)",
            start_time=datetime.now(timezone.utc),
            status="ACTIVE",
            metadata_json=json.dumps({}),
        )
        db.add(meeting)
        db.flush()

    capture = get_capture_metadata(meeting)
    if capture.get("status") in {
        "starting",
        "waiting_for_recording",
        "recording_ready",
        "transcribing",
        "transcribing_sarvam",
        "transcribing_whisper",
        "ingesting",
        "stopping",
    }:
        return {
            "ok": True,
            "meeting_id": meeting.id,
            "meeting_code": meeting_code,
            "status": capture.get("status"),
            "message": "A Vexa capture is already active for this meeting.",
        }

    try:
        response = await VexaSarvamService().start_capture(
            meeting_code=meeting_code,
            bot_name=settings.VEXA_BOT_NAME,
        )
    except VexaSarvamError as exc:
        _set_capture_metadata(meeting, {"status": "failed", "error": str(exc)[:1000]})
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc))

    _set_capture_metadata(
        meeting,
        {
            "status": "starting",
            "meeting_code": meeting_code,
            "vexa_bot_name": settings.VEXA_BOT_NAME,
            "capture_started_at": datetime.now(timezone.utc).isoformat(),
            "vexa_bot_response": response,
            "processed": False,
            "error": None,
        },
    )
    meeting.status = "ACTIVE"
    db.commit()

    background_tasks.add_task(process_vexa_meeting_background, meeting.id)

    return {
        "ok": True,
        "meeting_id": meeting.id,
        "meeting_code": meeting_code,
        "status": "starting",
        "message": "Vexa capture started. Admit the bot in Google Meet if it appears in the waiting room.",
    }


@router.get("/meetings/{meeting_id}")
async def get_vexa_capture_status(
    meeting_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == current_user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    capture = get_capture_metadata(meeting)
    return {
        "ok": True,
        "meeting_id": meeting.id,
        "meeting_code": capture.get("meeting_code") or meeting.provider_conference_id,
        "status": capture.get("status", "idle"),
        "processed": bool(capture.get("processed")),
        "entries_count": capture.get("entries_count", 0),
        "resolved_projects": capture.get("resolved_projects", []),
        "recording_id": capture.get("recording_id"),
        "transcription_provider": capture.get("transcription_provider"),
        "transcription_model": capture.get("transcription_model"),
        "transcription_job_id": capture.get("transcription_job_id"),
        "transcription_fallback_used": bool(capture.get("transcription_fallback_used")),
        "transcription_fallback_reason": capture.get("transcription_fallback_reason"),
        "sarvam_job_id": capture.get("sarvam_job_id"),
        "whisper_job_id": capture.get("whisper_job_id"),
        "bot_status": capture.get("bot_status"),
        "bot_status_updated_at": capture.get("bot_status_updated_at"),
        "bot_container_id": capture.get("bot_container_id"),
        "error": capture.get("error"),
    }


@router.post("/meetings/{meeting_id}/stop")
async def stop_vexa_capture(
    meeting_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == current_user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    capture = get_capture_metadata(meeting)
    meeting_code = capture.get("meeting_code") or meeting.provider_conference_id

    if capture.get("processed"):
        return {
            "ok": True,
            "meeting_id": meeting.id,
            "status": "completed",
            "message": "This meeting has already been processed.",
        }

    try:
        response = await VexaSarvamService().stop_capture(meeting_code)
    except VexaSarvamError as exc:
        _set_capture_metadata(meeting, {"status": "failed", "error": str(exc)[:1000]})
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc))

    # Vexa's DELETE is asynchronous: it returns a stopping state while the
    # recording is finalized. Keep Synora processing alive and let the same
    # post-meeting worker wait for the completed recording.
    _set_capture_metadata(
        meeting,
        {
            "status": "stopping",
            "stop_requested_at": datetime.now(timezone.utc).isoformat(),
            "vexa_stop_response": response,
        },
    )
    meeting.status = "ACTIVE"
    db.commit()
    # The capture worker was queued when capture started. Vexa stop is
    # asynchronous, so let that worker continue polling for the finalized
    # recording rather than starting a second concurrent pipeline.
    return {
        "ok": True,
        "meeting_id": meeting.id,
        "status": "stopping",
        "message": "Vexa stop requested. Synora will process the recording once Vexa finalizes it.",
        "vexa": response,
    }


@router.post("/meetings/{meeting_id}/process")
async def process_vexa_capture(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == current_user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    capture = get_capture_metadata(meeting)
    status_value = str(capture.get("status") or "").lower()
    if capture.get("processed"):
        return {
            "ok": True,
            "meeting_id": meeting.id,
            "status": "completed",
            "message": "This meeting has already been processed.",
        }

    if status_value in {
        "starting",
        "waiting_for_recording",
        "recording_ready",
        "transcribing",
        "transcribing_sarvam",
        "transcribing_whisper",
        "ingesting",
        "stopping",
    }:
        return {
            "ok": True,
            "meeting_id": meeting.id,
            "status": status_value,
            "message": "Meeting processing is already active.",
        }

    background_tasks.add_task(process_vexa_meeting_background, meeting.id)
    return {
        "ok": True,
        "meeting_id": meeting.id,
        "status": "processing_queued",
    }
