import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.context import (
    UnknownContextActionResponse,
    UnknownContextAssignRequest,
    UnknownContextCreateProjectRequest,
    UnknownContextItemRead,
)
from app.services.unknown_context_service import (
    UnknownContextError,
    UnknownContextService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/unknown-context", tags=["Unknown Context Triage"])

service = UnknownContextService()


def _tenant(current_user: User) -> str:
    return getattr(current_user, "tenant_id", "default_tenant")


@router.get(
    "/items",
    response_model=List[UnknownContextItemRead],
    summary="List Unknown Context items awaiting triage",
)
async def list_unknown_items(
    item_status: Optional[str] = Query(None, alias="status"),
    source: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = service.list_items(
        db=db,
        tenant_id=_tenant(current_user),
        status=item_status,
        source=source,
        limit=limit,
        offset=offset,
    )
    return [service.format_item_read(i, db) for i in items]


@router.get(
    "/summary",
    summary="Unknown Context triage counts",
)
async def unknown_context_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = _tenant(current_user)
    return {
        "pending": service.pending_count(db, tenant_id=tenant),
    }


@router.get(
    "/items/{item_id}",
    response_model=UnknownContextItemRead,
    summary="Get one Unknown Context item",
)
async def get_unknown_item(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        item = service.get_item(item_id, db, tenant_id=_tenant(current_user))
    except UnknownContextError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return service.format_item_read(item, db)


@router.get(
    "/items/{item_id}/suggestions",
    response_model=UnknownContextItemRead,
    summary="Explainable possible project matches for an item",
)
async def get_unknown_suggestions(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = _tenant(current_user)
    try:
        service.suggest_matches(item_id, db, tenant_id=tenant, persist=True)
        item = service.get_item(item_id, db, tenant_id=tenant)
    except UnknownContextError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return service.format_item_read(item, db)


@router.get(
    "/board",
    summary="Unknown Context living board (agent-maintained Excalidraw page)",
)
async def unknown_context_board(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One Excalidraw page with notes of unassigned context + suggested project."""
    from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    from app.services.excalidraw_service import ExcalidrawService
    from app.services.unknown_context_visual import pending_board_items

    tenant = _tenant(current_user)
    artifact = ExcalidrawService().get_or_create_artifact(
        SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, db, tenant_id=tenant, name="Unknown Context Board"
    )
    cards = pending_board_items(db, tenant_id=tenant)
    return {
        **ExcalidrawService().format_artifact_read(artifact).model_dump(),
        "pending_notes": cards,
    }


@router.post(
    "/items/{item_id}/assign",
    response_model=UnknownContextActionResponse,
    summary="Assign an item to an existing project",
)
async def assign_unknown_item(
    item_id: str,
    body: UnknownContextAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = _tenant(current_user)
    try:
        item = service.assign_to_project(
            item_id=item_id,
            project_id=body.project_id,
            db=db,
            actor_id=current_user.id,
            tenant_id=tenant,
            note=body.note,
        )
    except UnknownContextError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return UnknownContextActionResponse(
        success=True,
        message=f"Assigned to project '{item.assigned_project_id}'.",
        item=service.format_item_read(item, db),
    )


@router.post(
    "/items/{item_id}/keep",
    response_model=UnknownContextActionResponse,
    summary="Keep an item in Unknown Context",
)
async def keep_unknown_item(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = _tenant(current_user)
    try:
        item = service.keep_unknown(item_id, db, tenant_id=tenant)
    except UnknownContextError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return UnknownContextActionResponse(
        success=True,
        message="Item kept in Unknown Context.",
        item=service.format_item_read(item, db),
    )


@router.post(
    "/items/{item_id}/create-project",
    response_model=UnknownContextActionResponse,
    summary="Create a new project from an item",
)
async def create_project_from_item(
    item_id: str,
    body: UnknownContextCreateProjectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = _tenant(current_user)
    try:
        project = service.create_project_from_item(
            item_id=item_id,
            name=body.name,
            db=db,
            actor_id=current_user.id,
            tenant_id=tenant,
            description=body.description,
            workspace_id=body.workspace_id or "ws_default",
        )
        item = service.get_item(item_id, db, tenant_id=tenant)
    except UnknownContextError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return UnknownContextActionResponse(
        success=True,
        message=f"Created project '{project.name}' from item.",
        item=service.format_item_read(item, db),
        created_project_id=project.id,
    )


@router.post(
    "/items/{item_id}/dismiss",
    response_model=UnknownContextActionResponse,
    summary="Dismiss an item",
)
async def dismiss_unknown_item(
    item_id: str,
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = _tenant(current_user)
    try:
        item = service.dismiss(
            item_id, db, actor_id=current_user.id, tenant_id=tenant, reason=reason
        )
    except UnknownContextError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return UnknownContextActionResponse(
        success=True,
        message="Item dismissed.",
        item=service.format_item_read(item, db),
    )
