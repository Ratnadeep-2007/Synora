"""Scoped memory operations and original-source inspection."""

import json
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy.orm import defer
from app.api.deps import get_current_user, get_db, get_accessible_memory_project
from app.models.user import User
from app.models.evidence import Evidence
from app.models.source_event import SourceEvent
from app.models.memory_engine import SourceArtifact, MemoryIndex
from app.models.task_job import TaskJob
from app.services.source_artifact_service import SourceArtifactService

router = APIRouter(tags=["Memory & Original Sources"])


def accessible_artifact(artifact_id, db, user):
    artifact = db.get(SourceArtifact, artifact_id)
    if not artifact:
        raise HTTPException(404, "Original source not found")
    get_accessible_memory_project(artifact.project_id, db, user)
    tenant = getattr(user, "tenant_id", "default_tenant")
    allowed = {"default_tenant", "tenant_default"} if tenant in {"default_tenant", "tenant_default"} else {tenant}
    if artifact.tenant_id not in allowed:
        raise HTTPException(403, "Source access denied")
    return artifact


@router.get("/sources/evidence/{evidence_id}/artifacts")
def evidence_artifacts(evidence_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    evidence = db.get(Evidence, evidence_id)
    if not evidence:
        raise HTTPException(404, "Evidence not found")
    get_accessible_memory_project(evidence.project_id, db, user)
    tenant = getattr(user, "tenant_id", "default_tenant")
    allowed = ["default_tenant", "tenant_default"] if tenant in {"default_tenant", "tenant_default"} else [tenant]
    event = db.get(SourceEvent, evidence.source_event_id)
    if not event or event.tenant_id not in allowed:
        raise HTTPException(403, "Source access denied")
    artifact_id = json.loads(evidence.metadata_json or "{}").get("artifact_id")
    records = db.query(SourceArtifact).options(defer(SourceArtifact.data)).filter(SourceArtifact.tenant_id.in_(allowed),
        SourceArtifact.project_id == evidence.project_id,
        (SourceArtifact.evidence_id == evidence_id) | (SourceArtifact.id == artifact_id)).all()
    return [SourceArtifactService().describe(row) for row in records]


@router.get("/sources/evidence/{evidence_id}")
def original_evidence(evidence_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    evidence = db.get(Evidence, evidence_id)
    if not evidence:
        raise HTTPException(404, "Evidence not found")
    get_accessible_memory_project(evidence.project_id, db, user)
    event = db.get(SourceEvent, evidence.source_event_id)
    tenant = getattr(user, "tenant_id", "default_tenant")
    allowed = {"default_tenant", "tenant_default"} if tenant in {"default_tenant", "tenant_default"} else {tenant}
    if not event or event.tenant_id not in allowed:
        raise HTTPException(403, "Evidence access denied")
    from app.schemas.source_event import EvidenceRead
    return EvidenceRead.model_validate(evidence)


@router.get("/sources/artifacts/{artifact_id}/original")
def original_source(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    artifact = accessible_artifact(artifact_id, db, user)
    return Response(content=artifact.data, media_type=artifact.mime_type,
                    headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.get("/sources/artifacts/{artifact_id}")
def describe_original(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return SourceArtifactService().describe(accessible_artifact(artifact_id, db, user))


@router.post("/sources/artifacts/{artifact_id}/retry")
def retry_source(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    artifact = accessible_artifact(artifact_id, db, user)
    job = SourceArtifactService().retry(artifact, db)
    return {"artifact": SourceArtifactService().describe(artifact), "job_id": job.id if job else None}


@router.delete("/sources/artifacts/{artifact_id}")
def delete_original(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    artifact = accessible_artifact(artifact_id, db, user)
    db.delete(artifact)
    db.commit()
    return {"deleted": artifact_id, "evidence_retained": True}


@router.get("/projects/{project_id}/memory/history")
def memory_history(project_id: str, limit: int = Query(100, ge=1, le=200),
                   db: Session = Depends(get_db), project=Depends(get_accessible_memory_project)):
    from app.services.memory_lifecycle import MemoryLifecycleService
    return MemoryLifecycleService().history(project_id, db, limit)


@router.get("/projects/{project_id}/memory/processing")
def memory_processing(project_id: str, db: Session = Depends(get_db), project=Depends(get_accessible_memory_project)):
    from sqlalchemy import func
    from app.services.memory_jobs import JOB_TYPES
    states = db.query(TaskJob.job_type, TaskJob.status, func.count(TaskJob.id)).filter(
        TaskJob.project_id == project_id, TaskJob.job_type.in_(JOB_TYPES),
    ).group_by(TaskJob.job_type, TaskJob.status).all()
    providers = db.query(MemoryIndex.provider, func.count(MemoryIndex.id)).filter_by(project_id=project_id).group_by(MemoryIndex.provider).all()
    return {"jobs": [{"type": kind, "status": status, "count": count} for kind, status, count in states],
            "indexes": [{"provider": provider, "count": count} for provider, count in providers]}


@router.get("/memory/provider/health")
def memory_provider_health(user: User = Depends(get_current_user)):
    """Which retrieval provider is active; Mem0 is an optional experiment
    adapter and canonical memory always stays in Synora's DB."""
    from app.services.memory_provider import provider_health

    return provider_health()


@router.get("/projects/{project_id}/memory/session-scan")
def memory_session_scan(project_id: str, open_file: str = Query(""), topic: str = Query(""),
                    db: Session = Depends(get_db), user: User = Depends(get_current_user),
                    project=Depends(get_accessible_memory_project)):
    """Pattern 1 (session-start scan): blockers, active decisions, and
    precomputed proactive hints before the first message."""
    from app.core.config import settings
    from app.services.proactive_memory import ProactiveMemoryService

    if not settings.PROACTIVE_MEMORY_ENABLED:
        return {"project_id": project_id, "enabled": False, "hints": [], "blockers": [], "active_decisions": [], "memories": []}
    return ProactiveMemoryService().session_start_scan(
        db, project_id, user_id=user.id,
        context={"open_file": open_file, "topic": topic},
        tenant_id=getattr(user, "tenant_id", "default_tenant"),
    )


@router.post("/projects/{project_id}/memory/context-scan")
def memory_context_scan(project_id: str, body: dict, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user), project=Depends(get_accessible_memory_project)):
    """Pattern 2 (context-trigger scan): the DEMAND gate decides whether this
    message is worth a memory retrieval; acknowledgments never fire one."""
    from app.core.config import settings
    from app.services.proactive_memory import ProactiveMemoryService

    if not settings.PROACTIVE_MEMORY_ENABLED:
        return {"decision": "NO_DEMAND", "query": None, "memories": [], "suppressed": False, "enabled": False}
    return ProactiveMemoryService().on_context_message(
        db, project_id, str(body.get("message") or ""),
        history=list(body.get("history") or []), user_id=user.id,
    )


@router.post("/projects/{project_id}/memory/reflect-hints")
def memory_reflect_hints(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                         project=Depends(get_accessible_memory_project)):
    """Pattern 3: precompute proactive hints from current state (LLM-free),
    so the next session start is a pure lookup."""
    from app.services.proactive_memory import ProactiveMemoryService

    return ProactiveMemoryService().refresh_hints(
        db, project_id, tenant_id=getattr(user, "tenant_id", "default_tenant")
    )


@router.post("/projects/{project_id}/memory/reindex")
def reindex_memory(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user), project=Depends(get_accessible_memory_project)):
    from app.models.intelligence import CandidateKnowledge
    from app.services.memory_jobs import enqueue_job
    from app.services.memory_events import fingerprint
    tenant = getattr(user, "tenant_id", "default_tenant")
    queued = 0
    for kind, model in (("claim", CandidateKnowledge), ("evidence", Evidence)):
        for entity in db.query(model).filter(model.project_id == project_id).yield_per(100):
            job = enqueue_job(db, "memory_index", {"kind": kind, "entity_id": entity.id}, project_id, tenant,
                              key=f"backfill:{kind}:{entity.id}:{fingerprint(entity)}", requeue=True)
            queued += int(job.status == "pending")
    db.commit()
    return {"queued": queued}
