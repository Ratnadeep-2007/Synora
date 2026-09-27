"""
End-to-End Pipeline & API Integration Tests for Combined Phase 3-5.
Tests:
- Google Meet transcript -> Source Events -> Evidence -> Meeting Intelligence
  -> Candidate Knowledge -> Validation -> Project State Proposals
- Proof that Candidate Proposals do NOT mutate Authoritative Project State
- Approval workflow advancing state version
- API endpoints for Project State, Evidence, Knowledge, and Proposals
"""
from datetime import datetime, timezone
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.project_state import ProjectState, StateChange
from app.models.user import User
from app.services.pipeline_coordinator import PipelineCoordinator


@pytest.fixture
def prd_sample_meeting(db_session: Session, test_user: User) -> Meeting:
    """
    Creates a meeting containing the exact dialogue from PRD Section 14 / User Prompt Part L:
    1. 'We should add a general onboarding agent.'
    2. 'BA is currently the first processing agent.'
    3. 'Let's discuss whether onboarding should come before BA.'
    4. 'One requirement is that the user provides business context.'
    """
    meeting = Meeting(
        id="mtg_prd_pipeline_demo",
        project_id="proj_pipeline_test",
        user_id=test_user.id,
        provider="google",
        provider_conference_id="conf_prd_pipeline_demo",
        title="Product Architecture Review #42",
        status="ENDED",
    )
    db_session.add(meeting)
    db_session.commit()

    part_ceo = Participant(
        id="part_ceo",
        meeting_id=meeting.id,
        provider_participant_id="conf_prd_pipeline_demo/participants/p_ceo",
        display_name="CEO (Speaker A)",
    )
    part_arch = Participant(
        id="part_arch",
        meeting_id=meeting.id,
        provider_participant_id="conf_prd_pipeline_demo/participants/p_arch",
        display_name="Lead Architect (Speaker B)",
    )
    transcript = Transcript(
        id="trsc_demo",
        meeting_id=meeting.id,
        provider="google",
        provider_transcript_id="conf_prd_pipeline_demo/transcripts/tr_1",
        state="ENDED",
    )
    db_session.add_all([part_ceo, part_arch, transcript])
    db_session.commit()

    dialogue = [
        ("tent_01", part_ceo.id, "We should add a general onboarding agent before BA in the workflow.", "10:05:10"),
        ("tent_02", part_arch.id, "BA is currently the first processing agent.", "10:05:14"),
        ("tent_03", part_ceo.id, "Let's discuss whether onboarding should come before BA tomorrow.", "10:05:18"),
        ("tent_04", part_arch.id, "One requirement is that the user provides business context.", "10:05:22"),
    ]

    for tent_id, speaker_id, text, ts in dialogue:
        e = TranscriptEntry(
            id=tent_id,
            transcript_id=transcript.id,
            provider="google",
            provider_entry_id=f"entry_{tent_id}",
            participant_id=speaker_id,
            text=text,
            language_code="en-US",
            start_time=datetime(2026, 9, 24, 10, 5, 10, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 24, 10, 5, 25, tzinfo=timezone.utc),
        )
        db_session.add(e)

    db_session.commit()
    db_session.refresh(meeting)
    return meeting


def test_pipeline_coordinator_execution(
    prd_sample_meeting: Meeting,
    db_session: Session,
):
    """
    Executes full pipeline:
    Transcript -> Source Events -> Evidence -> Intelligence -> Candidates -> Proposals.
    Verifies that Project State remains at Version 1.
    """
    coordinator = PipelineCoordinator()
    result = coordinator.process_meeting(
        meeting_id=prd_sample_meeting.id,
        project_id=prd_sample_meeting.project_id,
        db=db_session,
    )

    assert result.success is True
    assert result.events_ingested == 4
    assert result.evidence_created == 4
    assert result.candidates_extracted >= 3
    assert result.proposals_created >= 2

    # CRITICAL INVARIANT: Authoritative Project State is NOT modified by the pipeline!
    assert result.authoritative_version_before == 1
    assert result.authoritative_version_after == 1

    state = db_session.query(ProjectState).filter_by(project_id=prd_sample_meeting.project_id).first()
    assert state.current_version == 1
    workflow = json.loads(state.agent_workflow_json)
    assert workflow[0] == "BA", "Workflow should not have changed before approval!"


def test_api_pipeline_and_approval_workflow(
    client: TestClient,
    prd_sample_meeting: Meeting,
    test_user: User,
):
    """
    Full HTTP API journey:
    1. GET /projects/{id}/state -> baseline v1
    2. POST /projects/{id}/meetings/{id}/process -> executes pipeline
    3. GET /projects/{id}/state -> still v1!
    4. GET /projects/{id}/state/proposals -> inspect pending proposals
    5. POST /projects/{id}/state/proposals/{proposal_id}/approve -> approves change
    6. GET /projects/{id}/state -> now v2 with Onboarding in workflow!
    7. GET /projects/{id}/state/history -> inspect version audit trail
    """
    headers = {"X-User-ID": test_user.id}
    proj_id = prd_sample_meeting.project_id

    # 1. Inspect initial state (v1)
    res_state1 = client.get(f"/projects/{proj_id}/state", headers=headers)
    assert res_state1.status_code == 200
    state1 = res_state1.json()
    assert state1["current_version"] == 1
    assert state1["agent_workflow"][0] == "BA"

    # 2. Trigger pipeline processing via API
    res_proc = client.post(
        f"/projects/{proj_id}/meetings/{prd_sample_meeting.id}/process",
        headers=headers,
    )
    assert res_proc.status_code == 200
    proc_data = res_proc.json()
    assert proc_data["success"] is True
    assert proc_data["evidence_created"] == 4
    assert proc_data["authoritative_version_after"] == 1

    # 3. Verify state is STILL v1
    res_state2 = client.get(f"/projects/{proj_id}/state", headers=headers)
    assert res_state2.status_code == 200
    assert res_state2.json()["current_version"] == 1

    # 4. List evidence & candidate knowledge via API
    res_ev = client.get(f"/projects/{proj_id}/evidence", headers=headers)
    assert res_ev.status_code == 200
    evidence_items = res_ev.json()
    assert len(evidence_items) == 4
    assert any("onboarding agent" in e["content"] for e in evidence_items)

    res_know = client.get(f"/projects/{proj_id}/knowledge", headers=headers)
    assert res_know.status_code == 200
    candidates = res_know.json()
    assert len(candidates) >= 3

    # 5. List pending proposals
    res_props = client.get(f"/projects/{proj_id}/state/proposals", headers=headers)
    assert res_props.status_code == 200
    proposals = res_props.json()
    assert len(proposals) >= 2

    # Find the agent_workflow proposal (Onboarding)
    workflow_prop = next((p for p in proposals if p["target_section"] == "agent_workflow"), proposals[0])
    prop_id = workflow_prop["id"]

    # 6. Explicitly APPROVE proposal
    res_appr = client.post(
        f"/projects/{proj_id}/state/proposals/{prop_id}/approve",
        headers=headers,
        json={"actor_id": "usr_founder", "note": "Approved during executive sync."},
    )
    assert res_appr.status_code == 200
    appr_data = res_appr.json()
    assert appr_data["version_number"] == 2
    assert appr_data["actor_id"] == "usr_founder"

    # 7. Verify state is now ADVANCED to v2!
    res_state3 = client.get(f"/projects/{proj_id}/state", headers=headers)
    assert res_state3.status_code == 200
    state3 = res_state3.json()
    assert state3["current_version"] == 2
    assert state3["agent_workflow"][0] == "Onboarding"

    # 8. Check history endpoint
    res_hist = client.get(f"/projects/{proj_id}/state/history", headers=headers)
    assert res_hist.status_code == 200
    history = res_hist.json()
    assert len(history) == 2  # v2 and v1
    assert history[0]["version_number"] == 2
    assert history[1]["version_number"] == 1


def test_proposal_rejection_workflow(
    client: TestClient,
    prd_sample_meeting: Meeting,
    test_user: User,
    db_session: Session,
):
    """Verify rejecting a proposal marks it rejected and does NOT advance project state."""
    headers = {"X-User-ID": test_user.id}
    proj_id = prd_sample_meeting.project_id

    # Execute pipeline to generate proposals
    client.post(f"/projects/{proj_id}/meetings/{prd_sample_meeting.id}/process", headers=headers)

    res_props = client.get(f"/projects/{proj_id}/state/proposals", headers=headers)
    proposals = res_props.json()
    assert len(proposals) > 0
    prop_to_reject = proposals[0]["id"]

    # Reject proposal
    res_rej = client.post(
        f"/projects/{proj_id}/state/proposals/{prop_to_reject}/reject",
        headers=headers,
        json={"actor_id": "usr_evaluator", "reason": "Not feasible in Phase 1."},
    )
    assert res_rej.status_code == 200
    rej_data = res_rej.json()
    assert rej_data["approval_status"] == "rejected"
    assert "Not feasible" in rej_data["reason"]

    # State remains unchanged
    res_state = client.get(f"/projects/{proj_id}/state", headers=headers)
    assert res_state.json()["current_version"] == 1


def test_rollback_endpoint(
    client: TestClient,
    prd_sample_meeting: Meeting,
    test_user: User,
):
    """Test POST /projects/{id}/state/rollback endpoint restores earlier state snapshot."""
    headers = {"X-User-ID": test_user.id}
    proj_id = prd_sample_meeting.project_id

    # Trigger pipeline and approve proposal to get to v2
    client.post(f"/projects/{proj_id}/meetings/{prd_sample_meeting.id}/process", headers=headers)
    proposals = client.get(f"/projects/{proj_id}/state/proposals", headers=headers).json()
    workflow_prop = next((p for p in proposals if p["target_section"] == "agent_workflow"), proposals[0])

    client.post(
        f"/projects/{proj_id}/state/proposals/{workflow_prop['id']}/approve",
        headers=headers,
        json={"actor_id": "usr_founder"},
    )

    # State is now v2
    assert client.get(f"/projects/{proj_id}/state", headers=headers).json()["current_version"] == 2

    # Rollback to v1
    res_rb = client.post(
        f"/projects/{proj_id}/state/rollback",
        headers=headers,
        json={"target_version": 1, "actor_id": "usr_admin", "reason": "Reverting experiment"},
    )
    assert res_rb.status_code == 200
    rb_data = res_rb.json()
    # Advances version to 3 with v1 content
    assert rb_data["version_number"] == 3

    current_state = client.get(f"/projects/{proj_id}/state", headers=headers).json()
    assert current_state["current_version"] == 3
    # Original baseline workflow restored (Onboarding removed)
    assert current_state["agent_workflow"][0] == "BA"
