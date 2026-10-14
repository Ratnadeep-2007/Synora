import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.agent_workforce import AgentExecution
from app.services.project_memory_service import ProjectMemoryService
from app.services.project_state_service import ProjectStateService
from app.services.agent_context_packer import pack_agent_context

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Build bounded context from the single shared, project-bounded memory layer.

    The underlying memory engine is shared across all sources, while every
    retrieval remains scoped to the requested project and tenant.
    """

    def __init__(
        self,
        state_service: Optional[ProjectStateService] = None,
        memory_service: Optional[ProjectMemoryService] = None,
    ):
        self.state_service = state_service or ProjectStateService()
        self.memory_service = memory_service or ProjectMemoryService(self.state_service)

    def build_agent_context(
        self,
        project_id: str,
        agent_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        section_filter: Optional[List[str]] = None,
        query: Optional[str] = None,
        limit_evidence: int = 10,
        limit_prior_runs: int = 5,
        limit_knowledge: int = 20,
        token_budget: int = 6000,
    ) -> Dict[str, Any]:
        """Assemble a bounded context view; never expose other projects."""
        memory = self.memory_service.build_context(
            project_id=project_id,
            db=db,
            tenant_id=tenant_id,
            query=query,
            limit_knowledge=limit_knowledge,
            limit_evidence=limit_evidence,
            include_pending=False,
        )

        state = memory["project_state"]
        sections_to_include = section_filter if section_filter is not None else [
            "requirements",
            "decisions",
            "architecture",
            "constraints",
            "assumptions",
            "open_questions",
        ]
        filtered_state = {
            "project_id": state["project_id"],
            "version": state["version"],
            "title": state["title"],
            "vision": state["vision"],
        }
        for section in sections_to_include:
            if section in state:
                filtered_state[section] = state[section]

        prior_runs = (
            db.query(AgentExecution)
            .filter(
                AgentExecution.project_id == project_id,
                AgentExecution.tenant_id == tenant_id,
                AgentExecution.status == "completed",
            )
            .order_by(AgentExecution.created_at.desc())
            .limit(max(0, min(20, limit_prior_runs)))
            .all()
        )

        formatted_prior_runs = [
            {
                "execution_id": r.id,
                "agent_id": r.agent_id,
                "output_type": r.output_type,
                "payload": (
                    json.loads(r.output_payload_json)
                    if r.output_payload_json
                    else {}
                ),
                "created_at": r.created_at.isoformat(),
            }
            for r in prior_runs
        ]

        from app.models.conflict import Conflict
        conflicts = db.query(Conflict).filter(
            Conflict.project_id == project_id,
            Conflict.tenant_id == tenant_id,
            Conflict.status.in_(["open", "under_review", "unresolved"]),
        ).order_by(Conflict.created_at.desc()).limit(8).all()

        return pack_agent_context({
            "tenant_id": tenant_id,
            "project_id": project_id,
            "state_version": memory["state_version"],
            "project_state": filtered_state,
            "knowledge": memory["knowledge"],
            "evidence": memory["evidence"],
            "conflicts": [{
                "id": item.id, "status": item.status, "title": item.title,
                "description": item.description,
                "current_state_reference": item.current_state_reference,
                "proposed_change_reference": item.proposed_change_reference,
                "evidence_ids": self.memory_service._json_list(item.evidence_ids_json),
            } for item in conflicts],
            "prior_agent_outputs": formatted_prior_runs,
            "assembled_for_agent": agent_id,
        }, query=query, token_budget=token_budget)
