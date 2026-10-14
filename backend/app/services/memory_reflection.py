"""A bounded second extraction pass over original meeting evidence."""

import hashlib
import json
from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.models.source_event import SourceEvent
from app.services.knowledge_intelligence import KnowledgeIntelligenceService
from app.services.memory_jobs import enqueue_job


class MemoryReflectionService:
    def __init__(self, knowledge=None):
        self.knowledge = knowledge or KnowledgeIntelligenceService()

    def schedule(self, meeting_id, project_id, tenant_id, db):
        rows = db.query(Evidence).filter_by(meeting_id=meeting_id, project_id=project_id).order_by(Evidence.id).all()
        signature = hashlib.sha256(json.dumps([(row.id, row.content) for row in rows]).encode()).hexdigest()
        if not rows:
            return None
        return enqueue_job(db, "memory_reflection", {"meeting_id": meeting_id, "signature": signature},
                           project_id, tenant_id, key=meeting_id + ":" + signature)

    def reflect(self, meeting_id, project_id, tenant_id, db):
        tenants = ["default_tenant", "tenant_default"] if tenant_id in {"default_tenant", "tenant_default"} else [tenant_id]
        sources = db.query(Evidence).join(SourceEvent, Evidence.source_event_id == SourceEvent.event_id).filter(
            Evidence.meeting_id == meeting_id, Evidence.project_id == project_id,
            SourceEvent.tenant_id.in_(tenants),
        ).order_by(Evidence.occurred_at.asc()).limit(120).all()
        candidates = db.query(CandidateKnowledge).filter_by(project_id=project_id, meeting_id=meeting_id).all()
        covered = {eid for item in candidates for eid in json.loads(item.evidence_ids_json or "[]")}
        prioritized = [row for row in sources if row.id not in covered] + [row for row in sources if row.id in covered]
        # One provider call. Later evidence gets another job when the durable
        # meeting fingerprint changes; this does not scan the whole archive.
        snapshots = [Evidence(id=row.id, project_id=project_id, source=row.source,
                              source_event_id=row.source_event_id, actor_id=row.actor_id,
                              content=row.content[:900]) for row in prioritized[:12]]
        extraction = self.knowledge.extract_items(snapshots, source_name="meeting_reflection_completeness")
        if extraction.ai_status == "ai_unavailable":
            return {"status": "provider_unavailable", "candidates_created": 0, "evidence_checked": 0}
        known = {(item.category, item.title.strip().lower(), item.content.strip().lower()) for item in candidates}
        extraction.items = [item for item in extraction.items if (
            item.category, item.title.strip().lower(), item.content.strip().lower()
        ) not in known][:8]
        created = self.knowledge.persist_candidates(extraction, project_id, db, meeting_id=meeting_id) if extraction.items else []
        # Reflection discovers candidates, never grants itself approval.
        from app.services.project_state_service import ProjectStateService
        service = ProjectStateService()
        for candidate in created:
            if candidate.status == "candidate" and candidate.category in {"decision_candidate", "requirement_candidate", "proposal"}:
                service.propose_change_from_candidate(candidate, db, actor_id="reflection_worker")
        return {"status": "review_ready", "candidates_created": len(created),
                "candidate_ids": [item.id for item in created], "evidence_checked": len(snapshots),
                "source_evidence_ids": [item.id for item in snapshots],
                "bounded": len(sources) > len(snapshots)}
