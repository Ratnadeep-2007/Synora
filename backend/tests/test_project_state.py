"""
Unit & Integration Tests for Checkpoint 3: Project State (Phase 5).
"""
import json
import pytest
from sqlalchemy.orm import Session

from app.models.intelligence import CandidateKnowledge, ClassificationEnum
from app.models.project_state import (
    ApprovalStatus,
    ProjectState,
    ProjectStateVersion,
    StateChange,
)
from app.services.project_state_service import (
    ConcurrencyError,
    ProjectStateService,
    StateTransitionError,
)


@pytest.fixture
def state_service() -> ProjectStateService:
    return ProjectStateService()


@pytest.fixture
def sample_candidate(db_session: Session) -> CandidateKnowledge:
    candidate = CandidateKnowledge(
        id="cand_test_onboarding",
        project_id="proj_state_test",
        category="proposal",
        classification=ClassificationEnum.PROPOSAL.value,
        title="Add Onboarding Agent before BA",
        content="We should add a general onboarding agent before BA in the workflow.",
        confidence=0.91,
        evidence_ids_json=json.dumps(["ev_101", "ev_102"]),
        status="candidate",
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def test_create_initial_state_baseline(state_service: ProjectStateService, db_session: Session):
    """Creating initial state initializes Version 1 and records baseline snapshot."""
    state = state_service.get_or_create_state("proj_init_test", db_session, title="Test Project")
    assert state.current_version == 1
    assert "BA" in json.loads(state.agent_workflow_json)

    v1_record = (
        db_session.query(ProjectStateVersion)
        .filter_by(project_id="proj_init_test", version_number=1)
        .first()
    )
    assert v1_record is not None
    assert "Initial baseline" in v1_record.reason


def test_candidate_proposal_does_not_mutate_state(
    state_service: ProjectStateService,
    sample_candidate: CandidateKnowledge,
    db_session: Session,
):
    """
    CRITICAL RULE: Candidate Knowledge is NOT Authoritative Project State.
    Proposing a change creates a StateChange in 'proposed' status,
    leaving authoritative state untouched at Version 1.
    """
    state_before = state_service.get_or_create_state(sample_candidate.project_id, db_session)
    assert state_before.current_version == 1
    workflow_before = json.loads(state_before.agent_workflow_json)
    assert "Onboarding" not in workflow_before

    # Propose change
    change = state_service.propose_change_from_candidate(sample_candidate, db_session)
    assert change.approval_status == ApprovalStatus.PROPOSED.value
    assert change.state_version_before == 1

    # Verify authoritative state is COMPLETELY UNTOUCHED
    db_session.refresh(state_before)
    assert state_before.current_version == 1
    assert json.loads(state_before.agent_workflow_json) == workflow_before


def test_approve_state_change_version_increment(
    state_service: ProjectStateService,
    sample_candidate: CandidateKnowledge,
    db_session: Session,
):
    """Approving a proposed change applies mutation, increments version (v1 -> v2), and creates snapshot."""
    state = state_service.get_or_create_state(sample_candidate.project_id, db_session)
    change = state_service.propose_change_from_candidate(sample_candidate, db_session)

    version_record = state_service.approve_state_change(
        change_id=change.id,
        actor_id="usr_lead_architect",
        db=db_session,
        note="Approved during architecture review.",
    )

    assert version_record.version_number == 2
    assert state.current_version == 2

    # Check that Onboarding was inserted into the agent workflow
    workflow_after = json.loads(state.agent_workflow_json)
    assert workflow_after[0] == "Onboarding"

    # Verify change and candidate status
    db_session.refresh(change)
    db_session.refresh(sample_candidate)
    assert change.approval_status == ApprovalStatus.APPROVED.value
    assert change.state_version_after == 2
    assert sample_candidate.status == "approved"


def test_optimistic_concurrency_protection(
    state_service: ProjectStateService,
    sample_candidate: CandidateKnowledge,
    db_session: Session,
):
    """
    If state evolved (e.g. from v1 to v2) while a proposal was pending against v1,
    approving that proposal MUST fail with ConcurrencyError.
    """
    state = state_service.get_or_create_state(sample_candidate.project_id, db_session)
    change = state_service.propose_change_from_candidate(sample_candidate, db_session)
    assert change.state_version_before == 1

    # Simulate concurrent update that advanced state to v2
    state.current_version = 2
    db_session.commit()

    with pytest.raises(ConcurrencyError, match="Optimistic concurrency violation"):
        state_service.approve_state_change(change.id, actor_id="usr_other", db=db_session)


def test_reject_state_change(
    state_service: ProjectStateService,
    sample_candidate: CandidateKnowledge,
    db_session: Session,
):
    """Explicitly rejecting a change updates status and leaves state unchanged."""
    state = state_service.get_or_create_state(sample_candidate.project_id, db_session)
    change = state_service.propose_change_from_candidate(sample_candidate, db_session)

    rejected_change = state_service.reject_state_change(
        change_id=change.id,
        actor_id="usr_product_manager",
        reason="Does not align with Q4 roadmap.",
        db=db_session,
    )

    assert rejected_change.approval_status == ApprovalStatus.REJECTED.value
    assert "Q4 roadmap" in rejected_change.reason
    assert state.current_version == 1

    # Cannot approve a rejected change
    with pytest.raises(StateTransitionError, match="must be 'proposed'"):
        state_service.approve_state_change(change.id, actor_id="usr_admin", db=db_session)


def test_state_rollback_to_earlier_version(
    state_service: ProjectStateService,
    sample_candidate: CandidateKnowledge,
    db_session: Session,
):
    """
    Rollback restores state from a target version, creates an explicit new version (v3),
    and records an audit StateChange. History is never destroyed.
    """
    proj_id = "proj_rollback_test"
    state = state_service.get_or_create_state(proj_id, db_session)
    assert state.current_version == 1  # Baseline v1

    # Propose and approve change to create v2
    cand = CandidateKnowledge(
        project_id=proj_id,
        category="requirement_candidate",
        classification="Requirement",
        title="Sample Requirement",
        content="Must provide business context",
        evidence_ids_json=json.dumps(["ev_1"]),
    )
    db_session.add(cand)
    db_session.commit()

    change = state_service.propose_change_from_candidate(cand, db_session)
    state_service.approve_state_change(change.id, actor_id="usr_lead", db=db_session)
    assert state.current_version == 2
    assert len(json.loads(state.requirements_json)) == 1

    # Now rollback to v1!
    new_version_record = state_service.rollback_to_version(
        project_id=proj_id,
        target_version=1,
        actor_id="usr_superadmin",
        reason="Emergency revert to clean v1 baseline",
        db=db_session,
    )

    # Version advances to 3 (restoring v1 content)
    assert new_version_record.version_number == 3
    assert state.current_version == 3
    # Requirements from v2 should be gone in restored state
    assert len(json.loads(state.requirements_json)) == 0
