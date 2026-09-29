from datetime import datetime, timezone
import json
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.connectors.google_meet import GoogleMeetConnector
from app.connectors.slack import SlackConnector
from app.connectors.excalidraw import ExcalidrawConnector
from app.models.agent_workforce import AgentExecution
from app.models.audit_log import AuditLog
from app.models.conflict import Conflict, ConflictStatus
from app.models.evidence import Evidence
from app.models.excalidraw import ExcalidrawArtifact, ExcalidrawProposal, ExcalidrawProposalStatus
from app.models.project_state import ApprovalStatus, ChangeOperation, ProjectState, StateChange
from app.models.source_event import SourceEvent
from app.schemas.excalidraw import ExcalidrawIngestRequest
from app.schemas.source_event import SourceEventCreate
from app.services.ai_workforce import AIWorkforceService
from app.services.audit_service import AuditService
from app.services.conflict_service import ConflictService
from app.services.context_builder import ContextBuilder
from app.services.excalidraw_service import ExcalidrawService
from app.services.ingestion_service import IngestionService
from app.services.project_state_service import ProjectStateService


def test_golden_end_to_end_scenario(db_session: Session, client: TestClient):
    """
    Validates Section 41: The Golden End-to-End Scenario:
    1. Ingest Google Meet transcript (proposing Onboarding Agent).
    2. Ingest Slack message (countering/questioning Onboarding Agent).
    3. Ingest Excalidraw initial diagram (Role A: linear baseline without Onboarding Agent).
    4. Conflict Engine detects multi-source contradiction across sources.
    5. Human reviews conflict, approves Onboarding Agent, advances Project State to v2.
    6. System generates Excalidraw change proposal (Role B) with structured diff preview.
    7. Human reviews diff and approves diagram update -> Excalidraw updated to v2.
    8. AI Workforce receives updated context; agent execution verifies consumption of State v2.
    """
    project_id = "proj_golden_scenario_01"
    tenant_id = "tenant_golden_e2e"

    ingestion = IngestionService()
    state_service = ProjectStateService()
    conflict_service = ConflictService(state_service=state_service)
    audit_service = AuditService()
    excal_service = ExcalidrawService(ingestion_service=ingestion, audit_service=audit_service)
    context_builder = ContextBuilder(state_service=state_service)
    workforce_service = AIWorkforceService(context_builder=context_builder, state_service=state_service)

    # Initial baseline Project State (v1)
    state = state_service.get_or_create_state(project_id, db_session)
    assert state.current_version == 1

    # =========================================================================
    # STEP 1: Ingest Google Meet transcript
    # Stakeholder: "We need to add an Onboarding Agent before the BA Agent to screen incoming client requests."
    # =========================================================================
    meet_event_in = SourceEventCreate(
        tenant_id=tenant_id,
        project_id=project_id,
        source="google_meet",
        source_event_id="conf_meet_e2e_entry_01",
        event_type="transcript_utterance",
        actor_id="usr_stakeholder_alice",
        occurred_at=datetime.now(timezone.utc),
        payload={
            "conference_record_id": "conf_meet_e2e_01",
            "speaker": "Alice (Product Lead)",
            "text": "We need to add an Onboarding Agent before the BA Agent to screen incoming client requests.",
            "language_code": "en-US",
        },
    )
    meet_source_event = ingestion.ingest_event(meet_event_in, db_session)
    meet_evidence = ingestion.create_evidence_from_event(
        event=meet_source_event,
        db=db_session,
        content=meet_event_in.payload["text"],
        metadata={"speaker": "Alice", "topic": "Architecture Workflow"},
    )
    assert meet_evidence is not None
    assert meet_evidence.source == "google_meet"

    # =========================================================================
    # STEP 2: Ingest Slack message
    # Team member: "Wait, didn't we decide the BA Agent handles initial intake directly? An Onboarding Agent might create redundant handoffs."
    # =========================================================================
    slack_event_in = SourceEventCreate(
        tenant_id=tenant_id,
        project_id=project_id,
        source="slack",
        source_event_id="slack_msg_e2e_02",
        event_type="channel_message",
        actor_id="usr_engineer_bob",
        occurred_at=datetime.now(timezone.utc),
        payload={
            "channel": "#architecture",
            "sender": "Bob (Tech Lead)",
            "text": "Wait, didn't we decide the BA Agent handles initial intake directly? An Onboarding Agent might create redundant handoffs.",
        },
    )
    slack_source_event = ingestion.ingest_event(slack_event_in, db_session)
    slack_evidence = ingestion.create_evidence_from_event(
        event=slack_source_event,
        db=db_session,
        content=slack_event_in.payload["text"],
        metadata={"channel": "#architecture", "author": "Bob"},
    )
    assert slack_evidence is not None
    assert slack_evidence.source == "slack"

    # =========================================================================
    # STEP 3: Ingest initial Excalidraw diagram (Role A: Input)
    # Scene showing existing pipeline: User -> BA Agent -> Project Planner Agent -> Functional Agent -> Tech Agent -> Frappe Agent
    # =========================================================================
    initial_diagram_nodes = ["User", "BA Agent", "Project Planner Agent", "Functional Agent", "Tech Agent", "Frappe Agent"]
    initial_elements = excal_service._build_flow_elements(initial_diagram_nodes)
    diagram_req = ExcalidrawIngestRequest(
        name="Current Pipeline Architecture",
        elements=initial_elements,
        app_state={"viewBackgroundColor": "#ffffff"},
        tenant_id=tenant_id,
    )
    artifact, excal_evidence = excal_service.ingest_diagram(
        project_id=project_id,
        req=diagram_req,
        db=db_session,
        tenant_id=tenant_id,
    )
    assert artifact.version == 1
    assert "Onboarding Agent" not in artifact.extracted_nodes_json
    assert excal_evidence.source == "excalidraw"

    # =========================================================================
    # STEP 4: Conflict Engine detects multi-source contradiction
    # Meet (proposing Onboarding Agent) vs Slack (questioning handoff) vs Excalidraw (current baseline)
    # =========================================================================
    conflict = conflict_service.create_conflict(
        project_id=project_id,
        title="Contradiction on Onboarding Agent introduction",
        description="Google Meet transcript proposes introducing an Onboarding Agent prior to the BA Agent, whereas Slack discussion questions redundant handoffs, and current Excalidraw architecture routes directly to BA Agent.",
        severity="high",
        conflict_type="architecture_contradiction",
        evidence_ids=[meet_evidence.id, slack_evidence.id, excal_evidence.id],
        db=db_session,
        tenant_id=tenant_id,
    )
    assert conflict.id is not None
    assert conflict.status == ConflictStatus.OPEN.value
    assert len(json.loads(conflict.evidence_ids_json)) == 3

    # =========================================================================
    # STEP 5: Human review & resolution -> State v2 bump
    # Human decides: "Approve addition of Onboarding Agent with scoped read-only intake role."
    # =========================================================================
    resolved_conflict = conflict_service.resolve_conflict(
        conflict_id=conflict.id,
        resolution_notes="Approve addition of Onboarding Agent with scoped read-only intake role. Hand-off sanitized intake to BA Agent.",
        actor_id="usr_lead_architect_carol",
        db=db_session,
        tenant_id=tenant_id,
    )
    assert resolved_conflict.status == ConflictStatus.APPROVED.value

    # Create StateChange proposal to update agent_workflow in Project State
    updated_workflow = ["Onboarding Agent", "BA Agent", "Project Planner Agent", "Functional Agent", "Tech Agent", "Frappe Agent"]
    state_proposal = state_service.propose_change(
        project_id=project_id,
        section="agent_workflow",
        operation=ChangeOperation.UPDATE,
        proposed_value=updated_workflow,
        reason="Resolved architecture conflict: added Onboarding Agent for client intake screening.",
        evidence_ids=[meet_evidence.id, slack_evidence.id],
        actor_id="usr_lead_architect_carol",
        db=db_session,
    )
    assert state_proposal.approval_status in (ApprovalStatus.PROPOSED.value, "proposed")

    # Approve StateChange proposal -> Advances Project State to v2
    state_version_rec = state_service.approve_state_change(
        change_id=state_proposal.id,
        actor_id="usr_lead_architect_carol",
        db=db_session,
    )
    approved_state = state_service.get_or_create_state(project_id, db_session)
    assert approved_state.current_version == 2
    assert "Onboarding Agent" in json.loads(approved_state.agent_workflow_json)

    # =========================================================================
    # STEP 6: Excalidraw Change Proposal Generation (Role B: Output)
    # System computes proposed visual modification with structured diff preview
    # =========================================================================
    proposal = excal_service.generate_proposal_from_state(
        project_id=project_id,
        state_version=approved_state.current_version,
        db=db_session,
        tenant_id=tenant_id,
    )
    assert proposal.id is not None
    assert proposal.status == ExcalidrawProposalStatus.PENDING.value
    assert proposal.derived_from_state_version == 2

    # Verify structured diff preview. Visualisation is derived from project
    # knowledge (not the deprecated agent workflow) and compiled deterministically.
    diff = json.loads(proposal.diff_preview_json)
    assert diff["nodes_after"], "expected a compiled visual plan"
    assert diff["nodes_added"], "expected new nodes derived from Project State"
    assert diff["connections_after"], "expected compiled relationships"
    assert "critique_ok" in diff
    # Verify authoritative artifact is NOT yet updated (Output Safety)
    db_session.refresh(artifact)
    assert artifact.version == 1, "Authoritative artifact was mutated before human approval!"

    # =========================================================================
    # STEP 7: Human Approval of Excalidraw Change
    # Human reviews diff preview and approves proposal -> Artifact updated to v2
    # =========================================================================
    reviewed_prop, updated_artifact = excal_service.review_proposal(
        proposal_id=proposal.id,
        action="approve",
        actor_id="usr_lead_architect_carol",
        db=db_session,
        tenant_id=tenant_id,
    )
    assert reviewed_prop.status == ExcalidrawProposalStatus.APPROVED.value
    assert updated_artifact is not None
    assert updated_artifact.version == 2
    # Approval applies the COMPILED visual plan derived from Project State, so the
    # artifact now carries the canonical shared-agent nodes (not the deprecated
    # sequential agent workflow).
    applied_nodes = json.loads(updated_artifact.extracted_nodes_json)
    assert "Synora Agent" in applied_nodes
    assert "Project State" in applied_nodes
    assert "Onboarding Agent" not in applied_nodes

    # The approval also appends an immutable visual revision linked to state v2.
    from app.services.visual_revision_service import VisualRevisionService

    latest_revision = VisualRevisionService().current_revision(project_id, db_session)
    assert latest_revision is not None
    assert latest_revision.derived_from_project_state_version == 2
    assert latest_revision.proposal_id == proposal.id

    # Verify audit log entry
    audit_logs = audit_service.query_logs(
        db=db_session,
        tenant_id=tenant_id,
        action="excalidraw_proposal_approved",
    )
    assert len(audit_logs) >= 1
    assert audit_logs[0].resource_id == proposal.id

    # =========================================================================
    # STEP 8: AI Workforce Context Update & Execution
    # Project Agent coordinator briefing and specialist agents reflect State v2
    # =========================================================================
    # Check Project Agent coordinator briefing
    briefing = workforce_service.get_project_coordinator_briefing(
        project_id=project_id,
        db=db_session,
        tenant_id=tenant_id,
    )
    assert briefing["coordinator"] == "Project Agent"
    assert briefing["current_state_version"] == 2
    assert "Onboarding Agent" in briefing["agent_workflow"]

    # Run Project Planner Agent against State v2
    planner_exec = workforce_service.run_agent(
        agent_id="project_planner_agent",
        project_id=project_id,
        db=db_session,
        tenant_id=tenant_id,
    )
    assert planner_exec.status == "completed"
    assert planner_exec.project_state_version == 2
    planner_payload = json.loads(planner_exec.output_payload_json)
    assert planner_payload["derived_from_state_version"] == 2

    # Run BA Agent against State v2
    ba_exec = workforce_service.run_agent(
        agent_id="ba_agent",
        project_id=project_id,
        db=db_session,
        tenant_id=tenant_id,
    )
    assert ba_exec.status == "completed"
    assert ba_exec.project_state_version == 2
    ba_payload = json.loads(ba_exec.output_payload_json)
    assert ba_payload["derived_from_state_version"] == 2
    assert "Onboarding" in ba_payload["title"] or "Onboarding" in ba_payload["summary"]

    # Run Tech Agent against State v2
    tech_exec = workforce_service.run_agent(
        agent_id="tech_agent",
        project_id=project_id,
        db=db_session,
        tenant_id=tenant_id,
    )
    assert tech_exec.status == "completed"
    assert tech_exec.project_state_version == 2

    print("\n--- GOLDEN END-TO-END SCENARIO SUCCESSFULLY VERIFIED ---")


def test_excalidraw_api_endpoints_and_coordinator_briefing(client: TestClient, db_session: Session):
    """
    Validates REST API endpoints for:
    - GET /projects/{id}/agents/coordinator-briefing
    - GET /projects/{id}/excalidraw
    - POST /projects/{id}/excalidraw/ingest
    - POST /projects/{id}/excalidraw/proposals/generate
    - GET /projects/{id}/excalidraw/proposals
    - POST /projects/{id}/excalidraw/proposals/{id}/review (approval & rejection)
    """
    proj_id = "proj_api_excal_test_01"

    # 1. Test Coordinator Briefing endpoint
    resp = client.get(
        f"/projects/{proj_id}/agents/coordinator-briefing",
        headers={"X-User-ID": "usr_lead_architect_carol"},
    )
    assert resp.status_code == 200
    briefing = resp.json()
    assert briefing["coordinator"] == "Project Agent"
    assert briefing["current_state_version"] >= 1
    assert "specialist_workforce" in briefing
    assert "ba_agent" in briefing["specialist_workforce"]
    assert "project_planner_agent" in briefing["specialist_workforce"]

    # 2. Test Get Initial Excalidraw Artifact
    resp = client.get(
        f"/projects/{proj_id}/excalidraw",
        headers={"X-User-ID": "usr_lead_architect_carol"},
    )
    assert resp.status_code == 200
    art = resp.json()
    assert art["version"] == 1
    assert len(art["elements"]) > 0

    # 3. Test Ingest Excalidraw Diagram
    ingest_payload = {
        "name": "Updated Visual Scene",
        "elements": [
            {"id": "t1", "type": "text", "text": "Client App"},
            {"id": "t2", "type": "text", "text": "API Gateway"},
        ],
        "app_state": {"gridSize": 10},
        "tenant_id": "default_tenant",
    }
    resp = client.post(
        f"/projects/{proj_id}/excalidraw/ingest",
        json=ingest_payload,
        headers={"X-User-ID": "usr_lead_architect_carol"},
    )
    assert resp.status_code == 200
    updated_art = resp.json()
    assert updated_art["version"] == 2
    assert "Client App" in updated_art["extracted_nodes"]

    # 4. Test Generate Excalidraw Proposal
    resp = client.post(
        f"/projects/{proj_id}/excalidraw/proposals/generate?state_version=2&reason=Sync+with+gateway",
        headers={"X-User-ID": "usr_lead_architect_carol"},
    )
    assert resp.status_code == 200
    proposal = resp.json()
    assert proposal["status"] == "pending"
    assert proposal["diff_preview"] is not None
    prop_id = proposal["id"]

    # 5. Test List Proposals
    resp = client.get(
        f"/projects/{proj_id}/excalidraw/proposals",
        headers={"X-User-ID": "usr_lead_architect_carol"},
    )
    assert resp.status_code == 200
    proposals = resp.json()
    assert len(proposals) >= 1

    # 6. Test Review Proposal (Approval)
    resp = client.post(
        f"/projects/{proj_id}/excalidraw/proposals/{prop_id}/review",
        json={"action": "approve", "reason": "Verified and approved by architect"},
        headers={"X-User-ID": "usr_lead_architect_carol"},
    )
    assert resp.status_code == 200
    review_res = resp.json()
    assert review_res["proposal"]["status"] == "approved"
    assert review_res["artifact"]["version"] == 3

