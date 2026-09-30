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


# ------------------------------------------------------------------
# Cluster Management & Project Draft Endpoints
# ------------------------------------------------------------------
from pydantic import BaseModel
from typing import Any, Dict


class ClusterAssignRequest(BaseModel):
    project_id: str


class ProjectDraftRequest(BaseModel):
    item_id: Optional[str] = None
    cluster_id: Optional[str] = None


class CreateProjectFromDraftRequest(BaseModel):
    draft: Dict[str, Any]
    workspace_id: Optional[str] = "ws_default"
    cluster_id: Optional[str] = None
    item_id: Optional[str] = None


@router.get(
    "/clusters",
    summary="List or trigger embedding-based clusters of pending Unknown Context items",
)
async def list_or_create_clusters(
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.unknown_cluster_service import UnknownClusterService
    from app.models.unknown_cluster import UnknownCluster

    cluster_svc = UnknownClusterService()
    tenant = _tenant(current_user)
    if refresh:
        clusters = cluster_svc.cluster_pending_items(db, tenant_id=tenant)
    else:
        clusters = (
            db.query(UnknownCluster)
            .filter(UnknownCluster.tenant_id == tenant, UnknownCluster.status == "pending")
            .all()
        )
        if not clusters:
            clusters = cluster_svc.cluster_pending_items(db, tenant_id=tenant)

    return [
        {
            "id": c.id,
            "title": c.title,
            "summary": c.summary,
            "item_count": c.item_count,
            "item_ids": c.get_item_ids(),
            "suggested_project_id": c.suggested_project_id,
            "suggested_project_name": c.suggested_project_name,
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in clusters
    ]


@router.post(
    "/clusters/{cluster_id}/assign",
    summary="Atomically assign all items in a cluster to a project",
)
async def assign_cluster(
    cluster_id: str,
    body: ClusterAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.unknown_cluster_service import UnknownClusterError, UnknownClusterService

    tenant = _tenant(current_user)
    try:
        cluster = UnknownClusterService().assign_cluster(
            cluster_id=cluster_id,
            project_id=body.project_id,
            db=db,
            actor_id=current_user.id,
            tenant_id=tenant,
        )
    except UnknownClusterError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {
        "success": True,
        "message": f"Cluster '{cluster.id}' assigned to project '{body.project_id}'.",
        "cluster_id": cluster.id,
        "assigned_project_id": cluster.assigned_project_id,
    }


@router.post(
    "/draft-project",
    summary="Synthesize an intelligent project draft from an unknown item or cluster",
)
async def draft_project(
    body: ProjectDraftRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.unknown_cluster_service import UnknownClusterService

    draft = UnknownClusterService().generate_project_draft(
        item_id=body.item_id,
        cluster_id=body.cluster_id,
        db=db,
    )
    return draft


@router.post(
    "/create-project-from-draft",
    summary="Create a full enterprise project from a draft with visual workspace and agent",
)
async def create_project_from_draft(
    body: CreateProjectFromDraftRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.unknown_cluster_service import UnknownClusterService

    tenant = _tenant(current_user)
    project = UnknownClusterService().create_project_from_draft(
        draft=body.draft,
        db=db,
        actor_id=current_user.id,
        tenant_id=tenant,
        workspace_id=body.workspace_id or "ws_default",
        cluster_id=body.cluster_id,
        item_id=body.item_id,
    )
    return {
        "success": True,
        "message": f"Project '{project.name}' successfully created.",
        "project_id": project.id,
        "name": project.name,
    }

