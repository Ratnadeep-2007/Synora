import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_google_meet_service
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
from app.models.meet_event_record import MeetEventRecord
from app.models.meet_subscription import MeetSubscriptionStatus
from app.models.user import User
from app.schemas.meet_events import (
    MeetEventRecordRead,
    MeetReconcileResponse,
    MeetSubscriptionCreate,
    MeetSubscriptionRead,
    PubSubPushResponse,
)
from app.services.google_meet import GoogleMeetService
from app.services.meet_event_worker import (
    MeetEventWorker,
    TRANSCRIPT_READY_EVENT,
    UNASSIGNED_PROJECT_ID,
)
from app.services.metrics import metrics
from app.services.workspace_events_service import (
    DuplicateSubscriptionError,
    WorkspaceEventsError,
    WorkspaceEventsService,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Meet Event Pipeline"])
subscriptions_router = APIRouter(prefix="/meet/subscriptions", tags=["Meet Subscriptions"])
pubsub_router = APIRouter(prefix="/pubsub", tags=["Pub/Sub Ingestion"])

workspace_events_service = WorkspaceEventsService()
meet_event_worker = MeetEventWorker()


def _read_dict_to_schema(data: Dict[str, Any]) -> MeetSubscriptionRead:
    return MeetSubscriptionRead(**data)


@subscriptions_router.post(
    "",
    response_model=MeetSubscriptionRead,
    summary="Subscribe to Meet transcript notifications",
    description=(
        "Registers a Google Workspace Events subscription for native Meet "
        "transcription notifications. The subscription is notification "
        "infrastructure only; transcript content is retrieved via Meet REST."
    ),
)
async def create_meet_subscription(
    body: MeetSubscriptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        subscription = workspace_events_service.create_subscription(
            user_id=current_user.id,
            target_resource=body.target_resource,
            db=db,
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            target_type=body.target_type,
            event_types=body.event_types,
            pubsub_topic=body.pubsub_topic,
        )
    except WorkspaceEventsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "subscription_failed", "message": str(exc)},
        )
    return _read_dict_to_schema(workspace_events_service.to_read_dict(subscription))


@subscriptions_router.get(
    "",
    response_model=List[MeetSubscriptionRead],
    summary="List Meet subscriptions",
)
async def list_meet_subscriptions(
    project_id: Optional[str] = Query(None),
    sub_status: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subs = workspace_events_service.list_subscriptions(
        db=db, user_id=current_user.id, project_id=project_id, status=sub_status
    )
    return [_read_dict_to_schema(workspace_events_service.to_read_dict(s)) for s in subs]


@subscriptions_router.get(
    "/expiring",
    response_model=List[MeetSubscriptionRead],
    summary="List subscriptions nearing expiration",
)
async def list_expiring_subscriptions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workspace_events_service.refresh_expiration_statuses(db)
    subs = workspace_events_service.list_subscriptions(
        db=db, user_id=current_user.id, status=MeetSubscriptionStatus.EXPIRING.value
    )
    expired = workspace_events_service.list_subscriptions(
        db=db, user_id=current_user.id, status=MeetSubscriptionStatus.EXPIRED.value
    )
    return [_read_dict_to_schema(workspace_events_service.to_read_dict(s)) for s in subs + expired]


@subscriptions_router.post(
    "/refresh-expirations",
    summary="Scan subscriptions and mark expiring/expired",
)
async def refresh_subscription_expirations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transitions = workspace_events_service.refresh_expiration_statuses(db)
    return {"success": True, **transitions}


@subscriptions_router.post(
    "/{subscription_id}/renew",
    response_model=MeetSubscriptionRead,
    summary="Renew a Meet subscription",
)
async def renew_meet_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subscription = workspace_events_service.get_subscription(subscription_id, db)
    if not subscription or subscription.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found.")
    try:
        renewed = workspace_events_service.renew_subscription(subscription_id, db)
    except WorkspaceEventsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "renewal_failed", "message": str(exc)},
        )
    return _read_dict_to_schema(workspace_events_service.to_read_dict(renewed))


@subscriptions_router.post(
    "/{subscription_id}/suspend",
    response_model=MeetSubscriptionRead,
    summary="Suspend a Meet subscription",
)
async def suspend_meet_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subscription = workspace_events_service.get_subscription(subscription_id, db)
    if not subscription or subscription.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found.")
    suspended = workspace_events_service.suspend_subscription(subscription_id, db)
    return _read_dict_to_schema(workspace_events_service.to_read_dict(suspended))


@pubsub_router.post(
    "/meet-events",
    response_model=PubSubPushResponse,
    summary="Pub/Sub push endpoint for Workspace Events",
    description=(
        "Notification delivery boundary for transcript-ready events. Validates, "
        "deduplicates, and durably records the notification; heavy retrieval "
        "and AI processing run outside this handler."
    ),
)
async def pubsub_meet_events(
    request: Request,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    try:
        envelope = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "malformed_envelope", "message": "Request body must be JSON."},
        )
    try:
        result = meet_event_worker.handle_pubsub_push(
            envelope=envelope, db=db, authorization_header=authorization
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_event", "message": str(exc)},
        )
    return PubSubPushResponse(**result)


@router.get(
    "/meet/events",
    response_model=List[MeetEventRecordRead],
    summary="List consumed Meet event records",
)
async def list_meet_events(
    event_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(MeetEventRecord).filter(MeetEventRecord.user_id == current_user.id)
    if event_status:
        query = query.filter(MeetEventRecord.status == event_status)
    records = query.order_by(MeetEventRecord.received_at.desc()).limit(limit).all()
    return [MeetEventRecordRead.model_validate(r) for r in records]


@router.post(
    "/meet/events/{event_record_id}/process",
    summary="Process a recorded Meet event (retrieval + persistence)",
    description=(
        "Runs Meet REST retrieval for a durably recorded transcript notification. "
        "Idempotent: already-processed events return without duplicate work."
    ),
)
async def process_meet_event(
    event_record_id: str,
    subscription_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    auto_process_pipeline: bool = Query(
        True,
        description="Run Evidence -> Intelligence -> proposals pipeline after persistence",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = db.query(MeetEventRecord).filter(MeetEventRecord.id == event_record_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event record not found.")
    if record.user_id and record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-user access denied.")
    try:
        meet_event_worker.bind_event_identity(
            event_record_id=event_record_id,
            user_id=current_user.id,
            subscription_id=subscription_id,
            project_id=project_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    try:
        result = meet_event_worker.process_event_record(event_record_id=event_record_id, db=db)
    except TranscriptUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail={"error": "transcript_pending", "message": str(exc)},
        )
    except CredentialsExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "credentials_expired", "message": str(exc)},
        )
    except GoogleMeetPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "insufficient_permissions", "message": str(exc)},
        )
    except GoogleMeetRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limit_exceeded", "message": str(exc)},
        )
    except (GoogleMeetTransientError, GoogleMeetError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "retrieval_failure", "message": str(exc)},
        )

    if auto_process_pipeline and result.get("status") == "processed":
        from app.services.pipeline_coordinator import PipelineCoordinator

        coordinator = PipelineCoordinator()
        try:
            pipeline_result = coordinator.process_meeting_with_context(
                meeting_id=result["meeting_id"],
                project_id=result["project_id"],
                db=db,
                actor_id=f"meet_event:{event_record_id}",
                workspace_id="ws_default",
                tenant_id="default_tenant",
                correlation_id=event_record_id,
            )
            result["pipeline"] = pipeline_result.model_dump()
        except Exception as exc:
            logger.warning("meet_pipeline_deferred: event=%s error=%s", event_record_id, exc)
            result["pipeline"] = {"status": "deferred", "error": str(exc)}
    return result


@router.post(
    "/meet/reconcile",
    response_model=MeetReconcileResponse,
    summary="Reconcile missed transcripts (recovery, not primary ingestion)",
    description=(
        "Recovery fallback for outages, Pub/Sub interruptions, and failed event "
        "processing. Reconciles transcript availability through the Meet REST "
        "API. Scoped to recorded-but-unprocessed events plus bounded discovery."
    ),
)
async def reconcile_meet_transcripts(
    max_conferences: int = Query(10, ge=1, le=50),
    project_id: Optional[str] = Query(None),
    meet_service: GoogleMeetService = Depends(get_google_meet_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pending = (
        db.query(MeetEventRecord)
        .filter(
            MeetEventRecord.user_id == current_user.id,
            MeetEventRecord.status.in_(["received", "processing", "pending_retry", "awaiting_transcript", "failed"]),
        )
        .order_by(MeetEventRecord.received_at.asc())
        .limit(max_conferences)
        .all()
    )
    processed = 0
    for record in pending:
        try:
            meet_event_worker.process_event_record(event_record_id=record.id, db=db)
            processed += 1
        except Exception as exc:
            logger.warning("meet_reconcile_event_failed: event=%s error=%s", record.id, exc)

    discovered = 0
    synced = 0
    transcripts = 0
    entries = 0
    if project_id:
        try:
            sync_result = await meet_service.sync_conferences(
                user_id=current_user.id,
                db=db,
                max_conferences=max_conferences,
                project_id=project_id,
            )
            discovered = sync_result.total_conferences_discovered
            synced = sync_result.total_conferences_synced
            transcripts = sync_result.total_transcripts_synced
            entries = sync_result.total_entries_synced
        except ConnectionNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "connection_not_found", "message": str(exc)},
            )
        except CredentialsExpiredError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "credentials_expired", "message": str(exc)},
            )
        except GoogleMeetPermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "insufficient_permissions", "message": str(exc)},
            )
        except GoogleMeetRateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "rate_limit_exceeded", "message": str(exc)},
            )
        except (GoogleMeetTransientError, GoogleMeetResourceNotFoundError, GoogleMeetError) as exc:
            metrics.increment("meet_sync_failed_total", labels={"reason": "reconciliation_failure"})
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": "reconciliation_failure", "message": str(exc)},
            )

    return MeetReconcileResponse(
        success=True,
        message=(
            "Reconciliation completed. Processed recorded events; "
            "bounded REST discovery ran only when a project was scoped."
        ),
        mode="reconciliation",
        total_conferences_discovered=discovered,
        total_conferences_synced=synced,
        total_transcripts_synced=transcripts,
        total_entries_synced=entries,
        total_events_processed=processed,
        meetings=[],
    )


@router.get(
    "/meet/unassigned",
    summary="List meetings awaiting project mapping",
)
async def list_unassigned_meetings(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.meeting import Meeting
    from app.schemas.meeting import MeetingRead

    meetings = (
        db.query(Meeting)
        .filter(
            Meeting.user_id == current_user.id,
            Meeting.project_id == UNASSIGNED_PROJECT_ID,
        )
        .order_by(Meeting.created_at.desc())
        .limit(limit)
        .all()
    )
    return [MeetingRead.model_validate(m) for m in meetings]


@router.post(
    "/meet/unassigned/{meeting_id}/assign",
    summary="Assign an unmapped meeting to a project",
)
async def assign_unmapped_meeting(
    meeting_id: str,
    project_id: str = Query(..., description="Target Synesis project ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.meeting import Meeting
    from app.models.project import Project
    from app.schemas.meeting import MeetingRead

    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.user_id == current_user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found.")
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    meeting.project_id = project.id
    db.commit()
    db.refresh(meeting)
    logger.info(
        "meet_project_assigned: meeting_id=%s project_id=%s actor=%s",
        meeting_id,
        project_id,
        current_user.id,
    )
    return MeetingRead.model_validate(meeting)
