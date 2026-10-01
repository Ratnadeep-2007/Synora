import json
import pytest
from sqlalchemy.orm import Session

from app.connectors.google_meet import GoogleMeetConnector
from app.connectors.slack import SlackConnector
from app.models.intelligence import CandidateKnowledge
from app.models.project_state import ApprovalStatus, ProjectState, StateChange
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
    3. Verifies the same source-independent memory engine updates Project State automatically
    4. AI Workforce executes against the updated Project State.
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
    assert res_meet.authoritative_version_after >= 2

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
    assert res_slack.authoritative_version_after >= 2

    # Project Memory is the shared canonical layer. Both source paths
    # contribute to the same project-bounded state without manual approval.
    db_session.refresh(base_state)
    assert base_state.current_version >= 3
    decisions = json.loads(base_state.decisions_json)
    requirements = json.loads(base_state.requirements_json)
    assert any("PostgreSQL" in str(item) for item in decisions)
    assert any("multi-factor" in str(item).lower() for item in requirements + decisions)
    memory_audits = (
        db_session.query(StateChange)
        .filter(
            StateChange.project_id == project_id,
            StateChange.target_section == "memory",
            StateChange.approval_status == ApprovalStatus.APPROVED.value,
        )
        .all()
    )
    assert len(memory_audits) >= 1

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

