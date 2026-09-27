import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.agent_workforce import AgentExecution
from app.models.evidence import Evidence
from app.models.project_state import ProjectState
from app.services.project_state_service import ProjectStateService

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    ContextBuilder for AI Workforce agents.
    Enforces the core rule:
    Do NOT pass the entire database blindly.
    Uses structured filtering (tenant, project, state version, relevant sections)
    before assembling targeted context for an agent.
    """

    def __init__(self, state_service: Optional[ProjectStateService] = None):
        self.state_service = state_service or ProjectStateService()

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
    ) -> Dict[str, Any]:
        """
        Assembles a bounded, structured context dictionary for the given agent.
        """
        # 1. Retrieve authoritative Project State
        state = self.state_service.get_or_create_state(project_id, db)
        state_dict = self.state_service._dump_state_dict(state)

        # 2. Extract sections based on filter or agent role
        filtered_state = {
            "project_id": state.project_id,
            "version": state.current_version,
            "title": state.title,
            "vision": state.vision,
        }

        # Selectively expose sections
        sections_to_include = section_filter or ["requirements", "decisions", "architecture", "agent_workflow", "constraints"]
        for sec in sections_to_include:
            if sec in state_dict:
                filtered_state[sec] = state_dict[sec]

        # 3. Retrieve relevant evidence (structured filtering by project and optional query)
        ev_query = db.query(Evidence).filter(
            Evidence.project_id == project_id,
        )
        if query:
            ev_query = ev_query.filter(Evidence.content.ilike(f"%{query}%"))
        evidence_items = ev_query.order_by(Evidence.created_at.desc()).limit(limit_evidence).all()

        formatted_evidence = [
            {
                "id": ev.id,
                "speaker": ev.actor_id or "Unknown",
                "text": ev.content,
                "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
                "source": ev.source,
            }
            for ev in evidence_items
        ]

        # 4. Retrieve relevant prior agent outputs
        prior_runs = (
            db.query(AgentExecution)
            .filter(
                AgentExecution.project_id == project_id,
                AgentExecution.tenant_id == tenant_id,
                AgentExecution.status == "completed",
            )
            .order_by(AgentExecution.created_at.desc())
            .limit(limit_prior_runs)
            .all()
        )

        formatted_prior_runs = [
            {
                "execution_id": r.id,
                "agent_id": r.agent_id,
                "output_type": r.output_type,
                "payload": json.loads(r.output_payload_json) if r.output_payload_json else {},
                "created_at": r.created_at.isoformat(),
            }
            for r in prior_runs
        ]

        context = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "state_version": state.current_version,
            "project_state": filtered_state,
            "evidence": formatted_evidence,
            "prior_agent_outputs": formatted_prior_runs,
            "assembled_for_agent": agent_id,
        }
        return context
