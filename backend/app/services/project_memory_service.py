from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.intelligence import CandidateKnowledge
from app.models.project_state import ProjectState, ProjectStateVersion, StateChange, ApprovalStatus, ChangeOperation
from app.services.project_state_service import ProjectStateService
from app.services.memory_retrieval import INACTIVE_STATUSES, query_groups, rank_records, search_predicate

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
        "requirement": "requirements",
        "proposal": "requirements",
        "decision_candidate": "decisions",
        "decision": "decisions",
        "architectural_change": "architecture",
        "question": "open_questions",
        "assumption": "assumptions",
    }

    def __init__(self, state_service: Optional[ProjectStateService] = None, search_provider=None):
        self.state_service = state_service or ProjectStateService()
        self.search_provider = search_provider

    def build_context(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        query: Optional[str] = None,
        limit_knowledge: int = 20,
        limit_evidence: int = 12,
        *,
        include_pending: bool = True,
        include_history: bool = False,
    ) -> Dict[str, Any]:
        """Return bounded memory for one project only."""
        state = self.state_service.get_or_create_state(project_id, db)
        state_dict = self.state_service._dump_state_dict(state)

        from app.models.evidence import Evidence
        from app.models.source_event import SourceEvent

        limit_knowledge = max(0, min(100, limit_knowledge))
        limit_evidence = max(0, min(100, limit_evidence))
        groups = query_groups(query)
        indexed_claims = indexed_evidence = []
        if query:
            from app.services.memory_index_service import MemoryIndexService
            provider = self.search_provider or MemoryIndexService()
            indexed_claims = provider.search(query, project_id, tenant_id, db, kind="claim", limit=40)
            indexed_evidence = provider.search(query, project_id, tenant_id, db, kind="evidence", limit=40)
        # Both spellings occur in legacy default-workspace ingestion. Other
        # tenant IDs are never expanded.
        source_tenants = [tenant_id]
        if tenant_id in {"default_tenant", "tenant_default"}:
            source_tenants = ["default_tenant", "tenant_default"]

        knowledge_query = (
            db.query(CandidateKnowledge)
            .filter(CandidateKnowledge.project_id == project_id)
        )
        if not include_history:
            knowledge_query = knowledge_query.filter(
                func.lower(CandidateKnowledge.status).notin_(INACTIVE_STATUSES),
                func.lower(CandidateKnowledge.classification).notin_(INACTIVE_STATUSES),
            )
        if not include_pending:
            knowledge_query = knowledge_query.filter(CandidateKnowledge.status == "approved")
        knowledge_base = knowledge_query
        if groups:
            predicate, score = search_predicate([CandidateKnowledge.title, CandidateKnowledge.content], groups)
            knowledge_query = knowledge_query.filter(predicate).order_by(score.desc())
        knowledge_rows = knowledge_query.order_by(
            CandidateKnowledge.created_at.desc(), CandidateKnowledge.id.asc()
        ).limit(min(800, max(160, limit_knowledge * 8)) if limit_knowledge else 0).all()
        if indexed_claims and limit_knowledge:
            indexed_rows = knowledge_base.filter(CandidateKnowledge.id.in_([hit["id"] for hit in indexed_claims])).all()
            knowledge_rows = list({row.id: row for row in [*indexed_rows, *knowledge_rows]}.values())

        # CandidateKnowledge has no tenant column. Verify its source links in
        # one bounded query instead of trusting a tenant ID in the response.
        referenced_ids = list(dict.fromkeys(
            str(eid) for item in knowledge_rows for eid in self._json_list(item.evidence_ids_json)
        ))
        evidence_scope = db.query(Evidence).join(SourceEvent, Evidence.source_event_id == SourceEvent.event_id).filter(
            Evidence.project_id == project_id,
            SourceEvent.tenant_id.in_(source_tenants),
        )
        allowed_ids = set()
        for offset in range(0, len(referenced_ids), 500):
            allowed_ids.update(row[0] for row in evidence_scope.with_entities(Evidence.id).filter(
                Evidence.id.in_(referenced_ids[offset:offset + 500])
            ).all())

        knowledge_records = []
        for item in knowledge_rows:
            item_evidence = self._json_list(item.evidence_ids_json)
            scoped_ids = [eid for eid in item_evidence if eid in allowed_ids]
            if item_evidence and len(scoped_ids) != len(item_evidence):
                continue
            if not scoped_ids:
                # A status label alone cannot establish an orphan claim's
                # source tenant or make it citable, even in a review response.
                continue
            knowledge_records.append({
                "id": item.id, "category": item.category, "classification": item.classification,
                "title": item.title, "content": item.content, "confidence": item.confidence,
                "status": item.status, "meeting_id": item.meeting_id, "evidence_ids": scoped_ids,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            })

        # Consolidate identical statements for retrieval only. The ledger and
        # immutable sources retain all their original rows.
        consolidated: Dict[tuple, Dict[str, Any]] = {}
        for record in rank_records(knowledge_records, query, indexed_claims):
            key = (record["category"], record["status"], " ".join(record["content"].lower().split()))
            if key in consolidated:
                existing = consolidated[key]
                existing["evidence_ids"] = list(dict.fromkeys(existing["evidence_ids"] + record["evidence_ids"]))
                existing.setdefault("supporting_candidate_ids", []).append(record["id"])
            else:
                consolidated[key] = record
        knowledge = list(consolidated.values())[:limit_knowledge]

        evidence_query = evidence_scope
        if groups:
            predicate, score = search_predicate([Evidence.content], groups)
            evidence_query = evidence_query.filter(predicate).order_by(score.desc())
        evidence_rows = evidence_query.order_by(Evidence.created_at.desc(), Evidence.id.asc()).limit(
            min(800, max(160, limit_evidence * 8)) if limit_evidence else 0
        ).all()
        if indexed_evidence and limit_evidence:
            indexed_rows = evidence_scope.filter(Evidence.id.in_([hit["id"] for hit in indexed_evidence])).all()
            evidence_rows = list({row.id: row for row in [*indexed_rows, *evidence_rows]}.values())

        linked_ids = list(dict.fromkeys(eid for item in knowledge for eid in item["evidence_ids"]))
        if not groups:
            # Session-start context must retain the sources of lasting approved
            # decisions even when they are older than the recent-event window.
            for section in ("constraints", "decisions", "open_questions"):
                for item in state_dict.get(section, []):
                    if isinstance(item, dict):
                        linked_ids.extend(item.get("evidence_ids") or [])
        linked_ids = list(dict.fromkeys(linked_ids))[:max(0, limit_evidence * 8)]
        linked_rows = evidence_scope.filter(Evidence.id.in_(linked_ids)).all() if linked_ids else []
        linked_by_id = {row.id: row for row in linked_rows}
        # Claim sources come first, so arbitrary recent chatter cannot crowd
        # out the ground truth for selected knowledge.
        rows_by_id = {row.id: row for row in [
            *(linked_by_id[eid] for eid in linked_ids if eid in linked_by_id), *evidence_rows
        ]}
        evidence_records = [{
            "id": item.id, "source": item.source, "source_event_id": item.source_event_id,
            "meeting_id": item.meeting_id, "transcript_id": item.transcript_id,
            "transcript_entry_id": item.transcript_entry_id, "speaker": item.actor_id or "Unknown",
            "text": item.content, "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
        } for item in rows_by_id.values()]
        if groups:
            ranked = rank_records(evidence_records, query, indexed_evidence)
            ranked_ids = {item["id"] for item in ranked}
            # A selected claim may paraphrase its original source. Keep that
            # source even when the source itself has no lexical query overlap.
            ranked += [item for item in evidence_records if item["id"] in linked_ids and item["id"] not in ranked_ids]
        else:
            ranked = evidence_records
        evidence = ranked[:limit_evidence]

        return {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "state_version": state.current_version,
            "project_state": state_dict,
            "knowledge": knowledge,
            "evidence": evidence,
            "retrieval": {"strategy": "hybrid" if indexed_claims or indexed_evidence else "lexical_expansion", "query_terms": [sorted(group) for group in groups],
                          "indexed_claim_hits": len(indexed_claims), "indexed_evidence_hits": len(indexed_evidence),
                          "include_pending": include_pending, "include_history": include_history,
                          "candidate_pool_limit": min(800, max(160, max(limit_knowledge, limit_evidence) * 8))},
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

            if candidate.status in {"rejected", "superseded", "conflict"}:
                skipped_ids.append(candidate.id)
                continue
            from app.services.memory_lifecycle import MemoryLifecycleService
            lifecycle = MemoryLifecycleService()
            if lifecycle.replacement_conflict(candidate, state, db, source=source):
                skipped_ids.append(candidate.id)
                continue
            if candidate.status != "approved" and (
                candidate.category == "proposal" or candidate.classification in {"Proposal", "Idea", "Discussion"}
            ):
                lifecycle.propose(candidate, state, db)
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

            # A concept title is the visible identity of a memory note. If the
            # same concept arrives later from Meet or WhatsApp, update that
            # note instead of appending a duplicate.
            matching_index = None
            incoming_title = (candidate.title or "").strip().lower()
            if incoming_title:
                for index, item in enumerate(values):
                    if not isinstance(item, dict):
                        continue
                    existing_title = str(
                        item.get("title") or item.get("text") or item.get("component") or ""
                    ).strip().lower()
                    if existing_title == incoming_title:
                        matching_index = index
                        break

            if matching_index is not None:
                existing = dict(values[matching_index])
                existing_content = str(
                    existing.get("content")
                    or existing.get("details")
                    or existing.get("text")
                    or existing.get("role")
                    or ""
                ).strip()
                incoming_content = (candidate.content or "").strip()
                if existing_content != incoming_content:
                    if "content" in existing:
                        existing["content"] = candidate.content
                    elif "details" in existing:
                        existing["details"] = candidate.content
                    elif "text" in existing:
                        existing["text"] = candidate.content
                    else:
                        existing["content"] = candidate.content
                    existing["source"] = source
                    existing["updated_at"] = (candidate.created_at or datetime.now(timezone.utc)).isoformat()
                    existing["updated_by"] = actor_id
                    existing["evidence_ids"] = list(dict.fromkeys(
                        [*(existing.get("evidence_ids") or []), *evidence_ids]
                    ))
                    values[matching_index] = existing
                    applied_ids.append(candidate.id)
                else:
                    combined_evidence = list(dict.fromkeys(
                        [*(existing.get("evidence_ids") or []), *evidence_ids]
                    ))
                    if combined_evidence != (existing.get("evidence_ids") or []):
                        existing["evidence_ids"] = combined_evidence
                        values[matching_index] = existing
                        applied_ids.append(candidate.id)
                    else:
                        skipped_ids.append(candidate.id)
                candidate.status = "approved"
                continue

            if any(self._item_fingerprint(item) == fingerprint for item in values):
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
