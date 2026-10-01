from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.services.workspace_atlas_service import WorkspaceAtlasService

router = APIRouter(prefix="/workspace", tags=["Workspace Project Atlas"])

service = WorkspaceAtlasService()


def _tenant(current_user: User) -> str:
    return getattr(current_user, "tenant_id", "default_tenant")


@router.get(
    "/atlas",
    summary="Get the single workspace Project Atlas",
    description=(
        "Returns the DB-backed infinite Excalidraw workspace containing a stable "
        "column for Context Inbox and every active project."
    ),
)
async def get_project_atlas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.get_or_sync(
        db=db,
        tenant_id=_tenant(current_user),
        workspace_id="ws_default",
    )


@router.post(
    "/atlas/sync",
    summary="Synchronize the Project Atlas",
)
async def sync_project_atlas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    force: bool = True,
):
    return service.get_or_sync(
        db=db,
        tenant_id=_tenant(current_user),
        workspace_id="ws_default",
        force=force,
    )
