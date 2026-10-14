"""Claim promotion, replacement review, and explicit supersession."""

import json
from datetime import datetime, timezone
from app.models.conflict import Conflict
from app.models.intelligence import CandidateKnowledge
from app.models.project_state import StateChange
from app.models.memory_engine import MemoryClaimRevision

TARGETS = {"requirement": "requirements", "requirement_candidate": "requirements",
           "decision": "decisions", "decision_candidate": "decisions",
           "architectural_change": "architecture", "constraint": "constraints"}


def normalized(value):
    return " ".join(str(value or "").lower().split()).rstrip(".")


def claim_text(item):
    return item.get("content") or item.get("details") or item.get("text") or item.get("detail") or "" if isinstance(item, dict) else str(item)


class MemoryLifecycleService:
    def replacement_conflict(self, candidate, state, db, tenant_id="default_tenant", source="generic"):
        section = TARGETS.get(candidate.category)
        if not section:
            return None
        rows = json.loads(getattr(state, section + "_json") or "[]")
        match = next((row for row in rows if isinstance(row, dict) and normalized(
            row.get("title") or row.get("component")
        ) == normalized(candidate.title) and normalized(claim_text(row)) != normalized(candidate.content)), None)
        if match is None:
            return None
        existing = db.query(Conflict).filter(Conflict.candidate_id == candidate.id,
            Conflict.tenant_id == tenant_id, Conflict.status.in_(["open", "under_review", "unresolved"])).first()
        if existing:
            return existing
        change = db.query(StateChange).filter_by(candidate_id=candidate.id, approval_status="proposed").first()
        if not change:
            change = StateChange(project_id=candidate.project_id, candidate_id=candidate.id,
                state_version_before=state.current_version, operation="update", target_section=section,
                value_json=json.dumps({"title": candidate.title, "content": candidate.content, "target_id": match.get("id")}),
                reason="Replacement of active project knowledge requires review.", actor_id="memory_policy",
                evidence_ids_json=candidate.evidence_ids_json, approval_status="proposed")
            db.add(change)
            db.flush()
        key = {"decisions": "decision", "requirements": "requirement", "architecture": "architecture", "constraints": "constraint"}[section]
        conflict = Conflict(tenant_id=tenant_id, project_id=candidate.project_id, candidate_id=candidate.id,
            state_change_id=change.id, type="decision" if section == "decisions" else "requirement" if section == "requirements" else "architecture" if section == "architecture" else "scope",
            severity="high", title=f"Review replacement: {candidate.title}",
            description="New evidence changes an active claim. Current memory is retained until review.",
            current_state_reference=json.dumps({key: match, "section": section}),
            proposed_change_reference=json.dumps({"title": candidate.title, "content": candidate.content}),
            evidence_ids_json=candidate.evidence_ids_json, status="open", source=source)
        candidate.status = "conflict"
        db.add(conflict)
        return conflict

    def propose(self, candidate, state, db):
        existing = db.query(StateChange).filter_by(candidate_id=candidate.id, approval_status="proposed").first()
        if not existing:
            db.add(StateChange(project_id=candidate.project_id, candidate_id=candidate.id,
                state_version_before=state.current_version, operation="insert", target_section=TARGETS.get(candidate.category, "requirements"),
                value_json=json.dumps({"title": candidate.title, "content": candidate.content, "source_candidate_id": candidate.id}),
                evidence_ids_json=candidate.evidence_ids_json, actor_id="memory_policy", reason="Unconfirmed proposal requires review.",
                approval_status="proposed"))
        candidate.status = "proposed"

    def supersede_prior(self, candidate, db):
        previous = db.query(CandidateKnowledge).filter(CandidateKnowledge.project_id == candidate.project_id,
            CandidateKnowledge.id != candidate.id, CandidateKnowledge.status == "approved").all()
        timestamp = datetime.now(timezone.utc)
        for old in previous:
            if old.category == candidate.category and normalized(old.title) == normalized(candidate.title) and normalized(old.content) != normalized(candidate.content):
                old.status = "superseded"
                for revision in db.query(MemoryClaimRevision).filter_by(candidate_id=old.id, valid_to=None).all():
                    revision.valid_to = timestamp
                    revision.superseded_by = candidate.id

    def history(self, project_id, db, limit=100):
        return [{"id": row.id, "candidate_id": row.candidate_id, "status": row.status,
                 "support_type": row.support_type, "valid_from": row.valid_from.isoformat(),
                 "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                 "superseded_by": row.superseded_by, "claim": json.loads(row.snapshot_json)}
                for row in db.query(MemoryClaimRevision).filter_by(project_id=project_id).order_by(
                    MemoryClaimRevision.valid_from.desc()).limit(limit).all()]
