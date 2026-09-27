import json
import pytest
from sqlalchemy.orm import Session

from app.models.conflict import Conflict, ConflictStatus, ConflictType
from app.models.intelligence import CandidateKnowledge, ClassificationEnum
from app.models.project_state import ProjectState, ProjectStateVersion, StateChange
from app.services.conflict_service import (
    ConflictService,
    PermissionDeniedError,
    StaleProposalError,
)
from app.services.project_state_service import ProjectStateService, StateTransitionError


def create_candidate(
    project_id: str,
    title: str,
    content: str,
    category: str = "proposal",
    classification: str = ClassificationEnum.PROPOSAL.value,
    evidence_ids: list = None,
) -> CandidateKnowledge:
    return CandidateKnowledge(
        project_id=project_id,
        category=category,
        classification=classification,
        title=title,
        content=content,
        confidence=0.9,
        evidence_ids_json=json.dumps(evidence_ids or ["ev_test_1"]),
        status="candidate",
    )


def test_no_conflict_and_false_conflict_avoidance(db_session: Session):
    """Verifies that non-conflicting proposals or incremental requirements do not trigger false conflicts."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_no_conf"
    state = state_service.get_or_create_state(proj_id, db_session)

    # 1. Normal incremental feature addition
    cand = create_candidate(
        project_id=proj_id,
        title="Add PDF Export",
        content="We should allow users to export their meeting summary to PDF format.",
        category="requirement_candidate",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)
    assert conflict is None, "False conflict generated for standard incremental requirement!"

    # 2. General non-contradictory question
    cand_q = create_candidate(
        project_id=proj_id,
        title="Frontend Architecture Question",
        content="Which CSS framework should we use for internal components?",
        category="question",
        classification=ClassificationEnum.QUESTION.value,
    )
    db_session.add(cand_q)
    db_session.commit()

    conflict_q = conflict_service.detect_conflicts_for_candidate(cand_q, db_session)
    assert conflict_q is None, "False conflict generated for a simple question!"


def test_workflow_architecture_conflict(db_session: Session):
    """Detects when an onboarding agent is proposed before BA in the agent workflow pipeline."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_wf_conf"
    state = state_service.get_or_create_state(proj_id, db_session)
    assert json.loads(state.agent_workflow_json) == ["BA", "Project", "Functional", "Tech", "Frappe"]

    cand = create_candidate(
        project_id=proj_id,
        title="Add Onboarding Agent",
        content="We should place an Onboarding agent before BA in the agent workflow pipeline.",
        category="proposal",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)
    assert conflict is not None
    assert conflict.type == ConflictType.WORKFLOW.value
    assert conflict.severity == "high"
    assert "Onboarding" in conflict.title
    assert conflict.status == ConflictStatus.OPEN.value
    assert conflict.state_change_id is not None


def test_direct_contradiction_decision_conflict(db_session: Session):
    """Detects direct contradiction against an established architectural decision (e.g. Postgres vs MongoDB)."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_dec_conf"
    state = state_service.get_or_create_state(proj_id, db_session)

    # Establish Postgres decision
    state.decisions_json = json.dumps([
        {"id": "dec_001", "text": "Use PostgreSQL as the primary relational database with pgvector."}
    ])
    db_session.commit()

    cand = create_candidate(
        project_id=proj_id,
        title="Switch to MongoDB",
        content="Let's migrate our database layer to MongoDB for document flexibility.",
        category="proposal",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)
    assert conflict is not None
    assert conflict.type == ConflictType.DECISION.value
    assert conflict.severity == "high"
    assert "Database" in conflict.title


def test_decision_reversal_conflict(db_session: Session):
    """Detects when a proposal attempts to reverse an explicitly confirmed negative decision."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_reversal_conf"
    state = state_service.get_or_create_state(proj_id, db_session)

    state.decisions_json = json.dumps([
        {"id": "dec_002", "text": "Do not build a custom web browser extension for MVP capture."}
    ])
    db_session.commit()

    cand = create_candidate(
        project_id=proj_id,
        title="Adopt Browser Extension",
        content="We decided to add a custom web browser extension for Chrome and Firefox.",
        category="decision_candidate",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)
    assert conflict is not None
    assert conflict.type == ConflictType.DECISION.value
    assert "Reversal" in conflict.title


def test_requirement_contradiction_conflict(db_session: Session):
    """Detects when a candidate directly contradicts a core requirement (e.g. offline support or security access)."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_req_conf"
    state = state_service.get_or_create_state(proj_id, db_session)

    state.requirements_json = json.dumps([
        {"id": "req_001", "content": "The application must provide offline mode for cached views."}
    ])
    db_session.commit()

    cand = create_candidate(
        project_id=proj_id,
        title="Remove Offline Mode",
        content="We should drop offline support to simplify our caching layer.",
        category="proposal",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)
    assert conflict is not None
    assert conflict.type == ConflictType.REQUIREMENT.value
    assert "Offline" in conflict.title


def test_scope_conflict_expansion(db_session: Session):
    """Detects out-of-scope expansion that contradicts established MVP constraints."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_scope_conf"
    state = state_service.get_or_create_state(proj_id, db_session)

    state.constraints_json = json.dumps([
        "Scope is strictly limited to MVP with Google Meet connector and lean single-tenant architecture."
    ])
    db_session.commit()

    cand = create_candidate(
        project_id=proj_id,
        title="Integrate Enterprise Multi-Cloud",
        content="Let's add multi-cloud infrastructure orchestration supporting AWS, Azure, and GCP simultaneously.",
        category="proposal",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)
    assert conflict is not None
    assert conflict.type == ConflictType.SCOPE.value
    assert "Scope" in conflict.title


def test_approve_conflict_human_review(db_session: Session):
    """Approving a conflict safely mutates authoritative Project State and advances version."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_approve_rev"
    state = state_service.get_or_create_state(proj_id, db_session)
    assert state.current_version == 1

    cand = create_candidate(
        project_id=proj_id,
        title="Add Onboarding",
        content="Add onboarding agent before BA in pipeline.",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)
    assert conflict.status == ConflictStatus.OPEN.value

    # Approve the workflow modification
    res = conflict_service.approve_conflict(
        conflict_id=conflict.id,
        actor_id="lead_reviewer",
        db=db_session,
        note="Approved by architecture committee.",
    )

    assert res["new_version"] == 2
    db_session.refresh(conflict)
    db_session.refresh(state)

    assert conflict.status == ConflictStatus.APPROVED.value
    assert conflict.resolved_by == "lead_reviewer"
    assert state.current_version == 2
    # Verify Onboarding was added to workflow
    wf = json.loads(state.agent_workflow_json)
    assert wf[0] == "Onboarding"


def test_reject_conflict_human_review(db_session: Session):
    """Rejecting a conflict preserves authoritative Project State intact."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_reject_rev"
    state = state_service.get_or_create_state(proj_id, db_session)
    assert state.current_version == 1

    cand = create_candidate(
        project_id=proj_id,
        title="Add Onboarding",
        content="Add onboarding agent before BA in pipeline.",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)

    rejected = conflict_service.reject_conflict(
        conflict_id=conflict.id,
        actor_id="tech_lead",
        reason="Does not fit current quarterly goals.",
        db=db_session,
    )

    assert rejected.status == ConflictStatus.REJECTED.value
    db_session.refresh(state)
    # State remains v1 and untouched
    assert state.current_version == 1
    wf = json.loads(state.agent_workflow_json)
    assert wf[0] == "BA"


def test_mark_unresolved_human_review(db_session: Session):
    """Marking a conflict unresolved preserves state while keeping proposal unresolved for future deliberation."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_unresolved_rev"
    state = state_service.get_or_create_state(proj_id, db_session)

    cand = create_candidate(
        project_id=proj_id,
        title="Add Onboarding",
        content="Add onboarding agent before BA in pipeline.",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)

    unresolved = conflict_service.mark_unresolved(
        conflict_id=conflict.id,
        actor_id="pm",
        db=db_session,
        note="Need feedback from customer success lead first.",
    )

    assert unresolved.status == ConflictStatus.UNRESOLVED.value
    db_session.refresh(state)
    assert state.current_version == 1


def test_stale_proposal_detection(db_session: Session):
    """Rejects approving a conflict if Project State was modified after the conflict was proposed."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_stale_test"
    state = state_service.get_or_create_state(proj_id, db_session)
    assert state.current_version == 1

    cand = create_candidate(
        project_id=proj_id,
        title="Add Onboarding",
        content="Add onboarding agent before BA in pipeline.",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)
    assert conflict.state_change.state_version_before == 1

    # Advance Project State in the background (e.g. another proposal was approved)
    state.current_version = 2
    db_session.commit()

    # Now attempt to approve the stale conflict
    with pytest.raises(StaleProposalError) as exc_info:
        conflict_service.approve_conflict(
            conflict_id=conflict.id,
            actor_id="reviewer",
            db=db_session,
        )
    assert "Stale proposal detected" in str(exc_info.value)


def test_concurrent_approval_guard(db_session: Session):
    """Prevent double approval or approving an already resolved conflict."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_concurrent_rev"
    state = state_service.get_or_create_state(proj_id, db_session)

    cand = create_candidate(
        project_id=proj_id,
        title="Add Onboarding",
        content="Add onboarding agent before BA in pipeline.",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(cand, db_session)

    # First approval succeeds
    conflict_service.approve_conflict(conflict_id=conflict.id, actor_id="user_1", db=db_session)

    # Second approval attempt must raise StateTransitionError
    with pytest.raises(StateTransitionError) as exc_info:
        conflict_service.approve_conflict(conflict_id=conflict.id, actor_id="user_2", db=db_session)
    assert "Cannot approve conflict in 'approved' status" in str(exc_info.value)


def test_cross_tenant_conflict_access(db_session: Session):
    """Rejects cross-tenant access and mutation attempts on conflicts."""
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)

    proj_id = "proj_tenant_iso"
    state = state_service.get_or_create_state(proj_id, db_session)

    cand = create_candidate(
        project_id=proj_id,
        title="Add Onboarding",
        content="Add onboarding agent before BA in pipeline.",
    )
    db_session.add(cand)
    db_session.commit()

    conflict = conflict_service.detect_conflicts_for_candidate(
        candidate=cand,
        db=db_session,
        tenant_id="tenant_alpha",
    )
    assert conflict.tenant_id == "tenant_alpha"

    # Attacker from tenant_beta tries to view or approve conflict
    with pytest.raises(PermissionDeniedError):
        conflict_service.get_conflict_by_id(conflict.id, db=db_session, tenant_id="tenant_beta")

    with pytest.raises(PermissionDeniedError):
        conflict_service.approve_conflict(
            conflict_id=conflict.id,
            actor_id="hacker",
            db=db_session,
            tenant_id="tenant_beta",
        )
