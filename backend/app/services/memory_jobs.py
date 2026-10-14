"""Durable leased jobs shared by local and Render memory workers."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from app.models.task_job import TaskJob

JOB_TYPES = ("memory_index", "memory_vector", "memory_reflection", "media_transform")


def enqueue_job(db, job_type, payload, project_id, tenant_id="default_tenant", key=None, requeue=False):
    if job_type not in JOB_TYPES:
        raise ValueError("Unsupported memory job type")
    identity = key or json.dumps(payload, sort_keys=True)
    job_id = "mem_" + hashlib.sha256(f"{tenant_id}:{project_id}:{job_type}:{identity}".encode()).hexdigest()[:40]
    existing = db.get(TaskJob, job_id)
    if existing:
        if requeue and existing.status in {"completed", "dead_letter", "failed"}:
            existing.status = "pending"
            existing.retry_count = 0
            existing.completed_at = None
            existing.payload_json = json.dumps(payload)
            existing.error_message = None
        return existing
    timestamp = datetime.now(timezone.utc)
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(TaskJob.__table__).values(
        id=job_id, tenant_id=tenant_id, project_id=project_id, job_type=job_type,
        payload_json=json.dumps(payload), status="pending", retry_count=0, max_retries=3,
        created_at=timestamp, updated_at=timestamp,
    ).on_conflict_do_nothing(index_elements=["id"]))
    return db.get(TaskJob, job_id)


class MemoryJobWorker:
    def __init__(self, index_service=None, reflection_service=None, artifact_service=None):
        self.index_service = index_service
        self.reflection_service = reflection_service
        self.artifact_service = artifact_service

    def recover(self, db):
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        count = db.query(TaskJob).filter(TaskJob.job_type.in_(JOB_TYPES), TaskJob.status == "running",
                                        TaskJob.updated_at < cutoff).update({TaskJob.status: "pending"}, synchronize_session=False)
        db.commit()
        return count

    def process_batch(self, db, limit=2):
        self.recover(db)
        completed = failed = 0
        candidates = db.query(TaskJob).filter(TaskJob.job_type.in_(JOB_TYPES), TaskJob.status == "pending").order_by(
            TaskJob.created_at.asc()
        ).limit(64).all()
        for job in candidates:
            if completed + failed >= limit:
                break
            payload = json.loads(job.payload_json or "{}")
            timestamp = datetime.now(timezone.utc)
            available = payload.get("next_attempt_at")
            if available and datetime.fromisoformat(available) > timestamp:
                continue
            lease = json.dumps({"lease": uuid.uuid4().hex})
            job_id, job_type, project_id, tenant_id = job.id, job.job_type, job.project_id, job.tenant_id
            claimed = db.execute(update(TaskJob).where(TaskJob.id == job_id, TaskJob.status == "pending").values(
                status="running", result_json=lease, updated_at=timestamp,
            ), execution_options={"synchronize_session": False})
            db.commit()
            if claimed.rowcount != 1:
                continue
            try:
                from app.services.memory_index_service import MemoryIndexService
                indexes = self.index_service or MemoryIndexService()
                if job_type == "memory_index":
                    result = indexes.index(payload["kind"], payload["entity_id"], db)
                elif job_type == "memory_vector":
                    result = indexes.embed_record(payload, db)
                elif job_type == "memory_reflection":
                    from app.services.memory_reflection import MemoryReflectionService
                    result = (self.reflection_service or MemoryReflectionService()).reflect(
                        payload["meeting_id"], project_id, tenant_id, db,
                    )
                else:
                    from app.services.source_artifact_service import SourceArtifactService
                    result = (self.artifact_service or SourceArtifactService()).reprocess(payload["artifact_id"], db)
                db.execute(update(TaskJob).where(TaskJob.id == job_id, TaskJob.status == "running", TaskJob.result_json == lease).values(
                    status="completed", result_json=json.dumps(result), error_message=None,
                    completed_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
                ), execution_options={"synchronize_session": False})
                db.commit()
                completed += 1
            except Exception as exc:
                db.rollback()
                db.expire_all()
                current = db.get(TaskJob, job_id)
                if current and current.status == "running" and current.result_json == lease:
                    current.retry_count += 1
                    current.status = "dead_letter" if current.retry_count >= current.max_retries else "pending"
                    current.error_message = str(exc)[:400]
                    payload["next_attempt_at"] = (timestamp + timedelta(seconds=min(600, 30 * 2 ** current.retry_count))).isoformat()
                    current.payload_json = json.dumps(payload)
                    db.commit()
                failed += 1
        db.expire_all()
        return {"completed": completed, "failed": failed}
