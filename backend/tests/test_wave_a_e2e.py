from datetime import datetime, timezone
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.project_state import ProjectState
from app.services.ai_workforce import AIWorkforceService
from app.services.conflict_service import ConflictService
from app.services.context_builder import ContextBuilder
from app.services.ingestion_service import IngestionService
from app.services.meeting_intelligence import MeetingIntelligenceService
from app.services.pipeline_coordinator import PipelineCoordinator
from app.services.project_state_service import ProjectStateService


def test_wave_a_end_to_end_flow(db_session: Session, client: TestClient):
    """
    MASTER WAVE A INTEGRATION TEST:
    Google Meet
    ↓
    Transcript
    ↓
    Evidence
    ↓
    Meeting Intelligence
    ↓
    Candidate Proposal
    ↓
    Conflict Detection
    ↓
    Human Approval
    ↓
    Project State vN -> vN+1
    ↓
    BA Agent Execution
    ↓
    Structured Agent Output
    """
    proj_id = "proj_wave_a_master"
    meet_id = "meet_wave_a_001"
    user_id = "usr_lead_pm"

    # Step 1: Seed real Google Meet conference with transcripts
    meeting = Meeting(
        id=meet_id,
        user_id=user_id,
        project_id=proj_id,
        provider="google",
        provider_conference_id="conf_spaces/wave_a_space",
        title="Sync Meeting: AI Workforce MVP Architecture",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
    )
    db_session.add(meeting)

    p1 = Participant(id=f"part_{meet_id}_1", meeting_id=meet_id, provider_participant_id="users/devin", display_name="Devin Lead")
    p2 = Participant(id=f"part_{meet_id}_2", meeting_id=meet_id, provider_participant_id="users/sec", display_name="Security Architect")
    p3 = Participant(id=f"part_{meet_id}_3", meeting_id=meet_id, provider_participant_id="users/sam", display_name="Sam PM")
    db_session.add_all([p1, p2, p3])

    transcript = Transcript(
        id=f"tr_{meet_id}",
        meeting_id=meet_id,
        provider="google",
        provider_transcript_id="transcripts/t_wave_a",
    )
    db_session.add(transcript)

    e1 = TranscriptEntry(
        id=f"entry_{meet_id}_1",
        transcript_id=transcript.id,
        provider="google",
        provider_entry_id="entries/1",
        participant_id=p1.id,
        text="We could add an onboarding agent before BA in the workflow pipeline.",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
    )
    e2 = TranscriptEntry(
        id=f"entry_{meet_id}_2",
        transcript_id=transcript.id,
        provider="google",
        provider_entry_id="entries/2",
        participant_id=p2.id,
        text="One requirement is that the onboarding agent must have read-only workspace access.",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
    )
    e3 = TranscriptEntry(
        id=f"entry_{meet_id}_3",
        transcript_id=transcript.id,
        provider="google",
        provider_entry_id="entries/3",
        participant_id=p3.id,
        text="Okay, let's do it and place the onboarding agent before BA.",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
    )
    db_session.add_all([e1, e2, e3])
    db_session.commit()

    # Step 2: Run End-to-End Pipeline
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)
    coordinator = PipelineCoordinator(
        state_service=state_service,
        conflict_service=conflict_service,
    )

    pipeline_res = coordinator.process_meeting(
        meeting_id=meet_id,
        project_id=proj_id,
        db=db_session,
        actor_id=user_id,
    )

    assert pipeline_res.success is True
    assert pipeline_res.evidence_created == 3
    assert pipeline_res.candidates_extracted == 3
    assert pipeline_res.conflicts_detected >= 1
    # Authoritative State MUST NOT be silently modified!
    assert pipeline_res.authoritative_version_before == 1
    assert pipeline_res.authoritative_version_after == 1

    # Step 3: Verify Conflict Center via API
    conflicts_resp = client.get(f"/projects/{proj_id}/conflicts", headers={"X-User-ID": user_id})
    assert conflicts_resp.status_code == 200
    conflicts_data = conflicts_resp.json()
    assert len(conflicts_data) >= 1
    wf_conflict = next(c for c in conflicts_data if c["type"] == "workflow")
    assert wf_conflict["status"] == "open"
    assert "Onboarding" in wf_conflict["title"]

    # Step 4: Human Review — Approve the workflow conflict
    review_resp = client.post(
        f"/projects/{proj_id}/conflicts/{wf_conflict['id']}/review",
        json={
            "action": "approve",
            "actor_id": user_id,
            "note": "Approved by PM after reviewing security constraints.",
        },
        headers={"X-User-ID": user_id},
    )
    assert review_resp.status_code == 200
    review_data = review_resp.json()
    assert review_data["conflict"]["status"] == "approved"
    assert review_data["project_state_version"] == 2

    # Step 5: Verify Project State transitioned to v2 with updated agent workflow
    state_resp = client.get(f"/projects/{proj_id}/state", headers={"X-User-ID": user_id})
    assert state_resp.status_code == 200
    state_data = state_resp.json()
    assert state_data["current_version"] == 2
    assert state_data["agent_workflow"][0] == "Onboarding"
    assert state_data["agent_workflow"][1] == "BA"

    # Step 6: Trigger BA Agent using the new authoritative State v2
    agent_run_resp = client.post(
        f"/projects/{proj_id}/agents/ba_agent/run",
        json={"task_description": "Analyze onboarding handoff requirements for v2 pipeline."},
        headers={"X-User-ID": user_id},
    )
    assert agent_run_resp.status_code == 200
    agent_run_data = agent_run_resp.json()
    execution = agent_run_data["execution"]
    assert execution["agent_id"] == "ba_agent"
    assert execution["project_state_version"] == 2
    assert execution["status"] == "completed"
    assert execution["output_payload"]["derived_from_state_version"] == 2
    assert len(execution["output_payload"]["evidence_sources"]) >= 1

    # Step 7: Verify Workforce API status reflection
    agents_list_resp = client.get(f"/projects/{proj_id}/agents", headers={"X-User-ID": user_id})
    assert agents_list_resp.status_code == 200
    agents_list = agents_list_resp.json()
    ba_meta = next(a for a in agents_list if a["agent_id"] == "ba_agent")
    assert ba_meta["status"] == "ready"
    assert ba_meta["current_project_state_version"] == 2
    assert ba_meta["current_task"] is not None

    # Step 8: Verify executions history
    history_resp = client.get(f"/projects/{proj_id}/agents/ba_agent/runs", headers={"X-User-ID": user_id})
    assert history_resp.status_code == 200
    history_data = history_resp.json()
    assert len(history_data) >= 1
    assert history_data[0]["id"] == execution["id"]
