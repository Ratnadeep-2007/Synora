import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.core.config import settings
from app.models.context_resolution import (
    PossibleProjectMatch,
    UnknownContextItem,
    UnknownItemStatus,
)
from app.models.evidence import Evidence
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, Project
from app.models.project_state import ProjectState
from app.models.source_event import SourceEvent
from app.schemas.context import (
    CandidateProject,
    ContextResolutionResult,
    PossibleMatchRead,
    UnknownContextItemRead,
)
from app.services.audit_service import AuditService
from app.services.context_intelligence import ContextIntelligenceService

logger = logging.getLogger(__name__)


class UnknownContextError(SynesisException):
    """Raised for invalid Unknown Context operations."""


class UnknownContextService:
    """Human triage for source evidence that could not be confidently mapped.

    Assignment is the ONLY path that moves evidence into a real project. It is
    always an explicit human action (or a deterministic trusted mapping), never
    a silent consequence of model confidence.
    """

    def __init__(
        self,
        context_service: Optional[ContextIntelligenceService] = None,
        audit_service: Optional[AuditService] = None,
    ):
        self.context_service = context_service or ContextIntelligenceService()
        self.audit_service = audit_service or AuditService()

    # ------------------------------------------------------------------
    # Create / list
    # ------------------------------------------------------------------
    def create_item(
        self,
        source: str,
        payload: Dict[str, Any],
        db: Session,
        tenant_id: str = "default_tenant",
        source_event_id: Optional[str] = None,
        evidence_id: Optional[str] = None,
        meeting_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        content: str = "",
        occurred_at: Optional[datetime] = None,
        context_resolution_id: Optional[str] = None,
        workspace_id: str = "ws_default",
    ) -> UnknownContextItem:
        self.context_service.ensure_unknown_context_project(db, workspace_id=workspace_id)

        # Idempotency: one Unknown Context item per (source, source_event_id).
        if source_event_id:
            existing = (
                db.query(UnknownContextItem)
                .filter(
                    UnknownContextItem.source == source,
                    UnknownContextItem.source_event_id == source_event_id,
                )
                .first()
            )
            if existing:
                return existing

        item = UnknownContextItem(
            project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
            tenant_id=tenant_id,
            source=source,
            source_event_id=source_event_id,
            evidence_id=evidence_id,
            meeting_id=meeting_id,
            actor_id=actor_id,
            occurred_at=occurred_at,
            content=content or ContextIntelligenceService.extract_text(source, payload),
            payload_json=json.dumps(payload, default=str),
            context_resolution_id=context_resolution_id,
            status=UnknownItemStatus.PENDING.value,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        logger.info(
            "unknown_context_item_created: id=%s source=%s source_event_id=%s",
            item.id,
            source,
            source_event_id,
        )
        return item

    def file_unresolved_meeting_evidence(
        self,
        meeting_id: str,
        evidence_records: List[Evidence],
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> int:
        """File meeting evidence that stayed in Unknown Context as inbox items.

        Meeting routing parks unresolved evidence under the Unknown Context
        system project, but without an UnknownContextItem it never reaches
        the Context Inbox, the Unknown board, or the Atlas Unknown column.
        One item per evidence row (the board/Atlas render one free note per
        item). Idempotent: an evidence row that already has an item in any
        status is never re-filed. Both evidence IDs and (source, source_event_id)
        keys are checked in bulk so pipeline re-runs do not duplicate items.
        Returns the number of newly filed items.
        """
        records = [evidence for evidence in evidence_records if (evidence.content or "").strip()]
        if not records:
            return 0
        event_keys = {f"meeting:{meeting_id}:evidence:{evidence.id}" for evidence in records}
        existing = db.query(UnknownContextItem).filter(or_(
            UnknownContextItem.evidence_id.in_([evidence.id for evidence in records]),
            UnknownContextItem.source_event_id.in_(event_keys),
        )).all()
        seen_evidence = {item.evidence_id for item in existing}
        seen_events = {(item.source, item.source_event_id) for item in existing}
        pending = []
        for evidence in records:
            content = (evidence.content or "").strip()
            source = evidence.source or "google_meet"
            event_key = f"meeting:{meeting_id}:evidence:{evidence.id}"
            if evidence.id in seen_evidence or (source, event_key) in seen_events:
                continue
            pending.append(UnknownContextItem(
                project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
                tenant_id=tenant_id,
                source=source,
                payload_json=json.dumps({
                    "meeting_id": meeting_id,
                    "evidence_id": evidence.id,
                    "speaker": evidence.actor_id,
                }),
                source_event_id=event_key,
                evidence_id=evidence.id,
                meeting_id=meeting_id,
                actor_id=evidence.actor_id,
                content=evidence.content or "",
                occurred_at=evidence.occurred_at,
                status=UnknownItemStatus.PENDING.value,
            ))
            seen_evidence.add(evidence.id)
            seen_events.add((source, event_key))
        filed = len(pending)
        if filed:
            # One transaction for the meeting, rather than several network
            # round trips and an expiration/reload for every spoken fragment.
            self.context_service.ensure_unknown_context_project(db)
            db.add_all(pending)
            db.commit()
            logger.info(
                "unknown_context_meeting_evidence_filed: meeting=%s items=%d",
                meeting_id,
                filed,
            )
        return filed

    def list_items(
        self,
        db: Session,
        tenant_id: str = "default_tenant",
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[UnknownContextItem]:
        query = db.query(UnknownContextItem).filter(UnknownContextItem.tenant_id == tenant_id)
        if status:
            query = query.filter(UnknownContextItem.status == status)
        if source:
            query = query.filter(UnknownContextItem.source == source)
        return (
            query.order_by(UnknownContextItem.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def pending_count(self, db: Session, tenant_id: str = "default_tenant") -> int:
        return (
            db.query(UnknownContextItem)
            .filter(
                UnknownContextItem.tenant_id == tenant_id,
                UnknownContextItem.status == UnknownItemStatus.PENDING.value,
            )
            .count()
        )

    @staticmethod
    def project_ids_for_workspace(db: Session, workspace_id: str) -> List[str]:
        return [
            project_id for (project_id,) in db.query(Project.id)
            .filter(Project.workspace_id == workspace_id, Project.is_system.is_(False))
            .all()
        ]

    def refresh_pending_suggestions(
        self,
        db: Session,
        tenant_id: str = "default_tenant",
        workspace_id: str = "ws_default",
        limit: int = 100,
    ) -> Dict[str, int]:
        """Re-rank pending inbox items after a project changes the candidate set.

        Bounded to the most recent ``limit`` pending items: with a large
        backlog a full re-rank takes minutes of database round-trips, and
        suggestions are advisory. Older items are re-ranked on the next
        project change or when opened in triage.
        """
        project_ids = self.project_ids_for_workspace(db, workspace_id)
        projects = self.context_service._authorized_projects(db, tenant_id, project_ids)
        corpus = self.context_service._build_corpus(projects, db, tenant_id)
        pending_items = (
            db.query(UnknownContextItem)
            .filter(
                UnknownContextItem.tenant_id == tenant_id,
                UnknownContextItem.status == UnknownItemStatus.PENDING.value,
            )
            .order_by(UnknownContextItem.created_at.desc())
            .limit(limit)
            .all()
        )
        refreshed = 0
        suggested = 0
        for item in pending_items:
            try:
                matches = self.suggest_matches(
                    item.id,
                    db,
                    tenant_id=tenant_id,
                    authorized_project_ids=project_ids,
                    semantic=False,
                    project_corpus=corpus,
                )
                refreshed += 1
                suggested += bool(matches)
            except Exception:
                logger.exception("unknown_context_suggestion_refresh_failed: item=%s", item.id)
        return {"items_refreshed": refreshed, "items_with_suggestions": suggested}

    def get_item(
        self, item_id: str, db: Session, tenant_id: str = "default_tenant"
    ) -> UnknownContextItem:
        item = (
            db.query(UnknownContextItem)
            .filter(
                UnknownContextItem.id == item_id,
                UnknownContextItem.tenant_id == tenant_id,
            )
            .first()
        )
        if not item:
            raise UnknownContextError(f"Unknown Context item '{item_id}' not found.")
        return item

    # ------------------------------------------------------------------
    # Explainable suggestions
    # ------------------------------------------------------------------
    def suggest_matches(
        self,
        item_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        persist: bool = True,
        authorized_project_ids: Optional[List[str]] = None,
        semantic: bool = True,
        project_corpus: Optional[List[Dict[str, Any]]] = None,
    ) -> List[PossibleProjectMatch]:
        item = self.get_item(item_id, db, tenant_id)
        payload = self._safe_payload(item.payload_json)

        # Re-resolve with the item's own continuity (same-group thread +
        # cross-source Meet/WhatsApp context), not the bare sentence, so a
        # terse follow-up ("yes, ship it") suggests the project its thread
        # was about.
        continuity = ""
        resolution: Optional[ContextResolutionResult] = None
        if semantic:
            try:
                from app.services.conversation_continuity import (
                    build_continuity_window,
                    build_meet_continuity,
                )

                if item.source == "whatsapp":
                    continuity = build_continuity_window(
                        db=db,
                        tenant_id=tenant_id,
                        group_name=payload.get("group_name"),
                        group_jid=payload.get("group_jid"),
                        current_text=item.content or "",
                        actor_jid=payload.get("sender_jid"),
                    )
                else:
                    continuity = build_meet_continuity(
                        db, tenant_id=tenant_id, meeting_id=item.meeting_id
                    )
            except Exception:
                continuity = ""

            resolution = self.context_service.resolve(
                source=item.source,
                payload=payload or {"text": item.content},
                db=db,
                tenant_id=tenant_id,
                actor_id=item.actor_id,
                source_event_id=item.source_event_id,
                continuity_context=continuity or None,
                authorized_project_ids=authorized_project_ids,
                record=False,
            )

        candidates = list(resolution.candidate_projects) if resolution else []
        # Recommendations remain human-reviewed. When semantic routing is
        # unavailable, show explainable lexical matches instead of leaving the
        # inbox blank; this never auto-assigns evidence to a project.
        if not resolution or not resolution.is_casual:
            corpus = project_corpus
            if corpus is None:
                projects = self.context_service._authorized_projects(
                    db, tenant_id, authorized_project_ids
                )
                corpus = self.context_service._build_corpus(projects, db, tenant_id)
            lexical_matches = self._similarity_suggestions(
                f"{item.content or ''} {continuity or ''}", corpus
            )
            by_project = {candidate.project_id: candidate for candidate in candidates}
            for candidate in lexical_matches:
                existing = by_project.get(candidate.project_id)
                if existing is None:
                    by_project[candidate.project_id] = candidate
            candidates = sorted(
                by_project.values(), key=lambda candidate: candidate.confidence, reverse=True
            )[: settings.CONTEXT_RESOLUTION_CANDIDATE_LIMIT]

        # Fresh suggestions replace stale ones (similarity is a suggestion, not state).
        if persist:
            db.query(PossibleProjectMatch).filter(
                PossibleProjectMatch.unknown_item_id == item.id
            ).delete()
            db.commit()

        matches: List[PossibleProjectMatch] = []
        for candidate in candidates:
            conflicts = self._detect_conflicts(candidate, item, db)
            match = PossibleProjectMatch(
                unknown_item_id=item.id,
                candidate_project_id=candidate.project_id,
                similarity_reason_json=json.dumps(candidate.reasons),
                supporting_evidence_ids_json=json.dumps(candidate.supporting_evidence_ids),
                supporting_state_sections_json=json.dumps(candidate.supporting_state_sections),
                conflicts_json=json.dumps(conflicts),
                recommendation="review",
            )
            if persist:
                db.add(match)
            matches.append(match)
        if persist:
            db.commit()
            for m in matches:
                db.refresh(m)
        return matches

    @staticmethod
    def _similarity_suggestions(text: str, corpus: List[Dict[str, Any]]) -> List[CandidateProject]:
        """Create conservative, explainable suggestions from project/content overlap."""
        stop_words = {
            "the", "and", "for", "with", "that", "this", "from", "have", "has",
            "will", "should", "could", "would", "what", "when", "where", "which",
            "create", "created", "make", "build", "need", "want", "please", "team",
            "project", "workspace", "system", "context", "unknown", "source", "item",
            "software", "architecture", "product", "engineering", "general", "application",
        }
        text_terms = {
            term for term in re.findall(r"[a-z0-9]{3,}", (text or "").lower())
            if term not in stop_words
        }
        if not text_terms:
            return []

        suggestions: List[CandidateProject] = []
        for entry in corpus:
            project_id = str(entry.get("project_id") or "")
            name = str(entry.get("name") or project_id)
            name_terms = {
                term for term in re.findall(r"[a-z0-9]{3,}", name.lower())
                if term not in stop_words
            }
            context_terms = UnknownContextService._project_context_terms(entry) - stop_words
            name_overlap = text_terms & name_terms
            context_overlap = text_terms & context_terms
            if not name_overlap and len(context_overlap) < 2:
                continue

            reasons = []
            if name_overlap:
                reasons.append("Matched project name: " + ", ".join(sorted(name_overlap)))
            if context_overlap:
                reasons.append(f"Topical overlap with project details ({len(context_overlap)} terms)")
            confidence = min(0.95, 0.45 + 0.16 * len(name_overlap) + 0.08 * len(context_overlap))
            suggestions.append(CandidateProject(
                project_id=project_id,
                project_name=name,
                confidence=confidence,
                reasons=reasons,
            ))
        return sorted(suggestions, key=lambda candidate: candidate.confidence, reverse=True)

    @staticmethod
    def _project_context_terms(entry: Dict[str, Any]) -> set[str]:
        text = " ".join((
            str(entry.get("description") or ""),
            str(entry.get("domain") or ""),
            json.dumps(entry.get("business_concepts", []), default=str),
            json.dumps(entry.get("technical_concepts", []), default=str),
            json.dumps(entry.get("entities", []), default=str),
            json.dumps(entry.get("state", {}), default=str),
            json.dumps(entry.get("recent_evidence", []), default=str),
        )).lower()
        return set(re.findall(r"[a-z0-9]{3,}", text))

    def _detect_conflicts(
        self,
        candidate: CandidateProject,
        item: UnknownContextItem,
        db: Session,
    ) -> List[str]:
        """Surface conflicts between current Project State and the candidate.

        Current authoritative state has higher importance than stale evidence,
        so explicit contradiction signals are reported for human review.
        """
        conflicts: List[str] = []
        text = (item.content or "").lower()
        if not text:
            return conflicts
        state = (
            db.query(ProjectState)
            .filter(ProjectState.project_id == candidate.project_id)
            .first()
        )
        if not state:
            return conflicts
        try:
            decisions = json.loads(state.decisions_json or "[]")
        except Exception:
            decisions = []
        for dec in decisions:
            dec_text = (dec.get("text", "") if isinstance(dec, dict) else str(dec)).lower()
            if "postgres" in dec_text and any(k in text for k in ("mongodb", "dynamodb", "nosql")):
                conflicts.append("Conflicts with approved database decision")
        return conflicts

    # ------------------------------------------------------------------
    # Human actions
    # ------------------------------------------------------------------
    def assign_to_project(
        self,
        item_id: str,
        project_id: str,
        db: Session,
        actor_id: str,
        tenant_id: str = "default_tenant",
        note: Optional[str] = None,
        authorized_project_ids: Optional[List[str]] = None,
    ) -> UnknownContextItem:
        item = self.get_item(item_id, db, tenant_id)
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project or project.is_system:
            raise UnknownContextError(f"Destination project '{project_id}' is not assignable.")
        if authorized_project_ids is not None and project.id not in authorized_project_ids:
            raise UnknownContextError("Assignment rejected: project is not authorized.")

        self._move_evidence(item, project.id, db)

        # A human routing decision should teach the resolver and continue the
        # normal downstream automation without requiring another manual action.
        try:
            from app.services.context_feedback_service import ContextFeedbackService
            ContextFeedbackService(db).record_feedback(
                selected_project_id=project.id,
                original_predicted_project_id=(
                    next((m.candidate_project_id for m in item.matches if m.recommendation == "review"), None)
                    if item.matches else None
                ),
                action="assigned",
                actor_id=actor_id,
                reason=note or "Human resolved Unknown Context routing.",
                text_snippet=item.content,
                source_event_id=item.source_event_id,
                resolution_id=item.context_resolution_id,
                evidence_id=item.evidence_id,
                tenant_id=tenant_id,
                workspace_id=project.workspace_id or "ws_default",
            )
        except Exception as exc:
            logger.warning("unknown_context_feedback_record_failed: %s", exc)

        try:
            from app.services.knowledge_intelligence import KnowledgeIntelligenceService
            evidence = (
                db.query(Evidence)
                .filter(Evidence.id == item.evidence_id)
                .first()
                if item.evidence_id else None
            )
            if evidence:
                extraction = KnowledgeIntelligenceService().extract_items([evidence], item.source)
                candidates = KnowledgeIntelligenceService().persist_candidates(
                    extraction,
                    project_id=project.id,
                    db=db,
                    meeting_id=item.meeting_id,
                )
                from app.services.conflict_service import ConflictService
                from app.services.project_memory_service import ProjectMemoryService

                conflict_service = ConflictService()
                safe_candidates = []
                for candidate in candidates:
                    conflict = conflict_service.detect_conflicts_for_candidate(
                        candidate, db=db, tenant_id=tenant_id, source=item.source
                    )
                    if conflict:
                        candidate.status = "conflict"
                        db.add(candidate)
                    else:
                        safe_candidates.append(candidate)
                db.commit()
                ProjectMemoryService().apply_candidates(
                    project_id=project.id,
                    candidates=safe_candidates,
                    db=db,
                    source=item.source,
                    actor_id=actor_id,
                )
        except Exception as exc:
            logger.warning("unknown_context_downstream_knowledge_failed: %s", exc)

        try:
            from app.services.project_semantic_profile_service import ProjectSemanticProfileService
            ProjectSemanticProfileService().rebuild_profile(
                project,
                db,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.warning("unknown_context_profile_refresh_failed: %s", exc)

        item.status = UnknownItemStatus.ASSIGNED.value
        item.assigned_project_id = project.id
        item.assigned_by = actor_id
        item.assigned_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(item)

        # Context assignment is a low-risk visual update: add/adjust semantic
        # notes through the existing three-way merge engine so user placement is
        # preserved and the project canvas reflects the newly classified evidence.
        try:
            from app.services.visual_patch_service import VisualPatchService
            patch = VisualPatchService().generate_patch_from_evidence(
                project_id=project.id,
                text=item.content,
                db=db,
                evidence_ids=[item.evidence_id] if item.evidence_id else [],
                tenant_id=tenant_id,
            )
            VisualPatchService().apply_patch(
                project_id=project.id,
                patch=patch,
                db=db,
                actor_id="synora_agent",
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.warning("unknown_context_visual_refresh_failed: %s", exc)

        self.audit_service.record_event(
            action="unknown_context_assigned",
            actor_id=actor_id,
            resource_type="unknown_context_item",
            resource_id=item.id,
            db=db,
            tenant_id=tenant_id,
            after_state={"project_id": project.id, "note": note},
        )
        logger.info(
            "unknown_context_assigned: item=%s project=%s actor=%s",
            item.id,
            project.id,
            actor_id,
        )
        return item

    def keep_unknown(
        self, item_id: str, db: Session, tenant_id: str = "default_tenant"
    ) -> UnknownContextItem:
        item = self.get_item(item_id, db, tenant_id)
        item.status = UnknownItemStatus.KEPT.value
        db.commit()
        db.refresh(item)
        return item

    def dismiss(
        self, item_id: str, db: Session, actor_id: str, tenant_id: str = "default_tenant",
        reason: Optional[str] = None,
    ) -> UnknownContextItem:
        item = self.get_item(item_id, db, tenant_id)
        item.status = UnknownItemStatus.DISMISSED.value
        item.assigned_by = actor_id
        item.assigned_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(item)
        self.audit_service.record_event(
            action="unknown_context_dismissed",
            actor_id=actor_id,
            resource_type="unknown_context_item",
            resource_id=item.id,
            db=db,
            tenant_id=tenant_id,
            after_state={"reason": reason},
        )
        return item

    def delete_item(
        self, item_id: str, db: Session, actor_id: str, tenant_id: str = "default_tenant"
    ) -> Dict[str, Any]:
        """Hard-delete one Unknown Context item and its unassigned content.

        Unlike dismiss (a soft status), this removes the inbox record, its
        project matches, its cluster membership, and - only while the linked
        evidence still belongs to the Unknown Context system project - the
        evidence and source event themselves. Evidence that was already
        assigned into a real project is project memory and is never deleted
        from here.
        """
        item = self.get_item(item_id, db, tenant_id)
        return self._delete_items([item], db, actor_id, tenant_id)

    def delete_pending(
        self, db: Session, actor_id: str, tenant_id: str = "default_tenant",
        status: str = UnknownItemStatus.PENDING.value,
    ) -> Dict[str, Any]:
        """Hard-delete every item in the given inbox status (bulk clear)."""
        items = (
            db.query(UnknownContextItem)
            .filter(
                UnknownContextItem.tenant_id == tenant_id,
                UnknownContextItem.status == status,
            )
            .all()
        )
        return self._delete_items(items, db, actor_id, tenant_id)

    def _delete_items(
        self, items: List[UnknownContextItem], db: Session, actor_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        from app.models.unknown_cluster import UnknownCluster

        item_ids = [item.id for item in items]

        # Bulk deletes with IN queries: a per-item loop over a large backlog
        # (hundreds of items x several Neon round-trips each) outlived every
        # client timeout and rolled back, deleting nothing.
        def _chunks(values, size=200):
            for i in range(0, len(values), size):
                yield values[i:i + size]

        evidence_ids = [item.evidence_id for item in items if item.evidence_id]
        deletable_evidence_ids: List[str] = []
        deletable_event_ids: List[str] = []
        for chunk in _chunks(evidence_ids):
            rows = (
                db.query(Evidence.id, Evidence.project_id, Evidence.source_event_id)
                .filter(Evidence.id.in_(chunk))
                .all()
            )
            for ev_id, ev_project, ev_event in rows:
                if ev_project == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID:
                    deletable_evidence_ids.append(ev_id)
                    if ev_event:
                        deletable_event_ids.append(ev_event)
        owned_event_ids: List[str] = []
        for chunk in _chunks(deletable_event_ids):
            rows = (
                db.query(SourceEvent.event_id, SourceEvent.project_id)
                .filter(SourceEvent.event_id.in_(chunk))
                .all()
            )
            owned_event_ids.extend(
                event_id for event_id, ev_project in rows
                if ev_project == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
            )

        for chunk in _chunks(item_ids):
            db.query(PossibleProjectMatch).filter(
                PossibleProjectMatch.unknown_item_id.in_(chunk)
            ).delete(synchronize_session=False)
        for chunk in _chunks(deletable_evidence_ids):
            db.query(Evidence).filter(Evidence.id.in_(chunk)).delete(
                synchronize_session=False
            )
        for chunk in _chunks(owned_event_ids):
            db.query(SourceEvent).filter(
                SourceEvent.event_id.in_(chunk)
            ).delete(synchronize_session=False)
        evidence_deleted = len(deletable_evidence_ids)
        for chunk in _chunks(item_ids):
            db.query(UnknownContextItem).filter(
                UnknownContextItem.id.in_(chunk)
            ).delete(synchronize_session=False)

        if item_ids:
            for cluster in db.query(UnknownCluster).filter(
                UnknownCluster.tenant_id == tenant_id
            ).all():
                retained = [i for i in cluster.get_item_ids() if i not in item_ids]
                if len(retained) != len(cluster.get_item_ids()):
                    if retained:
                        cluster.set_item_ids(retained)
                    else:
                        db.delete(cluster)
        db.commit()

        # Refresh both visual surfaces so deleted notes vanish immediately.
        for refresher in ("board", "atlas"):
            try:
                if refresher == "board":
                    from app.services.unknown_context_visual import (
                        render_unknown_context_board,
                    )

                    render_unknown_context_board(db, tenant_id=tenant_id)
                else:
                    from app.services.workspace_atlas_service import (
                        WorkspaceAtlasService,
                    )

                    WorkspaceAtlasService().get_or_sync(
                        db=db, tenant_id=tenant_id, workspace_id="ws_default", force=False
                    )
            except Exception as exc:
                logger.warning("unknown_context_delete_%s_refresh_failed: %s", refresher, exc)

        self.audit_service.record_event(
            action="unknown_context_deleted",
            actor_id=actor_id,
            resource_type="unknown_context_item",
            resource_id=item_ids[0] if len(item_ids) == 1 else "bulk",
            db=db,
            tenant_id=tenant_id,
            after_state={"deleted_items": len(item_ids), "deleted_evidence": evidence_deleted},
        )
        logger.info(
            "unknown_context_deleted: items=%d evidence=%d actor=%s",
            len(item_ids),
            evidence_deleted,
            actor_id,
        )
        return {
            "deleted_items": len(item_ids),
            "deleted_evidence": evidence_deleted,
            "item_ids": item_ids,
        }

    def create_project_from_item(
        self,
        item_id: str,
        name: str,
        db: Session,
        actor_id: str,
        tenant_id: str = "default_tenant",
        description: Optional[str] = None,
        workspace_id: str = "ws_default",
    ) -> Project:
        from app.services.project_agent_service import ProjectAgentService
        import uuid
        from sqlalchemy import func

        clean_name = (name or "").strip()
        if not clean_name:
            raise UnknownContextError("Project name cannot be empty.")

        existing = (
            db.query(Project)
            .filter(
                Project.workspace_id == workspace_id,
                func.lower(Project.name) == func.lower(clean_name),
                Project.is_system.is_(False),
            )
            .first()
        )
        if existing:
            raise UnknownContextError(
                f"A project with the name '{clean_name}' already exists (ID: {existing.id}). "
                f"Please choose a different name or assign the item to the existing project."
            )

        item = self.get_item(item_id, db, tenant_id)
        project_id = f"proj_{uuid.uuid4().hex[:8]}"
        project = ProjectAgentService().get_or_create_project(
            project_id=project_id,
            db=db,
            workspace_id=workspace_id,
            name=clean_name,
            description=description or f"Created from Unknown Context item {item.id}",
        )
        self.assign_to_project(
            item_id=item.id,
            project_id=project.id,
            db=db,
            actor_id=actor_id,
            tenant_id=tenant_id,
            note="Assigned to the project created from this context item.",
        )
        self.refresh_pending_suggestions(
            db, tenant_id=tenant_id, workspace_id=workspace_id
        )
        item = self.get_item(item_id, db, tenant_id)
        self.audit_service.record_event(
            action="unknown_context_project_created",
            actor_id=actor_id,
            resource_type="unknown_context_item",
            resource_id=item.id,
            db=db,
            tenant_id=tenant_id,
            after_state={"project_id": project.id, "project_name": name},
        )
        return project

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _move_evidence(self, item: UnknownContextItem, project_id: str, db: Session) -> None:
        """Re-home evidence + source event into the destination project.

        Provenance (source, sender, timestamp, source_event_id) is preserved;
        only the project boundary changes.
        """
        if item.evidence_id:
            evidence = db.query(Evidence).filter(Evidence.id == item.evidence_id).first()
            if evidence:
                evidence.project_id = project_id
        if item.source_event_id:
            event = (
                db.query(SourceEvent)
                .filter(
                    SourceEvent.source_event_id == item.source_event_id,
                    SourceEvent.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
                )
                .first()
            )
            if event:
                event.project_id = project_id
        db.commit()

    @staticmethod
    def _safe_payload(raw: Optional[str]) -> Dict[str, Any]:
        try:
            value = json.loads(raw) if raw else {}
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def format_item_read(
        self, item: UnknownContextItem, db: Session
    ) -> UnknownContextItemRead:
        matches: List[PossibleMatchRead] = []
        for m in item.matches:
            project = db.query(Project).filter(Project.id == m.candidate_project_id).first()
            matches.append(
                PossibleMatchRead(
                    id=m.id,
                    unknown_item_id=m.unknown_item_id,
                    candidate_project_id=m.candidate_project_id,
                    candidate_project_name=project.name if project else None,
                    similarity_reason=self._json_list(m.similarity_reason_json),
                    supporting_evidence_ids=self._json_list(m.supporting_evidence_ids_json),
                    supporting_state_sections=self._json_list(m.supporting_state_sections_json),
                    conflicts=self._json_list(m.conflicts_json),
                    recommendation=m.recommendation,
                    created_at=m.created_at,
                )
            )
        return UnknownContextItemRead(
            id=item.id,
            project_id=item.project_id,
            tenant_id=item.tenant_id,
            source=item.source,
            source_event_id=item.source_event_id,
            evidence_id=item.evidence_id,
            meeting_id=item.meeting_id,
            actor_id=item.actor_id,
            occurred_at=item.occurred_at,
            content=item.content,
            payload=self._safe_payload(item.payload_json),
            status=item.status,
            assigned_project_id=item.assigned_project_id,
            assigned_by=item.assigned_by,
            assigned_at=item.assigned_at,
            created_at=item.created_at,
            matches=matches,
        )

    @staticmethod
    def _json_list(raw: Optional[str]) -> List[Any]:
        try:
            value = json.loads(raw) if raw else []
            return value if isinstance(value, list) else []
        except Exception:
            return []
