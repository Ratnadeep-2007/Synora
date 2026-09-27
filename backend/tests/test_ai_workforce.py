import json
import pytest
from sqlalchemy.orm import Session

from app.models.agent_workforce import AgentExecution
from app.models.project_state import ProjectState, ProjectStateVersion
from app.services.ai_workforce import (
    AIWorkforceService,
    AgentOutputValidationError,
    AgentPermissionError,
)
from app.services.context_builder import ContextBuilder
from app.services.project_state_service import ProjectStateService


def test_agent_reads_correct_project_state_version(db_session: Session):
    """Verifies that an agent run consumes and logs the exact current authoritative Project State version."""
    state_service = ProjectStateService()
    context_builder = ContextBuilder(state_service)
    workforce_service = AIWorkforceService(context_builder, state_service)

    proj_id = "proj_wf_ver_test"
    state = state_service.get_or_create_state(proj_id, db_session)
    # Manually advance to v3 for testing version tracking
    state.current_version = 3
    db_session.commit()

    exec_record = workforce_service.run_agent(
        agent_id="ba_agent",
        project_id=proj_id,
        db=db_session,
    )

    assert exec_record.status == "completed"
    assert exec_record.project_state_version == 3
    payload = json.loads(exec_record.output_payload_json)
    assert payload["derived_from_state_version"] == 3


def test_agent_tenant_and_project_isolation(db_session: Session):
    """Verifies that an agent strictly receives context filtered to its own tenant and project."""
    state_service = ProjectStateService()
    context_builder = ContextBuilder(state_service)
    workforce_service = AIWorkforceService(context_builder, state_service)

    # Project A
    state_a = state_service.get_or_create_state("proj_tenant_A", db_session)
    state_a.vision = "Confidential Vision for Project Alpha."
    db_session.commit()

    # Context built for Project B
    context_b = context_builder.build_agent_context(
        project_id="proj_tenant_B",
        agent_id="ba_agent",
        db=db_session,
        tenant_id="tenant_bravo",
    )

    assert context_b["project_id"] == "proj_tenant_B"
    assert context_b["tenant_id"] == "tenant_bravo"
    assert "Confidential Vision for Project Alpha" not in str(context_b)


def test_agent_cannot_approve_own_proposals(db_session: Session):
    """Verifies that an agent possesses no direct approval authority over project state."""
    state_service = ProjectStateService()
    context_builder = ContextBuilder(state_service)
    workforce_service = AIWorkforceService(context_builder, state_service)

    tech_meta = workforce_service.AGENT_DEFINITIONS["tech_agent"]
    assert "approve_own_proposals" in tech_meta["permissions_prohibited"]
    assert "approve_state_changes" in tech_meta["permissions_prohibited"]
    assert "mutate_project_state" in tech_meta["permissions_prohibited"]


def test_agent_output_validation_success(db_session: Session):
    """Verifies that valid structured agent output passes schema validation."""
    state_service = ProjectStateService()
    context_builder = ContextBuilder(state_service)
    workforce_service = AIWorkforceService(context_builder, state_service)

    valid_payload = {
        "title": "Valid Proposal",
        "summary": "Valid summary of analysis",
        "derived_from_state_version": 1,
    }
    # Should not raise exception
    workforce_service._validate_agent_output("analysis", valid_payload)


def test_agent_malformed_output_rejected(db_session: Session):
    """Verifies that malformed or ungrounded agent output is strictly rejected."""
    state_service = ProjectStateService()
    context_builder = ContextBuilder(state_service)
    workforce_service = AIWorkforceService(context_builder, state_service)

    # Missing required 'summary' and 'title'
    with pytest.raises(AgentOutputValidationError):
        workforce_service._validate_agent_output("analysis", {"derived_from_state_version": 1})

    # Missing required 'derived_from_state_version'
    with pytest.raises(AgentOutputValidationError):
        workforce_service._validate_agent_output("analysis", {"summary": "Missing version reference"})


def test_failed_execution_does_not_corrupt_project_state(db_session: Session):
    """Verifies that a failure during agent execution logs an error run and leaves state untouched."""
    state_service = ProjectStateService()
    context_builder = ContextBuilder(state_service)
    workforce_service = AIWorkforceService(context_builder, state_service)

    proj_id = "proj_fail_test"
    state = state_service.get_or_create_state(proj_id, db_session)
    v_initial = state.current_version

    # Trigger run with invalid agent
    with pytest.raises(AgentPermissionError):
        workforce_service.run_agent(
            agent_id="non_existent_agent",
            project_id=proj_id,
            db=db_session,
        )

    db_session.refresh(state)
    assert state.current_version == v_initial, "ProjectState was mutated during failed execution!"
