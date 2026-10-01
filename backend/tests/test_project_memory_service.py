import json

from app.models.intelligence import CandidateKnowledge
from app.models.project_state import ProjectState
from app.services.project_memory_service import ProjectMemoryService


def test_project_memory_is_project_bounded_and_automatic(db_session):
    state = ProjectState(
        project_id="proj_memory_a",
        current_version=1,
        title="Memory A",
        vision="A",
        requirements_json="[]",
        architecture_json="[]",
        decisions_json="[]",
        constraints_json="[]",
        assumptions_json="[]",
        open_questions_json="[]",
    )
    db_session.add(state)
    db_session.flush()

    candidate = CandidateKnowledge(
        id="cand_mem_a",
        project_id="proj_memory_a",
        category="decision_candidate",
        classification="Decision",
        title="Use PostgreSQL",
        content="Store project knowledge in PostgreSQL.",
        confidence=0.95,
        evidence_ids_json=json.dumps(["ev_mem_a"]),
        status="candidate",
    )
    wrong_project = CandidateKnowledge(
        id="cand_mem_b",
        project_id="proj_memory_b",
        category="decision_candidate",
        classification="Decision",
        title="Wrong project",
        content="Must never cross the project boundary.",
        confidence=0.95,
        evidence_ids_json=json.dumps(["ev_mem_b"]),
        status="candidate",
    )
    db_session.add_all([candidate, wrong_project])
    db_session.commit()

    result = ProjectMemoryService().apply_candidates(
        project_id="proj_memory_a",
        candidates=[candidate, wrong_project],
        db=db_session,
        source="whatsapp",
        actor_id="synora_agent",
    )

    db_session.refresh(state)
    decisions = json.loads(state.decisions_json)

    assert result["applied"] == 1
    assert result["skipped"] == 1
    assert state.current_version == 2
    assert len(decisions) == 1
    assert decisions[0]["title"] == "Use PostgreSQL"
    assert decisions[0]["evidence_ids"] == ["ev_mem_a"]
    assert candidate.status == "approved"
    assert wrong_project.status == "candidate"
