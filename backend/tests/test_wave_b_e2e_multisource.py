import pytest
from sqlalchemy.orm import Session

from app.connectors.google_meet import GoogleMeetConnector
from app.connectors.slack import SlackConnector
from app.models.intelligence import CandidateKnowledge
from app.models.project_state import ApprovalStatus, ProjectState
from app.services.ai_workforce import AIWorkforceService
from app.services.conflict_service import ConflictService
from app.services.ingestion_service import IngestionService
from app.services.meeting_intelligence import MeetingIntelligenceService
from app.services.pipeline_coordinator import PipelineCoordinator
from app.services.project_state_service import ProjectStateService


def test_end_to_end_multisource_pipeline(db_session: Session):
    """
    Final System Verification (Part 37):
    Executes the complete knowledge pipeline from:
    1. Google Meet transcript entry -> Normalized SourceEvent -> Evidence -> Intelligence -> Candidate -> Proposal & Conflict
    2. Slack conversation message -> Normalized SourceEvent -> Evidence -> SAME Intelligence -> Candidate -> Proposal & Conflict
    3. Verifies Authoritative Project State remains at v1 (Proposals do NOT mutate state)
    4. Human approval advances Authoritative Project State to v2
    5. AI Workforce executes against the updated Authoritative Project State (v2).
    """
    project_id = "proj_multisource_e2e"
    tenant_id = "tenant_enterprise"

    # Services
    ingestion = IngestionService()
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service)
    intelligence_service = MeetingIntelligenceService()
    coordinator = PipelineCoordinator(
        ingestion_service=ingestion,
        intelligence_service=intelligence_service,
        state_service=state_service,
        conflict_service=conflict_service,
    )

    # Establish baseline Authoritative Project State (v1)
    base_state = state_service.get_or_create_state(project_id, db_session)
    assert base_state.current_version == 1

    # ==========================================================
    # SOURCE 1: GOOGLE MEET
    # ==========================================================
    meet_connector = GoogleMeetConnector()
    raw_meet_entry = {
        "name": "spaces/meet_space_123/transcripts/tr_1/entries/ent_meet_001",
        "text": "Decision confirmed: We will implement PostgreSQL with row-level security for tenant isolation.",
        "languageCode": "en-US",
        "speaker": "Security Architect",
    }
    meet_event = meet_connector.normalize(
        raw_data=raw_meet_entry,
        event_type="transcript_entry",
        project_id=project_id,
        tenant_id=tenant_id,
        conference_id="conf_meet_1",
    )

    # Ingest and run pipeline for Source 1
    res_meet = coordinator.process_source_events(
        events=[meet_event],
        project_id=project_id,
        db=db_session,
        tenant_id=tenant_id,
        source_name="google_meet",
    )
    assert res_meet.success is True
    assert res_meet.events_ingested == 1
    assert res_meet.evidence_created == 1
    assert res_meet.authoritative_version_after == 1  # UNCHANGED!

    # ==========================================================
    # SOURCE 2: SLACK
    # ==========================================================
    slack_connector = SlackConnector()
    raw_slack_message = {
        "text": "Proposal: We should require multi-factor authentication (MFA) for all administrative logins.",
        "user": "U_SECURITY_LEAD",
        "ts": "1719999000.123456",
        "channel": "C_ARCHITECTURE",
        "team": "T_ENTERPRISE",
    }
    slack_event = slack_connector.normalize(
        raw_data=raw_slack_message,
        event_type="channel_message",
        project_id=project_id,
        tenant_id=tenant_id,
        channel="C_ARCHITECTURE",
    )

    # Ingest and run pipeline for Source 2 (Exact same intelligence engine!)
    res_slack = coordinator.process_source_events(
        events=[slack_event],
        project_id=project_id,
        db=db_session,
        tenant_id=tenant_id,
        source_name="slack",
    )
    assert res_slack.success is True
    assert res_slack.events_ingested == 1
    assert res_slack.evidence_created == 1
    assert res_slack.authoritative_version_after == 1  # UNCHANGED!

    # Verify Project State remains strictly at v1
    db_session.refresh(base_state)
    assert base_state.current_version == 1

    # ==========================================================
    # HUMAN REVIEW & AUTHORITATIVE STATE ADVANCEMENT (v1 -> v2)
    # ==========================================================
    # Human Architect inspects proposals and approves the Security decision
    from app.models.project_state import StateChange
    proposals = (
        db_session.query(StateChange)
        .filter(
            StateChange.project_id == project_id,
            StateChange.approval_status == ApprovalStatus.PROPOSED.value,
        )
        .all()
    )
    assert len(proposals) >= 1

    selected_proposal = proposals[0]
    approved_version = state_service.approve_state_change(
        change_id=selected_proposal.id,
        actor_id="human_security_officer",
        db=db_session,
        note="Approved architecture decision after cross-source verification.",
    )

    # Authoritative Project State successfully advanced to v2!
    assert approved_version.version_number == 2
    db_session.refresh(base_state)
    assert base_state.current_version == 2

    # ==========================================================
    # AI WORKFORCE EXECUTION AGAINST AUTHORITATIVE STATE (v2)
    # ==========================================================
    workforce = AIWorkforceService()
    agent_result = workforce.run_agent(
        agent_id="tech_agent",
        project_id=project_id,
        db=db_session,
    )
    assert agent_result.status == "completed"
    assert agent_result.project_state_version == 2
    assert agent_result.output_payload_json is not None

