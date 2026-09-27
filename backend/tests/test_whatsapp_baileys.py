import json
import pytest
from sqlalchemy.orm import Session

from app.connectors.baileys import WhatsAppBaileysConnector
from app.connectors.base import ConnectorStatus
from app.connectors.registry import ConnectorRegistry, registry
from app.models.evidence import Evidence
from app.models.excalidraw import ExcalidrawArtifact, ExcalidrawProposal
from app.models.project import Project
from app.models.source_event import SourceEvent
from app.services.project_agent_service import ProjectAgentService
from app.services.whatsapp_service import WhatsAppIntelligenceService


def test_whatsapp_baileys_connector_registration():
    """Verify WhatsApp Baileys connector registers and reports unconfigured status until a session connects."""
    reg = ConnectorRegistry()
    conn = WhatsAppBaileysConnector()
    reg.register(conn)

    assert "whatsapp" in reg.list_providers()
    assert reg.get("whatsapp") is conn

    health = conn.health_check()
    assert health.status == ConnectorStatus.DEGRADED
    assert "Baileys" in health.details.get("client", "")


def test_whatsapp_project_identification_claims_engine(db_session: Session):
    """
    Verify WhatsApp intelligence understands when team is talking about Healthcare Claims Engine
    vs Core Architecture.
    """
    agent_service = ProjectAgentService()
    service = WhatsAppIntelligenceService()

    # Ensure two distinct projects exist in database
    claims_proj = agent_service.get_or_create_project(
        project_id="proj_claims_test",
        name="Healthcare Claims Engine",
        description="Automated health insurance claims processing and fraud detection",
        workspace_id="ws_default",
        db=db_session,
    )
    core_proj = agent_service.get_or_create_project(
        project_id="proj_core_test",
        name="Synesis Core Architecture",
        description="Core platform identity, routing, and database pipeline",
        workspace_id="ws_default",
        db=db_session,
    )

    # 1. Message mentioning claims / kyc should route to Healthcare Claims Engine
    msg_claims = "Team, we decided to integrate Digilocker KYC API for automatic claimant identity verification."
    matched_p, conf, reason = service.identify_project_from_context(msg_claims, db_session)
    assert matched_p.id == claims_proj.id
    assert conf >= 0.70
    assert "Healthcare Claims" in matched_p.name

    # 2. Message mentioning core auth / session / redis should route to Core Architecture
    msg_core = "For Core Architecture, let's switch session storage to Redis with JWT validation."
    matched_core, conf_core, reason_core = service.identify_project_from_context(msg_core, db_session)
    assert matched_core.id == core_proj.id
    assert conf_core >= 0.70
    assert "Core Architecture" in matched_core.name

    # 3. Message with explicit project ID
    msg_id = f"Regarding {claims_proj.id}: add Fraud Detection Engine to the pipeline."
    matched_id, conf_id, reason_id = service.identify_project_from_context(msg_id, db_session)
    assert matched_id.id == claims_proj.id
    assert conf_id >= 0.95


def test_whatsapp_message_processing_and_excalidraw_updates(db_session: Session):
    """
    Verify that an incoming WhatsApp group chat message:
    1. Understands target project
    2. Ingests Evidence
    3. Accurately mutates and updates the target project's Excalidraw whiteboard
    """
    agent_service = ProjectAgentService()
    service = WhatsAppIntelligenceService()

    claims_proj = agent_service.get_or_create_project(
        project_id="proj_claims_excal_test",
        name="Healthcare Claims Engine",
        description="Claims adjudication system",
        workspace_id="ws_default",
        db=db_session,
    )

    initial_artifact = service.excal_service.get_or_create_artifact(
        project_id=claims_proj.id,
        db=db_session,
    )
    initial_version = initial_artifact.version

    # Incoming WhatsApp message discussing an architectural component
    payload = {
        "message_id": "wamid.HBgTEST12345",
        "sender_jid": "919876543210@s.whatsapp.net",
        "sender_name": "Dr. Arvind (Lead Architect)",
        "group_jid": "120363025812345678@g.us",
        "group_name": "Synora Architecture & Engineering",
        "text": "Team, regarding the Healthcare Claims project, we have decided to integrate Digilocker KYC API for automatic claimant identity verification. Add Digilocker KYC component to the pipeline.",
    }

    result = service.process_incoming_message(payload, db_session)

    assert result["ok"] is True
    assert result["matched_project"]["id"] == claims_proj.id
    assert result["confidence"] >= 0.80
    assert result["excalidraw_updated"] is True
    assert result["artifact_version"] == initial_version + 1
    assert result["context_status"] == "resolved"
    assert "Digilocker KYC Service" in result["nodes_added"]

    # Verify Evidence was persisted
    ev = db_session.query(Evidence).filter(Evidence.id == result["evidence_id"]).first()
    assert ev is not None
    assert ev.project_id == claims_proj.id
    assert "WhatsApp [Synora Architecture & Engineering]" in ev.content
    assert "Digilocker KYC" in ev.content

    # Verify Excalidraw artifact was actually updated with the new node
    db_session.refresh(initial_artifact)
    extracted_nodes = json.loads(initial_artifact.extracted_nodes_json)
    assert "Digilocker KYC Service" in extracted_nodes

    # Verify Decision Card was rendered in the scene elements
    elements = json.loads(initial_artifact.elements_json)
    element_texts = [el.get("text", "") for el in elements if el.get("type") == "text"]
    decision_texts = [t for t in element_texts if "DECISION" in t and "Digilocker KYC" in t]
    assert len(decision_texts) > 0

    # Verify ExcalidrawProposal was recorded with diff
    proposal = db_session.query(ExcalidrawProposal).filter(ExcalidrawProposal.id == result["proposal_id"]).first()
    assert proposal is not None
    assert proposal.status == "pending"
    assert "Digilocker KYC Service" in proposal.reason


def test_whatsapp_isolation_between_two_projects(db_session: Session):
    """
    Verify that WhatsApp messages about Project A ONLY mutate Project A's Excalidraw,
    and messages about Project B ONLY mutate Project B's Excalidraw.
    """
    agent_service = ProjectAgentService()
    service = WhatsAppIntelligenceService()

    proj_a = agent_service.get_or_create_project(
        project_id="proj_iso_a",
        name="Healthcare Claims Engine",
        description="Claims engine",
        workspace_id="ws_default",
        db=db_session,
    )
    proj_b = agent_service.get_or_create_project(
        project_id="proj_iso_b",
        name="Synesis Core Architecture",
        description="Core platform",
        workspace_id="ws_default",
        db=db_session,
    )

    art_a = service.excal_service.get_or_create_artifact(proj_a.id, db_session)
    art_b = service.excal_service.get_or_create_artifact(proj_b.id, db_session)
    v_a_initial = art_a.version
    v_b_initial = art_b.version

    # Message about Project A
    res_a = service.process_incoming_message(
        {
            "message_id": "wa_msg_a_1",
            "sender_name": "Alice",
            "text": "In Healthcare Claims, let's add Fraud Detection Engine to verify claim submissions.",
        },
        db_session,
    )
    assert res_a["matched_project"]["id"] == proj_a.id

    db_session.refresh(art_a)
    db_session.refresh(art_b)
    # Project A whiteboard updated, Project B whiteboard untouched!
    assert art_a.version == v_a_initial + 1
    assert art_b.version == v_b_initial

    # Message about Project B
    res_b = service.process_incoming_message(
        {
            "message_id": "wa_msg_b_1",
            "sender_name": "Bob",
            "text": "For Core Architecture, we decided to use Redis Session Cache for state persistence.",
        },
        db_session,
    )
    assert res_b["matched_project"]["id"] == proj_b.id

    db_session.refresh(art_a)
    db_session.refresh(art_b)
    # Project B whiteboard updated to v2, Project A remains at v2
    assert art_a.version == v_a_initial + 1
    assert art_b.version == v_b_initial + 1


def test_whatsapp_ignores_casual_chitchat(db_session: Session):
    """
    Verify that casual chit-chat (greetings, lunch talk, acknowledgments)
    is recognized and ignored. All Excalidraw whiteboards remain untouched.
    """
    agent_service = ProjectAgentService()
    service = WhatsAppIntelligenceService()

    proj = agent_service.get_or_create_project(
        project_id="proj_casual_test",
        name="Healthcare Claims Engine",
        description="Claims engine",
        workspace_id="ws_default",
        db=db_session,
    )
    art = service.excal_service.get_or_create_artifact(proj.id, db_session)
    v_initial = art.version

    # Casual messages that must be ignored
    casual_messages = [
        "Hey team, what time is lunch today? Anyone hungry?",
        "Good morning everyone! Have a great Friday.",
        "Can someone send the Google Meet link for the 3pm call?",
        "ok cool thanks",
        "sounds good 👍",
    ]

    for msg in casual_messages:
        res = service.process_incoming_message(
            {
                "message_id": f"msg_casual_{hash(msg)}",
                "sender_name": "Teammate",
                "text": msg,
            },
            db_session,
        )
        assert res["ok"] is True
        assert res["processed"] is False
        assert res["status"] == "ignored"
        assert res["matched_project"] is None
        assert res["excalidraw_updated"] is False
        assert "casual" in res["reason"].lower()

    # Verify project whiteboard remained completely untouched!
    db_session.refresh(art)
    assert art.version == v_initial


def test_whatsapp_quarantines_unknown_project_context(db_session: Session):
    """Unknown project discussions are retained under Unknown Context."""
    agent_service = ProjectAgentService()
    service = WhatsAppIntelligenceService()

    claims_proj = agent_service.get_or_create_project(
        project_id="proj_claims_leaveit",
        name="Healthcare Claims Engine",
        description="Health insurance claims adjudication",
        workspace_id="ws_default",
        db=db_session,
    )
    core_proj = agent_service.get_or_create_project(
        project_id="proj_core_leaveit",
        name="Synesis Core Architecture",
        description="Core architecture system",
        workspace_id="ws_default",
        db=db_session,
    )

    art_claims = service.excal_service.get_or_create_artifact(claims_proj.id, db_session)
    art_core = service.excal_service.get_or_create_artifact(core_proj.id, db_session)
    v_claims_init = art_claims.version
    v_core_init = art_core.version

    res = service.process_incoming_message(
        {
            "message_id": "wa_msg_uncreated_1",
            "sender_name": "Crypto Dev",
            "group_jid": "120363099999999999@g.us",
            "group_name": "general",
            "text": "For the Solana Crypto Arbitrage Bot, let's deploy Uniswap v3 flash loans and integrate Phantom Wallet API.",
        },
        db_session,
    )

    assert res["ok"] is True
    assert res["processed"] is True
    assert res["matched_project"]["id"] == "system_unknown_context"
    assert res["context_status"] in {"unknown", "ambiguous"}
    assert res["excalidraw_updated"] is False

    db_session.refresh(art_claims)
    db_session.refresh(art_core)
    assert art_claims.version == v_claims_init
    assert art_core.version == v_core_init


def test_whatsapp_api_endpoints(client, db_session: Session):
    """Verify WhatsApp REST API and webhook endpoints."""
    agent_service = ProjectAgentService()
    claims_proj = agent_service.get_or_create_project(
        project_id="proj_claims_api_test",
        name="Healthcare Claims Engine",
        description="Health insurance claims processing",
        workspace_id="ws_default",
        db=db_session,
    )
    core_proj = agent_service.get_or_create_project(
        project_id="proj_core_api_test",
        name="Synesis Core Architecture",
        description="Core architecture system",
        workspace_id="ws_default",
        db=db_session,
    )

    # 1. Health & status endpoint (no live Baileys session in tests → degraded)
    res_status = client.get("/connectors/whatsapp/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert status_data["provider"] == "whatsapp"
    assert status_data["status"] == "degraded"
    assert "Baileys" in status_data["details"]["client"]

    # 2. Simulate group chat message
    sim_payload = {
        "sender_name": "Chief Architect",
        "group_name": "Synora Product Council",
        "text": "For Healthcare Claims Engine: requirement is that all claims above $5000 must trigger AML Verification Engine.",
    }
    res_sim = client.post(
        "/connectors/whatsapp/simulate",
        json=sim_payload,
        headers={"X-User-ID": "usr_synesis_default"},
    )
    assert res_sim.status_code == 200
    sim_data = res_sim.json()
    assert sim_data["ok"] is True
    assert "Healthcare Claims" in sim_data["matched_project"]["name"]
    assert sim_data["excalidraw_updated"] is True
    assert sim_data["evidence_id"] is not None

    # 3. Webhook endpoint from Baileys daemon
    webhook_payload = {
        "message_id": "wamid_webhook_test_999",
        "sender_name": "DevOps Engineer",
        "group_name": "Synora Engineering",
        "text": "In Core Architecture: we decided to deploy Celery Task Queue for asynchronous event delivery.",
    }
    res_hook = client.post("/connectors/whatsapp/webhook", json=webhook_payload)
    assert res_hook.status_code == 200
    hook_data = res_hook.json()
    assert hook_data["ok"] is True
    assert "Core Architecture" in hook_data["matched_project"]["name"]

    # 4. History endpoint
    res_hist = client.get("/connectors/whatsapp/history")
    assert res_hist.status_code == 200
    hist_data = res_hist.json()
    assert len(hist_data) >= 2
    assert any("Healthcare Claims" in h.get("content", "") or "Core Architecture" in h.get("content", "") for h in hist_data)


def test_whatsapp_session_status_lifecycle_and_group_count(client):
    """
    Validates WhatsApp session lifecycle requirements:
    1. Unconfigured session returns degraded/disconnected with None latency and no fake 0 groups
    2. Connected session reports healthy status, real active group count, and valid latency
    3. Reconnecting session reports reconnecting session status and degraded health
    4. Disconnected session clears active groups and reports disconnected status
    5. Repeated session registration safely updates status idempotently
    6. Verifies /connectors/whatsapp/session-status endpoint works end-to-end
    """
    conn = WhatsAppBaileysConnector()

    # 1. Unconfigured session
    health_unconf = conn.health_check("session_unconf_test")
    assert health_unconf.status == ConnectorStatus.DEGRADED
    assert health_unconf.latency_ms is None
    assert health_unconf.details["session_status"] == "unconfigured"
    assert health_unconf.details["active_groups_count"] is None

    # 2. Connected session
    conn.update_session_status(
        session_id="session_test_01",
        status="connected",
        active_groups_count=4,
    )
    health_conn = conn.health_check("session_test_01")
    assert health_conn.status == ConnectorStatus.HEALTHY
    assert health_conn.latency_ms is not None
    assert health_conn.details["session_status"] == "connected"
    assert health_conn.details["active_groups_count"] == 4
    assert health_conn.details["connected_at"] is not None

    # 3. Reconnecting session
    conn.update_session_status(
        session_id="session_test_01",
        status="reconnecting",
        active_groups_count=None,
    )
    health_rec = conn.health_check("session_test_01")
    assert health_rec.status == ConnectorStatus.DEGRADED
    assert health_rec.details["session_status"] == "reconnecting"
    assert health_rec.details["active_groups_count"] is None
    assert health_rec.latency_ms is None

    # 4. Disconnected session
    conn.update_session_status(
        session_id="session_test_01",
        status="disconnected",
        active_groups_count=None,
    )
    health_disc = conn.health_check("session_test_01")
    assert health_disc.status == ConnectorStatus.DISCONNECTED
    assert health_disc.details["session_status"] == "disconnected"
    assert health_disc.details["active_groups_count"] is None
    assert health_disc.latency_ms is None

    # 5. Repeated session registration
    conn.update_session_status(
        session_id="session_test_01",
        status="connected",
        active_groups_count=7,
    )
    # Repeated update with same session ID
    conn.update_session_status(
        session_id="session_test_01",
        status="connected",
        active_groups_count=8,
    )
    health_rep = conn.health_check("session_test_01")
    assert health_rep.status == ConnectorStatus.HEALTHY
    assert health_rep.details["active_groups_count"] == 8

    # 6. REST API: POST /connectors/whatsapp/session-status and GET /connectors/whatsapp/status
    post_res = client.post(
        "/connectors/whatsapp/session-status",
        json={
            "session_id": "baileys_live",
            "status": "connected",
            "active_groups_count": 5,
        },
    )
    assert post_res.status_code == 200
    assert post_res.json()["ok"] is True

    get_res = client.get("/connectors/whatsapp/status?connection_id=baileys_live")
    assert get_res.status_code == 200
    body = get_res.json()
    assert body["status"] == "healthy"
    assert body["details"]["session_status"] == "connected"
    assert body["details"]["active_groups_count"] == 5

    # Report disconnect via API
    client.post(
        "/connectors/whatsapp/session-status",
        json={
            "session_id": "baileys_live",
            "status": "disconnected",
        },
    )
    get_res2 = client.get("/connectors/whatsapp/status?connection_id=baileys_live")
    assert get_res2.status_code == 200
    body2 = get_res2.json()
    assert body2["status"] == "disconnected"
    assert body2["details"]["session_status"] == "disconnected"
    assert body2["details"]["active_groups_count"] is None

