from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.intelligence import CandidateKnowledge
from app.models.project_state import ProjectState, ProjectStateVersion, StateChange, ApprovalStatus, ChangeOperation
from app.services.project_state_service import ProjectStateService

logger = logging.getLogger(__name__)


class ProjectMemoryService:
    """Shared, project-bounded memory orchestrator.

    Sources (WhatsApp, completed meeting transcripts, and future connectors)
    feed evidence into one logical memory engine. The engine never crosses
    project boundaries and keeps ProjectState as the canonical snapshot while
    CandidateKnowledge remains the detailed knowledge/event layer.

    Normal, evidence-backed note updates are applied automatically. State
    changes are versioned and auditable; unresolved *project routing* stays in
    Unknown Context rather than being guessed here.
    """

    STATE_TARGETS = {
        "requirement_candidate": "requirements",
        "decision_candidate": "decisions",
        "architectural_change": "architecture",
        "question": "open_questions",
        "assumption": "assumptions",
    }

    def __init__(self, state_service: Optional[ProjectStateService] = None):
        self.state_service = state_service or ProjectStateService()

    def build_context(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        query: Optional[str] = None,
        limit_knowledge: int = 20,
        limit_evidence: int = 12,
    ) -> Dict[str, Any]:
        """Return bounded memory for one project only."""
        state = self.state_service.get_or_create_state(project_id, db)
        state_dict = self.state_service._dump_state_dict(state)

        knowledge_query = (
            db.query(CandidateKnowledge)
            .filter(CandidateKnowledge.project_id == project_id)
            .order_by(CandidateKnowledge.created_at.desc())
        )
        if query:
            like = f"%{query}%"
            knowledge_query = knowledge_query.filter(
                CandidateKnowledge.title.ilike(like)
                | CandidateKnowledge.content.ilike(like)
            )

        knowledge = knowledge_query.limit(limit_knowledge).all()

        from app.models.evidence import Evidence

        evidence_query = (
            db.query(Evidence)
            .filter(Evidence.project_id == project_id)
            .order_by(Evidence.created_at.desc())
        )
        if query:
            evidence_query = evidence_query.filter(Evidence.content.ilike(f"%{query}%"))
        evidence = evidence_query.limit(limit_evidence).all()

        return {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "state_version": state.current_version,
            "project_state": state_dict,
            "knowledge": [
                {
                    "id": item.id,
                    "category": item.category,
                    "classification": item.classification,
                    "title": item.title,
                    "content": item.content,
                    "confidence": item.confidence,
                    "status": item.status,
                    "meeting_id": item.meeting_id,
                    "evidence_ids": self._json_list(item.evidence_ids_json),
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in knowledge
            ],
            "evidence": [
                {
                    "id": item.id,
                    "source": item.source,
                    "meeting_id": item.meeting_id,
                    "transcript_id": item.transcript_id,
                    "transcript_entry_id": item.transcript_entry_id,
                    "speaker": item.actor_id or "Unknown",
                    "text": item.content,
                    "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
                }
                for item in evidence
            ],
        }

    def summarize(self, project_id: str, db: Session, tenant_id: str = "default_tenant") -> Dict[str, Any]:
        """Return compact counts for UI and observability, scoped to one project."""
        context = self.build_context(
            project_id=project_id,
            db=db,
            tenant_id=tenant_id,
            limit_knowledge=1,
            limit_evidence=1,
        )
        state = context["project_state"]
        return {
            "project_id": project_id,
            "state_version": context["state_version"],
            "knowledge": db.query(CandidateKnowledge).filter(
                CandidateKnowledge.project_id == project_id
            ).count(),
            "requirements": len(state.get("requirements", [])),
            "decisions": len(state.get("decisions", [])),
            "architecture": len(state.get("architecture", [])),
            "constraints": len(state.get("constraints", [])),
            "assumptions": len(state.get("assumptions", [])),
            "open_questions": len(state.get("open_questions", [])),
            "updated_at": context["project_state"].get("updated_at"),
        }

    def apply_candidates(
        self,
        project_id: str,
        candidates: Sequence[CandidateKnowledge],
        db: Session,
        *,
        source: str = "unknown",
        actor_id: str = "synora_agent",
    ) -> Dict[str, Any]:
        """Automatically promote evidence-backed knowledge into project memory.

        Supported canonical sections are updated in one transaction. The
        detailed CandidateKnowledge records remain available as the memory
        ledger, so source provenance and the original extracted item are never
        lost. Unsupported categories stay in the ledger without being forced
        into a task tracker or unrelated state section.
        """
        if not candidates:
            state = self.state_service.get_or_create_state(project_id, db)
            return {
                "project_id": project_id,
                "state_version_before": state.current_version,
                "state_version_after": state.current_version,
                "applied": 0,
                "skipped": 0,
                "candidate_ids": [],
            }

        state = (
            db.query(ProjectState)
            .filter(ProjectState.project_id == project_id)
            .with_for_update()
            .first()
        )
        if not state:
            state = self.state_service.get_or_create_state(project_id, db)

        before = state.current_version
        arrays = {
            "requirements": self._json_list(state.requirements_json),
            "architecture": self._json_list(state.architecture_json),
            "decisions": self._json_list(state.decisions_json),
            "constraints": self._json_list(state.constraints_json),
            "assumptions": self._json_list(state.assumptions_json),
            "open_questions": self._json_list(state.open_questions_json),
        }

        applied_ids: List[str] = []
        skipped_ids: List[str] = []

        for candidate in candidates:
            # Candidate must belong to this exact project. Never let callers
            # use the memory orchestrator to cross a project boundary.
            if candidate.project_id != project_id:
                skipped_ids.append(candidate.id)
                continue

            target = self.STATE_TARGETS.get(candidate.category)
            if not target:
                # action_item / proposal / conflict_signal / informational
                # remain available in the detailed knowledge ledger; they are
                # intentionally not coerced into task-tracker fields.
                candidate.status = "approved"
                skipped_ids.append(candidate.id)
                continue

            values = arrays[target]
            evidence_ids = self._json_list(candidate.evidence_ids_json)
            fingerprint = self._candidate_fingerprint(candidate)

            if any(
                self._item_fingerprint(item) == fingerprint
                or (
                    isinstance(item, dict)
                    and candidate.title
                    and str(item.get("title") or item.get("text") or "").strip().lower()
                    == candidate.title.strip().lower()
                    and evidence_ids
                    and set(evidence_ids).intersection(
                        set(item.get("evidence_ids") or [])
                    )
                )
                for item in values
            ):
                candidate.status = "approved"
                skipped_ids.append(candidate.id)
                continue

            created = candidate.created_at or datetime.now(timezone.utc)
            base = {
                "source": source,
                "source_candidate_id": candidate.id,
                "evidence_ids": evidence_ids,
                "created_at": created.isoformat(),
            }

            if target == "requirements":
                values.append(
                    {
                        **base,
                        "id": f"req_mem_{uuid.uuid4().hex[:10]}",
                        "title": candidate.title,
                        "content": candidate.content,
                    }
                )
            elif target == "decisions":
                values.append(
                    {
                        **base,
                        "id": f"dec_mem_{uuid.uuid4().hex[:10]}",
                        "text": candidate.content,
                        "title": candidate.title,
                        "date": created.strftime("%Y-%m-%d"),
                        "approved_by": actor_id,
                    }
                )
            elif target == "architecture":
                values.append(
                    {
                        **base,
                        "id": f"arch_mem_{uuid.uuid4().hex[:10]}",
                        "component": candidate.title,
                        "role": candidate.classification,
                        "details": candidate.content,
                    }
                )
            elif target == "open_questions":
                values.append(
                    {
                        **base,
                        "id": f"q_mem_{uuid.uuid4().hex[:10]}",
                        "title": candidate.title,
                        "content": candidate.content,
                    }
                )
            elif target == "assumptions":
                values.append(
                    {
                        **base,
                        "id": f"asm_mem_{uuid.uuid4().hex[:10]}",
                        "title": candidate.title,
                        "content": candidate.content,
                    }
                )

            candidate.status = "approved"
            applied_ids.append(candidate.id)

        if not applied_ids:
            db.commit()
            return {
                "project_id": project_id,
                "state_version_before": before,
                "state_version_after": before,
                "applied": 0,
                "skipped": len(skipped_ids),
                "candidate_ids": applied_ids,
            }

        state.requirements_json = json.dumps(arrays["requirements"])
        state.architecture_json = json.dumps(arrays["architecture"])
        state.decisions_json = json.dumps(arrays["decisions"])
        state.constraints_json = json.dumps(arrays["constraints"])
        state.assumptions_json = json.dumps(arrays["assumptions"])
        state.open_questions_json = json.dumps(arrays["open_questions"])

        after = before + 1
        state.current_version = after
        state.updated_at = datetime.now(timezone.utc)

        snapshot = self.state_service._dump_state_dict(state)
        version_record = ProjectStateVersion(
            project_id=project_id,
            version_number=after,
            snapshot_json=json.dumps(snapshot),
            reason=f"Automatic project memory sync from {source}.",
            change_summary_json=json.dumps(
                {
                    "action": "memory_auto_sync",
                    "source": source,
                    "candidate_ids": applied_ids,
                    "skipped_candidate_ids": skipped_ids,
                }
            ),
            actor_id=actor_id,
        )
        db.add(version_record)

        # A compact audit bridge keeps the existing StateChange history usable
        # without creating a human-review gate for routine note updates.
        audit_change = StateChange(
            project_id=project_id,
            state_version_before=before,
            state_version_after=after,
            operation=ChangeOperation.INSERT.value,
            target_section="memory",
            value_json=json.dumps({"candidate_ids": applied_ids, "source": source}),
            reason=f"Automatic project memory sync from {source}.",
            actor_id=actor_id,
            evidence_ids_json=json.dumps(
                list(
                    dict.fromkeys(
                        ev_id
                        for candidate in candidates
                        if candidate.id in applied_ids
                        for ev_id in self._json_list(candidate.evidence_ids_json)
                    )
                )
            ),
            approval_status=ApprovalStatus.APPROVED.value,
            resolved_at=datetime.now(timezone.utc),
        )
        db.add(audit_change)

        db.commit()
        db.refresh(state)

        logger.info(
            "project_memory_auto_sync: project=%s source=%s applied=%d skipped=%d v%d->v%d",
            project_id,
            source,
            len(applied_ids),
            len(skipped_ids),
            before,
            after,
        )
        return {
            "project_id": project_id,
            "state_version_before": before,
            "state_version_after": after,
            "applied": len(applied_ids),
            "skipped": len(skipped_ids),
            "candidate_ids": applied_ids,
        }

    @staticmethod
    def _json_list(raw: Optional[str]) -> List[Any]:
        try:
            value = json.loads(raw or "[]")
            return value if isinstance(value, list) else []
        except Exception:
            return []

    @staticmethod
    def _candidate_fingerprint(candidate: CandidateKnowledge) -> str:
        evidence = ",".join(sorted(ProjectMemoryService._json_list(candidate.evidence_ids_json)))
        return "|".join(
            [
                candidate.category,
                (candidate.title or "").strip().lower(),
                (candidate.content or "").strip().lower(),
                evidence,
            ]
        )

    @staticmethod
    def _item_fingerprint(item: Any) -> str:
        if not isinstance(item, dict):
            return ""
        evidence_ids = item.get("evidence_ids") or []
        return "|".join(
            [
                str(item.get("category") or "").lower(),
                str(item.get("title") or item.get("text") or "").strip().lower(),
                str(item.get("content") or item.get("details") or "").strip().lower(),
                ",".join(sorted(str(v) for v in evidence_ids)),
            ]
        )
