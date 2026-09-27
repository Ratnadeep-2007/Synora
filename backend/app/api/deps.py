from typing import Generator, Optional
from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.database import SessionLocal, get_db
from app.models.user import User
from app.services.encryption_service import EncryptionService
from app.services.google_oauth import GoogleOAuthService
from app.services.google_meet import GoogleMeetService


def get_encryption_service() -> EncryptionService:
    """Provides singleton/shared encryption service instance."""
    return EncryptionService(settings.ENCRYPTION_KEY)


def get_google_oauth_service(
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> GoogleOAuthService:
    """Provides configured GoogleOAuthService instance."""
    return GoogleOAuthService(settings=settings, encryption_service=encryption_service)


def get_google_meet_service(
    oauth_service: GoogleOAuthService = Depends(get_google_oauth_service),
) -> GoogleMeetService:
    """Provides configured GoogleMeetService instance."""
    return GoogleMeetService(oauth_service=oauth_service)


def get_ingestion_service() -> "IngestionService":
    from app.services.ingestion_service import IngestionService
    return IngestionService()


def get_meeting_intelligence_service() -> "MeetingIntelligenceService":
    from app.services.meeting_intelligence import MeetingIntelligenceService
    return MeetingIntelligenceService()


def get_project_state_service() -> "ProjectStateService":
    from app.services.project_state_service import ProjectStateService
    return ProjectStateService()


def get_conflict_service(
    state_service: "ProjectStateService" = Depends(get_project_state_service),
) -> "ConflictService":
    from app.services.conflict_service import ConflictService
    return ConflictService(state_service=state_service)


def get_pipeline_coordinator(
    ingestion: "IngestionService" = Depends(get_ingestion_service),
    intelligence: "MeetingIntelligenceService" = Depends(get_meeting_intelligence_service),
    state: "ProjectStateService" = Depends(get_project_state_service),
    conflict: "ConflictService" = Depends(get_conflict_service),
) -> "PipelineCoordinator":
    from app.services.pipeline_coordinator import PipelineCoordinator
    return PipelineCoordinator(
        ingestion_service=ingestion,
        intelligence_service=intelligence,
        state_service=state,
        conflict_service=conflict,
    )


def get_context_builder(
    state_service: "ProjectStateService" = Depends(get_project_state_service),
) -> "ContextBuilder":
    from app.services.context_builder import ContextBuilder
    return ContextBuilder(state_service=state_service)


def get_ai_workforce_service(
    context_builder: "ContextBuilder" = Depends(get_context_builder),
    state_service: "ProjectStateService" = Depends(get_project_state_service),
) -> "AIWorkforceService":
    from app.services.ai_workforce import AIWorkforceService
    return AIWorkforceService(
        context_builder=context_builder,
        state_service=state_service,
    )


def get_excalidraw_service(
    ingestion: "IngestionService" = Depends(get_ingestion_service),
) -> "ExcalidrawService":
    from app.services.excalidraw_service import ExcalidrawService
    return ExcalidrawService(ingestion_service=ingestion)


def get_project_agent_service(
    state_service: "ProjectStateService" = Depends(get_project_state_service),
    workforce_service: "AIWorkforceService" = Depends(get_ai_workforce_service),
    excal_service: "ExcalidrawService" = Depends(get_excalidraw_service),
) -> "ProjectAgentService":
    from app.services.project_agent_service import ProjectAgentService
    return ProjectAgentService(
        state_service=state_service,
        workforce_service=workforce_service,
        excal_service=excal_service,
    )


def get_workspace_events_service() -> "WorkspaceEventsService":
    from app.services.workspace_events_service import WorkspaceEventsService
    return WorkspaceEventsService()


def get_meet_event_worker() -> "MeetEventWorker":
    from app.services.meet_event_worker import MeetEventWorker
    return MeetEventWorker()


def get_current_user(
    db: Session = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    user_id: Optional[str] = Query(None, description="Optional user ID"),
) -> User:
    """
    Dependency that resolves the current authenticated Synesis user.
    Supports X-User-ID header or query parameter. Rejects unauthenticated requests.
    """
    target_id = x_user_id or user_id
    if not target_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide X-User-ID header or user_id query parameter.",
        )

    user = db.query(User).filter(User.id == target_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unknown user '{target_id}'.",
        )

    return user
