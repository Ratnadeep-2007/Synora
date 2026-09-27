import logging
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db
from app.connectors.registry import registry
from app.connectors.base import ConnectorStatus
from app.core.config import settings
from app.core.rbac import Permission, Role, enforce_permission
from app.services.audit_service import AuditService
from app.services.metrics import metrics
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["System & Observability"])
audit_service = AuditService()
task_service = TaskService()


@router.get("/health", summary="Comprehensive Health Check")
def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Performs multi-component health checks:
    - Application status
    - Database responsiveness
    - External connector statuses (Google Meet, Slack, etc.)
    
    Overall status logic:
    - healthy: Database and all connectors are healthy
    - degraded: Database is healthy, but one or more connectors are degraded/unavailable
    - unavailable: Database is down or application is failing
    """
    start_time = time.time()
    components: Dict[str, Any] = {}
    is_database_healthy = False

    # 1. Database Health Check
    db_latency_ms = 0.0
    try:
        t0 = time.time()
        db.execute(text("SELECT 1"))
        db_latency_ms = round((time.time() - t0) * 1000.0, 2)
        is_database_healthy = True
        components["database"] = {
            "status": "healthy",
            "latency_ms": db_latency_ms,
            "engine": "sqlite" if "sqlite" in settings.DATABASE_URL else "postgresql",
        }
    except Exception as exc:
        logger.error(f"Database health check failed: {exc}")
        components["database"] = {
            "status": "unavailable",
            "error": str(exc),
        }

    # 2. Connector Health Checks
    connector_healths = registry.check_all_health()
    components["connectors"] = {}
    all_connectors_healthy = True
    any_connector_unavailable = False

    for name, health in connector_healths.items():
        components["connectors"][name] = {
            "status": health.status.value,
            "latency_ms": round(health.latency_ms, 2) if health.latency_ms is not None else None,
            "error": health.error_message,
        }
        if health.status != ConnectorStatus.HEALTHY:
            all_connectors_healthy = False
        if health.status in (ConnectorStatus.ERROR, ConnectorStatus.DISCONNECTED):
            any_connector_unavailable = True

    # 3. Determine Overall System Health
    if not is_database_healthy:
        overall_status = "unavailable"
    elif not all_connectors_healthy:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    total_latency_ms = round((time.time() - start_time) * 1000.0, 2)

    return {
        "status": overall_status,
        "environment": settings.ENVIRONMENT,
        "version": settings.VERSION,
        "total_latency_ms": total_latency_ms,
        "components": components,
    }


@router.get("/health/ready", summary="Readiness Probe")
def readiness_check(db: Session = Depends(get_db)) -> Dict[str, str]:
    """
    Kubernetes / Docker container readiness probe.
    Returns 200 OK only if the database is responsive.
    """
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service not ready: database unresponsive ({exc})",
        )


@router.get("/metrics", summary="Operational Metrics Snapshot")
def get_metrics() -> Dict[str, Any]:
    """
    Returns real-time operational metrics for ingestion, intelligence, connectors,
    and agent workforce tasks.
    """
    return metrics.get_snapshot()


@router.get("/audit", summary="Query Immutable Audit Trail")
def get_audit_logs(
    tenant_id: str = Query("default_tenant", description="Tenant scope"),
    action: Optional[str] = Query(None, description="Filter by action name"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    role: str = Query("admin", description="Requester role (admin/owner required)"),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Returns the immutable audit log for a tenant. Requires ADMIN or OWNER role.
    """
    enforce_permission(role, Permission.READ_AUDIT)
    logs = audit_service.query_logs(
        db=db,
        tenant_id=tenant_id,
        action=action,
        resource_type=resource_type,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": log.id,
            "tenant_id": log.tenant_id,
            "actor_id": log.actor_id,
            "actor_role": log.actor_role,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "status": log.status,
            "ip_address": log.ip_address,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
        }
        for log in logs
    ]


@router.get("/tasks/dlq", summary="List Dead-Letter Queue Jobs")
def list_dlq_jobs(
    tenant_id: str = Query("default_tenant"),
    role: str = Query("admin"),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Fetch all background jobs currently quarantined in the Dead-Letter Queue.
    """
    enforce_permission(role, Permission.MANAGE_CONNECTORS)
    jobs = task_service.get_dead_letter_jobs(db=db, tenant_id=tenant_id)
    return [
        {
            "id": j.id,
            "job_type": j.job_type,
            "tenant_id": j.tenant_id,
            "project_id": j.project_id,
            "status": j.status,
            "error_message": j.error_message,
            "retry_count": j.retry_count,
            "max_retries": j.max_retries,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
        }
        for j in jobs
    ]


@router.post("/tasks/dlq/{job_id}/replay", summary="Replay Dead-Letter Queue Job")
def replay_dlq_job(
    job_id: str,
    role: str = Query("admin"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Operator endpoint to reset a dead-letter job to PENDING for re-processing.
    """
    enforce_permission(role, Permission.MANAGE_CONNECTORS)
    job = task_service.replay_dead_letter_job(job_id=job_id, db=db)
    return {
        "success": True,
        "message": f"Job '{job.id}' has been reset to PENDING.",
        "job_id": job.id,
        "status": job.status,
    }
