"""Record indexing work and claim revisions in the same source transaction."""

import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.models.source_event import SourceEvent
from app.models.task_job import TaskJob
from app.models.memory_engine import MemoryClaimRevision, SourceArtifact


def fingerprint(entity):
    values = [entity.project_id, getattr(entity, "status", "source"), getattr(entity, "classification", ""),
              getattr(entity, "title", ""), getattr(entity, "content", ""), getattr(entity, "evidence_ids_json", "")]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


@event.listens_for(Session, "before_flush")
def collect_changes(session, *_):
    changes = session.info.setdefault("memory_changes", [])
    for item in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(item, (CandidateKnowledge, Evidence)) and (
            item in session.new or item in session.deleted or session.is_modified(item, include_collections=False)
        ):
            changes.append((item, item in session.deleted))


@event.listens_for(Session, "after_flush_postexec")
def persist_changes(session, *_):
    connection = session.connection()
    timestamp = datetime.now(timezone.utc)
    for entity, deleted in session.info.pop("memory_changes", []):
        kind = "claim" if isinstance(entity, CandidateKnowledge) else "evidence"
        revision = fingerprint(entity) if not deleted else "deleted"
        if kind == "evidence" and not deleted:
            connection.execute(SourceArtifact.__table__.update().where(SourceArtifact.evidence_id == entity.id).values(project_id=entity.project_id))
        job_id = "mem_" + hashlib.sha256(f"{kind}:{entity.id}:{revision}".encode()).hexdigest()[:40]
        if not connection.execute(select(TaskJob.id).where(TaskJob.id == job_id)).first():
            # The write uses the existing transaction: a rollback also removes
            # the outbox job. SQLite and Postgres both support ON CONFLICT.
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            insert = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
            connection.execute(insert(TaskJob.__table__).values(
                id=job_id, tenant_id="default_tenant", project_id=entity.project_id,
                job_type="memory_index", status="pending", retry_count=0, max_retries=3,
                payload_json=json.dumps({"kind": kind, "entity_id": entity.id, "revision": revision}),
                created_at=timestamp, updated_at=timestamp,
            ).on_conflict_do_nothing(index_elements=["id"]))
        if kind == "claim" and not deleted:
            revision_id = "mrev_" + hashlib.sha256(f"{entity.id}:{revision}".encode()).hexdigest()[:40]
            if not connection.execute(select(MemoryClaimRevision.id).where(MemoryClaimRevision.id == revision_id)).first():
                connection.execute(MemoryClaimRevision.__table__.update().where(
                    MemoryClaimRevision.candidate_id == entity.id, MemoryClaimRevision.valid_to.is_(None),
                ).values(valid_to=timestamp))
                snapshot = {key: getattr(entity, key) for key in (
                    "id", "project_id", "category", "classification", "title", "content", "status", "evidence_ids_json"
                )}
                connection.execute(MemoryClaimRevision.__table__.insert().values(
                    id=revision_id, candidate_id=entity.id, project_id=entity.project_id, status=entity.status,
                    support_type="inferred" if entity.classification in {"Assumption", "Idea"} else "explicit",
                    snapshot_json=json.dumps(snapshot), valid_from=timestamp,
                ))


@event.listens_for(Session, "after_soft_rollback")
def discard_changes(session, *_):
    session.info.pop("memory_changes", None)
