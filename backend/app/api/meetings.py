from datetime import datetime, timezone
import json
import logging
import re
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import (
    get_current_user,
    get_db,
    get_google_meet_service,
    get_pipeline_coordinator,
)
from app.core.exceptions import (
    ConnectionNotFoundError,
    CredentialsExpiredError,
    GoogleMeetError,
    GoogleMeetPermissionError,
    GoogleMeetRateLimitError,
    GoogleMeetResourceNotFoundError,
    GoogleMeetTransientError,
)
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.user import User
from app.schemas.meeting import (
    MeetingEvidenceRouteRequest,
    MeetingDetailRead,
    MeetingRead,
    MeetingSyncResponse,
    TranscriptEntryInput,
    TranscriptEntryRead,
    TranscriptIngestRequest,
    TranscriptIngestResponse,
    TranscriptRead,
)
from app.services.google_meet import GoogleMeetService
from app.services.meeting_session_intelligence import MeetingSessionIntelligenceService
from app.services.pipeline_coordinator import PipelineCoordinator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Google Meet Ingestion"])


@router.post(
    "/sync",
    response_model=MeetingSyncResponse,
    summary="Reconcile Google Meet Conferences & Transcripts (recovery)",
    description=(
        "Manual reconciliation/recovery fallback for the event-driven pipeline. "
        "Prefer automatic transcript synchronization via Workspace Events + Pub/Sub. "
        "Use this endpoint to recover events missed during outages or failed processing. "
        "Bounded: syncs at most max_conferences records into the given project."
    ),
)
async def sync_google_meetings(
    max_conferences: int = Query(10, ge=1, le=50, description="Max conference records to discover"),
    filter_query: Optional[str] = Query(None, description="Optional Google Meet filter expression"),
    project_id: str = Query("proj_default", description="Associated Synesis project ID"),
    meet_service: GoogleMeetService = Depends(get_google_meet_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manual reconciliation for the event-driven transcript pipeline.
    The primary ingestion path is automatic: Workspace Events -> Pub/Sub ->
    Synesis worker -> Meet REST retrieval. Use this endpoint only to recover
    missed or failed events. Idempotent: re-running updates existing records
    without creating duplicates.
    """
    try:
        response = await meet_service.sync_conferences(
            user_id=current_user.id,
            db=db,
            max_conferences=max_conferences,
            filter_query=filter_query,
            project_id=project_id,
        )
        return response

    except ConnectionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "connection_not_found",
                "message": str(exc),
                "hint": "Please authorize your Google account via GET /auth/google first.",
            },
        )
    except CredentialsExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "credentials_expired",
                "message": str(exc),
                "hint": "Please re-authenticate your Google account via GET /auth/google.",
            },
        )
    except GoogleMeetPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "insufficient_permissions",
                "message": str(exc),
                "hint": "Verify your Google account has permission to view Meet conference records and scopes are granted.",
            },
        )
    except GoogleMeetRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": str(exc),
                "retry_after": exc.retry_after,
            },
        )
    except GoogleMeetTransientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "google_service_error",
                "message": str(exc),
            },
        )
    except GoogleMeetError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": exc.error_code or "meet_api_error",
                "message": str(exc),
            },
        )


@router.get(
    "",
    response_model=List[MeetingRead],
    summary="List Synchronized Meetings",
    description="Lists all synchronized meetings for the authenticated user.",
)
async def list_meetings(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Meeting).filter(Meeting.user_id == current_user.id)
    if status_filter:
        query = query.filter(Meeting.status == status_filter)

    meetings = query.order_by(Meeting.created_at.desc()).offset(offset).limit(limit).all()
    return [MeetingRead.model_validate(m) for m in meetings]


@router.get(
    "/{meeting_id}/intelligence",
    summary="Get Meet Session Intelligence",
    description=(
        "Returns the Meet-specific session projection: timestamped transcript windows, "
        "participants, topics derived from extracted knowledge, action items, key "
        "decisions/requirements/questions, and the memory version delta. This is "
        "a projection over shared Synora memory, not a separate memory store."
    ),
)
async def get_meeting_intelligence(
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting '{meeting_id}' not found.",
        )

    service = MeetingSessionIntelligenceService()
    try:
        metadata = json.loads(meeting.metadata_json or "{}")
    except (TypeError, ValueError):
        metadata = {}
    cached = metadata.get("session_intelligence")
    if cached:
        return cached

    try:
        return service.get_or_build(meeting_id=meeting_id, db=db, persist=True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/{meeting_id}",
    response_model=MeetingDetailRead,
    summary="Get Meeting Details",
    description="Gets detailed information for a specific meeting including participants and transcripts.",
)
async def get_meeting(
    meeting_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.participants),
            joinedload(Meeting.transcripts).joinedload(Transcript.entries),
        )
        .filter(
            Meeting.id == meeting_id,
            Meeting.user_id == current_user.id,
        )
        .first()
    )
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting '{meeting_id}' not found for user '{current_user.id}'.",
        )

    detail = MeetingDetailRead.model_validate(meeting)
    try:
        metadata = json.loads(meeting.metadata_json or "{}")
    except (TypeError, ValueError):
        metadata = {}
    detail.session_intelligence = metadata.get("session_intelligence")
    return detail


@router.get(
    "/{meeting_id}/transcript",
    response_model=TranscriptRead,
    summary="Get Meeting Transcript and Entries",
    description="Returns the transcript and structured spoken utterances for a meeting.",
)
async def get_meeting_transcript(
    meeting_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.id == meeting_id,
            Meeting.user_id == current_user.id,
        )
        .first()
    )
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting '{meeting_id}' not found.",
        )

    transcript = (
        db.query(Transcript)
        .options(
            joinedload(Transcript.entries).joinedload(TranscriptEntry.participant),
        )
        .filter(Transcript.meeting_id == meeting_id)
        .first()
    )
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No transcript found for meeting '{meeting_id}'.",
        )

    # Format transcript with participant display names populated
    entries_read = []
    for entry in transcript.entries:
        entry_read = TranscriptEntryRead(
            id=entry.id,
            transcript_id=entry.transcript_id,
            provider_entry_id=entry.provider_entry_id,
            participant_id=entry.participant_id,
            participant_display_name=entry.participant.display_name if entry.participant else None,
            text=entry.text,
            language_code=entry.language_code,
            start_time=entry.start_time,
            end_time=entry.end_time,
            created_at=entry.created_at,
        )
        entries_read.append(entry_read)

    return TranscriptRead(
        id=transcript.id,
        meeting_id=transcript.meeting_id,
        provider=transcript.provider,
        provider_transcript_id=transcript.provider_transcript_id,
        state=transcript.state,
        start_time=transcript.start_time,
        end_time=transcript.end_time,
        docs_destination_url=transcript.docs_destination_url,
        created_at=transcript.created_at,
        entries=entries_read,
    )




def parse_raw_transcript_text(raw_text: str) -> List[TranscriptEntryInput]:
    """
    Parses arbitrary meeting transcript text into structured speaker utterances.
    Supports:
    - Colon format: 'Speaker Name: text' or 'Speaker Name [10:02 AM]: text'
    - Bracketed speaker format: '[10:02] Speaker Name: text'
    - WebVTT / SRT subtitle format (<v Speaker>Text)
    - Google Meet / Teams pasted transcript blocks (Speaker line followed by text line)
    """
    entries: List[TranscriptEntryInput] = []
    lines = raw_text.strip().splitlines()

    current_speaker = "Speaker 1"
    pattern_colon = re.compile(
        r"^(?:\[(?P<time1>[\d:APMapm\s\.\,\-]+)\]\s*)?(?P<speaker>[A-Za-z0-9\s\.\(\)\-_@]+?)(?:\s*\[(?P<time2>[\d:APMapm\s\.\,\-]+)\])?:\s*(?P<text>.+)$"
    )

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if line.startswith("WEBVTT") or line.isdigit() or "-->" in line:
            i += 1
            continue

        m = pattern_colon.match(line)
        if m:
            spk = m.group("speaker").strip()
            txt = m.group("text").strip()
            if spk.startswith("<v ") and spk.endswith(">"):
                spk = spk[3:-1].strip()
            entries.append(TranscriptEntryInput(speaker=spk, text=txt))
            current_speaker = spk
            i += 1
            continue

        # Multiline block format (e.g. Speaker Name \n 10:02 AM \n Spoken text)
        if len(line) < 40 and not line.endswith((".", "?", "!", ";")) and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if (re.match(r"^[\d:APMapm\s]+$", next_line) or "-->" in next_line) and i + 2 < len(lines):
                text_line = lines[i + 2].strip()
                if text_line:
                    entries.append(TranscriptEntryInput(speaker=line, text=text_line))
                    current_speaker = line
                    i += 3
                    continue
            elif next_line and not (len(next_line) < 40 and not next_line.endswith((".", "?", "!", ";"))):
                entries.append(TranscriptEntryInput(speaker=line, text=next_line))
                current_speaker = line
                i += 2
                continue

        entries.append(TranscriptEntryInput(speaker=current_speaker, text=line))
        i += 1

    return entries


@router.post(
    "/ingest-transcript",
    response_model=TranscriptIngestResponse,
    summary="Ingest Transcript (Zero-Quota Alternative)",
    description=(
        "Ingests raw transcript text, dialogue entries, or subtitles from any source "
        "(Google Meet live captions, pasted notes, Zoom/Teams, local Whisper) without Google Cloud API quota limits."
    ),
)
async def ingest_transcript_endpoint(
    payload: TranscriptIngestRequest,
    coordinator: PipelineCoordinator = Depends(get_pipeline_coordinator),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Determine entries
    parsed_entries: List[TranscriptEntryInput] = []
    if payload.entries and len(payload.entries) > 0:
        parsed_entries = payload.entries
    elif payload.raw_transcript and payload.raw_transcript.strip():
        parsed_entries = parse_raw_transcript_text(payload.raw_transcript)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide either 'raw_transcript' text or structured 'entries'.",
        )

    if not parsed_entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not extract any dialogue utterances from the provided transcript.",
        )

    # 2. Create Meeting
    meeting_id = f"mtg_{uuid.uuid4().hex[:12]}"
    conf_id = f"manual_{uuid.uuid4().hex[:10]}"
    meeting = Meeting(
        id=meeting_id,
        project_id=payload.project_id,
        user_id=current_user.id,
        provider=payload.provider,
        provider_conference_id=conf_id,
        title=payload.title or "Imported Meeting Transcript",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        status="ENDED",
    )
    db.add(meeting)

    # 3. Create Participants
    participants_map = {}
    for entry_in in parsed_entries:
        spk_name = entry_in.speaker.strip()
        if spk_name not in participants_map:
            clean_id = re.sub(r"[^a-zA-Z0-9_]", "_", spk_name.lower())[:24]
            part = Participant(
                id=f"part_{meeting_id}_{clean_id}_{uuid.uuid4().hex[:4]}",
                meeting_id=meeting_id,
                provider_participant_id=f"part_{clean_id}",
                display_name=spk_name,
            )
            db.add(part)
            participants_map[spk_name] = part

    # 4. Create Transcript
    transcript_id = f"trsc_{uuid.uuid4().hex[:12]}"
    transcript = Transcript(
        id=transcript_id,
        meeting_id=meeting_id,
        provider=payload.provider,
        provider_transcript_id=f"trsc_{uuid.uuid4().hex[:10]}",
        state="AVAILABLE",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
    )
    db.add(transcript)

    # 5. Create Transcript Entries
    for idx, entry_in in enumerate(parsed_entries):
        part = participants_map.get(entry_in.speaker.strip())
        tent = TranscriptEntry(
            id=f"tent_{uuid.uuid4().hex[:12]}",
            transcript_id=transcript_id,
            provider=payload.provider,
            provider_entry_id=f"entry_{meeting_id}_{idx}",
            participant_id=part.id if part else None,
            text=entry_in.text,
            language_code="en-US",
            start_time=entry_in.start_time or datetime.now(timezone.utc),
            end_time=entry_in.end_time or datetime.now(timezone.utc),
        )
        db.add(tent)

    db.commit()
    db.refresh(meeting)

    # 6. Auto-process knowledge pipeline if requested
    pipeline_res_dict = None
    if payload.auto_process:
        try:
            pipeline_result = coordinator.process_meeting(
                meeting_id=meeting.id,
                project_id=payload.project_id,
                db=db,
                actor_id=current_user.id,
            )
            pipeline_res_dict = (
                pipeline_result.model_dump()
                if hasattr(pipeline_result, "model_dump")
                else pipeline_result.__dict__
            )
        except Exception as exc:
            logger.error(f"Auto-processing pipeline failed for meeting '{meeting.id}': {exc}", exc_info=True)

    return TranscriptIngestResponse(
        success=True,
        message=f"Successfully ingested {len(parsed_entries)} utterances across {len(participants_map)} participants.",
        meeting_id=meeting.id,
        project_id=payload.project_id,
        title=meeting.title,
        entries_count=len(parsed_entries),
        pipeline_result=pipeline_res_dict,
    )


@router.post(
    "/{meeting_id}/route-evidence",
    summary="Route a multi-project meeting's evidence across candidate projects",
    description=(
        "Files each evidence row under its best-matching project from the supplied "
        "candidate set, using the same resolver WhatsApp routing uses. A meeting "
        "may legitimately discuss several projects, but Evidence.project_id holds "
        "exactly one, so the split happens per row. Rows the resolver cannot "
        "separate confidently are left untouched and reported as unresolved rather "
        "than guessed at."
    ),
)
async def route_meeting_evidence(
    meeting_id: str,
    payload: MeetingEvidenceRouteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == current_user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting '{meeting_id}' not found for user '{current_user.id}'.",
        )

    from app.services.meeting_evidence_router import MeetingEvidenceRouter

    try:
        return MeetingEvidenceRouter().route_meeting_evidence(
            meeting_id=meeting_id,
            candidate_project_ids=payload.candidate_project_ids,
            db=db,
            tenant_id="default_tenant",
            actor_id=current_user.id,
            dry_run=payload.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


