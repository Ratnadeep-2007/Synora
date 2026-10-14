from typing import Generator, Optional
import hashlib
from fastapi import Depends, Header, HTTPException, Query, Request, status
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


def get_context_intelligence_service() -> "ContextIntelligenceService":
    from app.services.context_intelligence import ContextIntelligenceService
    return ContextIntelligenceService()


def get_unknown_context_service() -> "UnknownContextService":
    from app.services.unknown_context_service import UnknownContextService
    return UnknownContextService()


def get_workspace_events_service() -> "WorkspaceEventsService":
    from app.services.workspace_events_service import WorkspaceEventsService
    return WorkspaceEventsService()


def get_meet_event_worker() -> "MeetEventWorker":
    from app.services.meet_event_worker import MeetEventWorker
    return MeetEventWorker()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    user_id: Optional[str] = Query(None, description="Optional user ID"),
) -> User:
    """
    Dependency that resolves the current authenticated Synesis user.
    Supports X-User-ID header or query parameter. Rejects unauthenticated requests.
    Automatically provisions new session users to ensure seamless onboarding.
    """
    if settings.AUTH_REQUIRED:
        claims = getattr(request.state, "auth_claims", None)
        if not claims:
            raise HTTPException(status_code=401, detail="Sign in required.")
        subject = claims["sub"]
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
        target_id = getattr(request.state, "synora_user_id", None) or f"usr_neon_{digest}"
        user = db.query(User).filter(User.id == target_id).first()
        if user:
            return user
        claimed_email = str(claims.get("email") or "").strip().lower()
        email = claimed_email or f"neon-{digest}@synora.internal"
        if db.query(User).filter(User.email == email).first():
            email = f"neon-{digest}@synora.internal"
        user = User(id=target_id, email=email, name=str(claims.get("name") or claimed_email or "Synora user")[:255])
        db.add(user)
        try:
            db.commit()
        except Exception:
            db.rollback()
            user = db.query(User).filter(User.id == target_id).first()
            if not user:
                raise
        return user

    target_id = (x_user_id or user_id or "").strip()
    if not target_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide X-User-ID header or user_id query parameter.",
        )

    user = db.query(User).filter((User.id == target_id) | (User.email == target_id)).first()
    if not user:
        clean_name = target_id.replace("usr_", "").strip()
        display_name = f"User {clean_name[:8]}" if clean_name else "User"
        user_email = target_id if "@" in target_id else f"{target_id}@synesis.internal"

        # Check if email is already taken by a different user
        existing_with_email = db.query(User).filter(User.email == user_email).first()
        if existing_with_email:
            return existing_with_email

        user = User(
            id=target_id,
            email=user_email,
            name=display_name,
        )
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
            user = db.query(User).filter((User.id == target_id) | (User.email == user_email)).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Unknown user '{target_id}'.",
                )

    return user


def get_accessible_memory_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check workspace access before reading memory or creating a snapshot."""
    from app.models.project import Project
    from app.models.workspace_membership import WorkspaceMembership

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if settings.AUTH_REQUIRED:
        membership = db.query(WorkspaceMembership).filter(
            WorkspaceMembership.workspace_id == project.workspace_id,
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.status == "active",
        ).first()
        if not membership:
            raise HTTPException(status_code=403, detail="Project workspace access required.")
    return project
