"""
Tests for the 'One Project = One Logical Project Agent' Architecture:
1. Auto-provisioning of Project Agent upon Project creation.
2. Logical context boundary isolation between distinct projects (memory, state, workspace).
3. Specialist capabilities execution coordinated by Project Agent.
4. Living Excalidraw workspace synchronization backed by PostgreSQL system of record.
5. Project Agent memory management and API endpoints.
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.models.project import Project, ProjectAgent, Workspace
from app.models.project_state import ChangeOperation
from app.models.excalidraw import ExcalidrawArtifact
from app.services.project_agent_service import ProjectAgentService
from app.services.project_state_service import ProjectStateService
from app.schemas.project_agent import ProjectCreateRequest


def test_auto_provisioning_on_project_creation(db_session: Session, client: TestClient):
    """
    Validates that creating a new project automatically provisions its dedicated Project Agent.
    """
    service = ProjectAgentService()
    project_agent = service.get_or_provision_project_agent("proj_auto_test_01", db_session)

    assert project_agent is not None
    assert project_agent.project_id == "proj_auto_test_01"
    assert "Project Agent" in project_agent.name

    # Verify connected tools and capabilities
    tools = json.loads(project_agent.connected_tools_json)
    assert "google_meet" in tools
    assert "whatsapp" in tools
    assert "excalidraw" in tools
    assert "slack" not in tools

    capabilities = json.loads(project_agent.capabilities_json)
    assert "ba_agent" in capabilities
    assert "project_planner_agent" in capabilities
    assert "functional_agent" in capabilities
    assert "tech_agent" in capabilities
    assert "frappe_agent" in capabilities

    # Verify living workspace artifact was provisioned
    assert project_agent.living_workspace_artifact_id is not None
    assert project_agent.workspace_sync_status == "synchronized"


def test_logical_isolation_between_projects(db_session: Session, client: TestClient):
    """
    Validates that two projects have strict logical isolation:
    - Distinct Project Agent entities
    - Isolated memory contexts
    - Isolated living Excalidraw workspaces
    - No cross-project context pollution
    """
    service = ProjectAgentService()
    proj_a_id = "proj_iso_alpha"
    proj_b_id = "proj_iso_beta"

    agent_a = service.get_or_provision_project_agent(proj_a_id, db_session)
    agent_b = service.get_or_provision_project_agent(proj_b_id, db_session)

    # 1. Distinct identities
    assert agent_a.id != agent_b.id
    assert agent_a.project_id == proj_a_id
    assert agent_b.project_id == proj_b_id

    # 2. Memory Isolation: Update Alpha's memory
    service.update_agent_memory(
        project_id=proj_a_id,
        db=db_session,
        memory_updates={
            "domain": "Healthcare Insurance Billing",
            "compliance": "HIPAA strict",
        },
    )

    db_session.refresh(agent_a)
    db_session.refresh(agent_b)
    mem_a = json.loads(agent_a.memory_context_json)
    mem_b = json.loads(agent_b.memory_context_json)

    assert mem_a.get("domain") == "Healthcare Insurance Billing"
    assert mem_a.get("compliance") == "HIPAA strict"
    assert mem_b.get("domain") != "Healthcare Insurance Billing"
    assert "compliance" not in mem_b

    # 3. Living Workspace Isolation
    assert agent_a.living_workspace_artifact_id != agent_b.living_workspace_artifact_id


def test_specialist_capability_dispatch_through_coordinator(db_session: Session, client: TestClient):
    """
    Validates that specialist capabilities are coordinated through the Project Agent
    and create traceable execution lineage in the PostgreSQL system of record.
    """
    service = ProjectAgentService()
    project_id = "proj_dispatch_test_01"

    # Ensure agent is provisioned
    agent = service.get_or_provision_project_agent(project_id, db_session)

    # Dispatch Business Analysis specialist capability
    execution = service.dispatch_capability(
        project_id=project_id,
        capability_id="ba_specialist",
        task_description="Analyze customer invoice approval requirements from Google Meet transcript",
        db=db_session,
    )

    assert execution is not None
    assert execution.agent_id == "ba_agent"
    assert execution.project_id == project_id
    assert execution.output_type in ("analysis", "requirement_proposal")
    assert execution.status == "completed"

    # Check execution record lineage in working memory
    db_session.refresh(agent)
    mem = json.loads(agent.memory_context_json)
    milestones = mem.get("recent_milestones", [])
    assert len(milestones) > 0
    assert any("ba_agent" in m for m in milestones)


def test_living_visual_workspace_sync_with_decision_cards(db_session: Session, client: TestClient):
    """
    Validates Section 5 & 7:
    Excalidraw is the living visual workspace maintained by the Project Agent.
    When a decision is approved (e.g. from Google Meet: 'Customer approved invoice workflow'),
    the Project Agent updates the living Excalidraw workspace in the PostgreSQL system of record
    with structured visual DECISION cards (Title, Source, Date, Evidence).
    """
    service = ProjectAgentService()
    state_service = ProjectStateService()
    project_id = "proj_living_excal_01"

    # Setup project state with a decision linked to evidence
    state = state_service.get_or_create_state(project_id, db_session)
    state_change = state_service.propose_change(
        project_id=project_id,
        section="decisions",
        operation=ChangeOperation.INSERT,
        proposed_value={
            "id": "dec_meet_invoice_01",
            "text": "Invoice workflow approved by customer",
            "date": "2026-09-24",
            "approved_by": "lead_architect",
            "detail": "Customer approved invoice approval before generation",
        },
        reason="Google Meet stakeholder alignment agreement",
        actor_id="ba_agent",
        evidence_ids=["ev_meet_transcript_042"],
        db=db_session,
    )
    # Approve state change into Project State v2
    state_service.approve_state_change(
        change_id=state_change.id,
        actor_id="lead_architect",
        db=db_session,
    )

    # Sync living visual workspace
    artifact = service.sync_living_excalidraw_workspace(project_id, db_session)

    assert artifact is not None
    assert artifact.project_id == project_id
    assert artifact.version >= 2

    elements = json.loads(artifact.elements_json)
    assert len(elements) > 0

    # Verify elements contain the living DECISION visual card
    texts = [el.get("text", "") for el in elements if el.get("type") == "text"]
    all_text = " ".join(texts)
    assert "DECISION" in all_text
    assert "Invoice workflow approved" in all_text
    assert "SOURCE: Google Meet" in all_text
    assert "EVIDENCE: ev_meet_transcript_042" in all_text


def test_project_and_agent_api_endpoints(db_session: Session, client: TestClient):
    """
    Validates the REST API endpoints:
    - POST /projects (creates project and auto-provisions Project Agent)
    - GET /projects (lists projects with agent ID)
    - GET /projects/{id}/agent (fetches Project Agent)
    - POST /projects/{id}/agent/dispatch (dispatches specialist capability)
    - GET /projects/{id}/agent/memory (retrieves isolated memory)
    - POST /projects/{id}/agent/memory (updates isolated memory)
    - POST /projects/{id}/agent/sync-excalidraw (triggers living workspace sync)
    """
    # 1. Create project
    create_resp = client.post(
        "/projects",
        json={"name": "Logistics Route Optimization", "description": "AI routing project"},
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert create_resp.status_code == 200
    proj_data = create_resp.json()
    project_id = proj_data["id"]
    assert proj_data["project_agent_id"] is not None

    # 1b. Create project with explicit source selection incl. canonical whatsapp ID
    create_sources_resp = client.post(
        "/projects",
        json={
            "name": "WhatsApp Source Project",
            "description": "Project with whatsapp source",
            "sources": ["google_meet", "whatsapp", "excalidraw"],
        },
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert create_sources_resp.status_code == 200, create_sources_resp.text
    sources_project_id = create_sources_resp.json()["id"]
    sources_agent_resp = client.get(
        f"/projects/{sources_project_id}/agent",
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert sources_agent_resp.status_code == 200
    assert sources_agent_resp.json()["connected_tools"] == [
        "google_meet",
        "whatsapp",
        "excalidraw",
    ]

    # 1c. Unknown source IDs are rejected deterministically
    bad_sources_resp = client.post(
        "/projects",
        json={"name": "Bad Source Project", "sources": ["slack"]},
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert bad_sources_resp.status_code == 400
    assert bad_sources_resp.json()["detail"]["error"] == "invalid_source"

    # 2. Get Project Agent
    agent_resp = client.get(
        f"/projects/{project_id}/agent",
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert agent_resp.status_code == 200
    agent_data = agent_resp.json()
    assert agent_data["project_id"] == project_id
    assert "Project Agent" in agent_data["name"]
    # capabilities is a list of capability DTOs
    capability_ids = [c["id"] for c in agent_data["capabilities"]]
    assert "ba_agent" in capability_ids

    # 3. Read and update Project Agent memory
    mem_update_resp = client.post(
        f"/projects/{project_id}/agent/memory",
        json={"memory_updates": {"customer_persona": "Enterprise Operations Director"}},
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert mem_update_resp.status_code == 200
    updated_mem = mem_update_resp.json()
    assert (
        updated_mem.get("customer_persona") == "Enterprise Operations Director"
        or updated_mem.get("memory_context", {}).get("customer_persona") == "Enterprise Operations Director"
    )

    mem_get_resp = client.get(
        f"/projects/{project_id}/agent/memory",
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert mem_get_resp.status_code == 200
    mem_body = mem_get_resp.json()
    assert (
        mem_body.get("customer_persona") == "Enterprise Operations Director"
        or mem_body.get("memory_context", {}).get("customer_persona") == "Enterprise Operations Director"
    )

    # 4. Dispatch Specialist Capability via API
    dispatch_resp = client.post(
        f"/projects/{project_id}/agent/dispatch",
        json={"capability_id": "tech_agent", "task_description": "Validate API latency constraints"},
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert dispatch_resp.status_code == 200
    dispatch_data = dispatch_resp.json()
    assert dispatch_data["execution"]["agent_id"] == "tech_agent"
    assert "Project Agent successfully coordinated" in dispatch_data["message"]

    # 5. Sync Living Excalidraw Workspace via API
    sync_resp = client.post(
        f"/projects/{project_id}/agent/sync-excalidraw",
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert sync_resp.status_code == 200
    sync_data = sync_resp.json()
    assert sync_data["id"] is not None
    assert isinstance(sync_data["elements"], list)


def test_workspace_central_agent_provisioning_and_portfolio_oversight(db_session: Session, client: TestClient):
    """
    Validates that a single central Workspace Agent handles and oversees
    all projects across the workspace:
    - Automatically provisioned for the workspace
    - Maintains portfolio oversight of multiple projects
    - Dispatches specialist capabilities across projects
    - Records portfolio-level milestones and cross-project context
    """
    service = ProjectAgentService()
    ws_id = "ws_portfolio_test"

    # Create two projects in the same workspace
    proj_a = service.get_or_create_project("proj_port_a", db_session, workspace_id=ws_id, name="Logistics Platform")
    proj_b = service.get_or_create_project("proj_port_b", db_session, workspace_id=ws_id, name="Billing Service")

    # Fetch central Workspace Agent
    central_agent = service.get_or_provision_workspace_agent(ws_id, db_session)

    assert central_agent is not None
    assert central_agent.workspace_id == ws_id
    assert "Central" in central_agent.name

    # Check portfolio read representation
    dto = service.format_workspace_agent_read(central_agent, db_session)
    assert dto.projects_count >= 2
    managed_names = [p["name"] for p in dto.managed_projects]
    assert "Logistics Platform" in managed_names
    assert "Billing Service" in managed_names

    # Dispatch capability via central agent focusing on project A
    exec_a = service.dispatch_workspace_capability(
        workspace_id=ws_id,
        capability_id="ba_agent",
        project_id=proj_a.id,
        task_description="Define cargo tracking acceptance criteria",
        db=db_session,
    )
    assert exec_a.project_id == proj_a.id
    assert exec_a.agent_id == "ba_agent"

    # Check central agent portfolio memory reflects the execution
    db_session.refresh(central_agent)
    mem = json.loads(central_agent.memory_context_json)
    milestones = mem.get("recent_milestones", [])
    assert any(proj_a.id in m for m in milestones)


def test_workspace_central_agent_api_endpoints(db_session: Session, client: TestClient):
    """
    Validates REST API endpoints for the central Workspace Agent:
    - GET /workspace/agent
    - GET /workspaces/{id}/agent
    - POST /workspace/agent/dispatch
    - POST /workspace/agent/memory
    """
    # 1. Get default workspace central agent
    res = client.get("/workspace/agent", headers={"X-User-ID": "usr_lead"})
    assert res.status_code == 200
    data = res.json()
    assert data["workspace_id"] == "ws_default"
    assert "Central" in data["name"]
    assert "managed_projects" in data

    # 2. Update portfolio memory
    mem_res = client.post(
        "/workspace/agent/memory",
        json={"priorities": ["Unified architecture governance across all apps"]},
        headers={"X-User-ID": "usr_lead"},
    )
    assert mem_res.status_code == 200
    mem_data = mem_res.json()
    assert any("Unified architecture governance" in p for p in mem_data.get("portfolio_priorities", []))

    # 3. Dispatch capability via central workspace agent
    disp_res = client.post(
        "/workspace/agent/dispatch",
        json={"capability_id": "tech_agent", "task_description": "Assess global tech stack constraints"},
        headers={"X-User-ID": "usr_lead"},
    )
    assert disp_res.status_code == 200
    disp_data = disp_res.json()
    assert disp_data["status"] == "success"
    assert disp_data["execution"]["agent_id"] == "tech_agent"


def test_project_name_uniqueness_and_deduplication(db_session: Session, client: TestClient):
    """
    Validates that:
    1. Creating a project with an existing name is rejected with HTTP 409 Conflict.
    2. Name uniqueness is case-insensitive and trims whitespace.
    3. Empty project names are rejected with HTTP 400 Bad Request.
    4. Service layer get_or_create_project returns the existing Project rather than duplicating.
    """
    service = ProjectAgentService()

    # 1. Create a project via API
    resp = client.post(
        "/projects",
        json={"name": "Dinein Unique", "description": "Restaurant order management"},
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert resp.status_code == 200
    first_id = resp.json()["id"]

    # 2. Attempt duplicate creation with exact same name -> 409 Conflict
    dup_resp = client.post(
        "/projects",
        json={"name": "Dinein Unique", "description": "Duplicate attempt"},
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert dup_resp.status_code == 409
    assert "already exists" in dup_resp.json()["detail"]

    # 3. Attempt duplicate creation with lowercase and whitespace -> 409 Conflict
    case_resp = client.post(
        "/projects",
        json={"name": "  dinein unique  ", "description": "Case insensitive duplicate"},
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert case_resp.status_code == 409
    assert "already exists" in case_resp.json()["detail"]

    # 4. Attempt creation with empty name -> 400 Bad Request
    empty_resp = client.post(
        "/projects",
        json={"name": "   ", "description": "Empty name"},
        headers={"X-User-ID": "usr_test_lead"},
    )
    assert empty_resp.status_code == 400

    # 5. Service layer get_or_create_project deduplication
    matched_proj = service.get_or_create_project(
        project_id="proj_some_new_random_id",
        db=db_session,
        workspace_id="ws_default",
        name="dinein unique",
    )
    assert matched_proj.id == first_id


