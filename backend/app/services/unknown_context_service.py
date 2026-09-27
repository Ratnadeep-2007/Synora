import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
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
    ) -> List[PossibleProjectMatch]:
        item = self.get_item(item_id, db, tenant_id)
        payload = self._safe_payload(item.payload_json)

        resolution: ContextResolutionResult = self.context_service.resolve(
            source=item.source,
            payload=payload or {"text": item.content},
            db=db,
            tenant_id=tenant_id,
            actor_id=item.actor_id,
            source_event_id=item.source_event_id,
            record=False,
        )

        # Fresh suggestions replace stale ones (similarity is a suggestion, not state).
        if persist:
            db.query(PossibleProjectMatch).filter(
                PossibleProjectMatch.unknown_item_id == item.id
            ).delete()
            db.commit()

        matches: List[PossibleProjectMatch] = []
        for candidate in resolution.candidate_projects:
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

        item.status = UnknownItemStatus.ASSIGNED.value
        item.assigned_project_id = project.id
        item.assigned_by = actor_id
        item.assigned_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(item)

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

        item = self.get_item(item_id, db, tenant_id)
        project_id = f"proj_{uuid.uuid4().hex[:8]}"
        project = ProjectAgentService().get_or_create_project(
            project_id=project_id,
            db=db,
            workspace_id=workspace_id,
            name=name,
            description=description or f"Created from Unknown Context item {item.id}",
        )
        self._move_evidence(item, project.id, db)
        item.status = UnknownItemStatus.ASSIGNED.value
        item.assigned_project_id = project.id
        item.assigned_by = actor_id
        item.assigned_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(item)
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
