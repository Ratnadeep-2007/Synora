import json
import pytest
from sqlalchemy.orm import Session

from app.connectors.baileys import WhatsAppBaileysConnector
from app.connectors.base import ConnectorStatus
from app.connectors.registry import ConnectorRegistry, registry
from app.models.context_resolution import UnknownContextItem, UnknownItemStatus
from app.models.evidence import Evidence
from app.models.excalidraw import ExcalidrawProposal
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.services.context_intelligence import ContextIntelligenceService
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


def test_whatsapp_uses_shared_context_intelligence(db_session: Session):
    """WhatsApp must resolve projects through the SHARED Context Intelligence engine.

    Deterministic signals resolve exactly. Free text without a deterministic
    signal is never silently attached to a project.
    """
    agent_service = ProjectAgentService()
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

    ctx = ContextIntelligenceService()

    # 1. Explicit project ID -> exact deterministic resolution
    res_id = ctx.resolve(
        source="whatsapp",
        payload={"text": f"Regarding {claims_proj.id}: add Fraud Detection Engine."},
        db=db_session,
    )
    assert res_id.decision == "resolved"
    assert res_id.project_id == claims_proj.id
    assert res_id.requires_human_review is False

    # 2. Explicit project tag -> deterministic resolution
    res_tag = ctx.resolve(
        source="whatsapp",
        payload={"text": "[core] we decided to use Redis Session Cache for persistence."},
        db=db_session,
    )
    assert res_tag.decision == "resolved"
    assert res_tag.project_id == core_proj.id

    # 3. Free text that does not match any workspace project goes to Unknown Context
    res_free = ctx.resolve(
        source="whatsapp",
        payload={"text": "we need to build a Shopify e-commerce catalog sync for an external apparel store."},
        db=db_session,
    )
    assert res_free.decision == "unknown"
    assert res_free.project_id is None
    assert res_free.requires_human_review is True

    # 4. Unknown Context is never a candidate project
    assert all(
        c.project_id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
        for c in res_free.candidate_projects
    )


def test_whatsapp_message_routes_and_auto_applies(db_session: Session):
    """
    A deterministically-resolved WhatsApp message (zero-human-loop):
    1. Resolves the target project through the shared engine
    2. Persists Evidence with provenance
    3. Agent AUTOMATICALLY writes the note to that project's Excalidraw board
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

    payload = {
        "message_id": "wamid.HBgTEST12345",
        "sender_jid": "919876543210@s.whatsapp.net",
        "sender_name": "Dr. Arvind (Lead Architect)",
        "group_jid": "120363025812345678@g.us",
        "group_name": "Synora Architecture & Engineering",
        "text": (
            f"Team, regarding {claims_proj.id}: we have decided to integrate "
            "Digilocker KYC API for automatic claimant identity verification."
        ),
    }

    result = service.process_incoming_message(payload, db_session)

    assert result["ok"] is True
    assert result["processed"] is True
    assert result["matched_project"]["id"] == claims_proj.id

    # First message: evidence is captured but the board is not rewritten yet,
    # because one message cannot describe an architecture.
    assert result["excalidraw_updated"] is False
    db_session.refresh(initial_artifact)
    assert initial_artifact.version == initial_version

    # Evidence was persisted with provenance against the resolved project.
    ev = db_session.query(Evidence).filter(Evidence.id == result["evidence_id"]).first()
    assert ev is not None
    assert ev.project_id == claims_proj.id
    assert "Digilocker KYC" in ev.content

    # Second message crosses the evidence threshold; the board then advances
    # automatically, with no UI interaction.
    payload2 = dict(payload)
    payload2["message_id"] = "wamid.HBgTEST12346"
    payload2["text"] = (
        f"Regarding {claims_proj.id}: follow-up - the KYC integration must also "
        "support Aadhaar and the claims service must retry on transient failure."
    )
    result2 = service.process_incoming_message(payload2, db_session)
    assert result2["ok"] is True
    assert result2["excalidraw_updated"] is True
    assert result2["visual_proposal_pending"] is False

    db_session.refresh(initial_artifact)
    assert initial_artifact.version == initial_version + 1


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

    # Message about Project A
    res_a = service.process_incoming_message(
        {
            "message_id": "wa_msg_a_1",
            "sender_name": "Alice",
            "text": f"In {proj_a.id}, let's add Fraud Detection Engine to verify claim submissions.",
        },
        db_session,
    )
    assert res_a["matched_project"]["id"] == proj_a.id

    # Message about Project B
    res_b = service.process_incoming_message(
        {
            "message_id": "wa_msg_b_1",
            "sender_name": "Bob",
            "text": f"For {proj_b.id}, we decided to use Redis Session Cache for state persistence.",
        },
        db_session,
    )
    assert res_b["matched_project"]["id"] == proj_b.id

    # Evidence for each message is scoped to exactly one project: no cross-pollution.
    ev_a = db_session.query(Evidence).filter(Evidence.id == res_a["evidence_id"]).first()
    ev_b = db_session.query(Evidence).filter(Evidence.id == res_b["evidence_id"]).first()
    assert ev_a.project_id == proj_a.id
    assert ev_b.project_id == proj_b.id


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


def test_whatsapp_leaves_uncreated_project_alone(db_session: Session):
    """
    Verify that conversation about a project that is NOT created in the workspace
    is completely ignored (leave it), and DOES NOT pollute or mutate any existing project's whiteboard.
    """
    agent_service = ProjectAgentService()
    service = WhatsAppIntelligenceService()

    # Workspace only has Claims and Core
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

    # Conversation about an uncreated, unrelated project (e.g. Solana Crypto Wallet)
    uncreated_proj_message = (
        "For the Solana Crypto Arbitrage Bot, let's deploy Uniswap v3 flash loans and integrate Phantom Wallet API."
    )

    res = service.process_incoming_message(
        {
            "message_id": "wa_msg_uncreated_1",
            "sender_name": "Crypto Dev",
            "text": uncreated_proj_message,
        },
        db_session,
    )

    # Must be preserved in Unknown Context for human triage, never attached
    # to an existing project and never silently discarded.
    assert res["ok"] is True
    assert res["status"] == "unknown_context"
    assert res["matched_project"] is None
    assert res["excalidraw_updated"] is False
    assert res["unknown_item_id"] is not None

    item = (
        db_session.query(UnknownContextItem)
        .filter(UnknownContextItem.id == res["unknown_item_id"])
        .first()
    )
    assert item is not None
    assert item.status == UnknownItemStatus.PENDING.value
    assert item.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    # Original provenance preserved
    assert item.source_event_id == "wa_msg_uncreated_1"
    assert item.evidence_id == res["evidence_id"]

    # Verify BOTH existing project whiteboards remained untouched!
    db_session.refresh(art_claims)
    db_session.refresh(art_core)
    assert art_claims.version == v_claims_init
    assert art_core.version == v_core_init


def test_whatsapp_api_endpoints(client, db_session: Session):
    """Verify WhatsApp API, durable queueing, and explicit batch reconciliation."""
    agent_service = ProjectAgentService()
    claims_proj = agent_service.get_or_create_project(
        project_id="proj_claims_api_test",
        name="Healthcare Claims Engine",
        description="Health insurance claims processing",
        workspace_id="ws_default",
        db=db_session,
    )
    agent_service.get_or_create_project(
        project_id="proj_core_api_test",
        name="Synesis Core Architecture",
        description="Core architecture system",
        workspace_id="ws_default",
        db=db_session,
    )

    res_status = client.get("/connectors/whatsapp/status")
    assert res_status.status_code == 200
    assert res_status.json()["provider"] == "whatsapp"

    sim_payload = {
        "sender_name": "Chief Architect",
        "group_name": "Synora Product Council",
        "group_jid": "api-test@g.us",
        "message_id": "wa_api_sim_1",
        "text": "general announcement: let us schedule a sync to review all roadmap priorities next week.",
    }
    res_sim = client.post(
        "/connectors/whatsapp/simulate",
        json=sim_payload,
        headers={"X-User-ID": "usr_synesis_default"},
    )
    assert res_sim.status_code == 200
    assert res_sim.json()["status"] == "queued"

    webhook_payload = {
        "message_id": "wamid_webhook_test_999",
        "sender_name": "DevOps Engineer",
        "group_name": "Synora Engineering",
        "group_jid": "api-test@g.us",
        "text": f"For {claims_proj.id}: we decided to deploy Celery Task Queue.",
    }
    res_hook = client.post("/connectors/whatsapp/webhook", json=webhook_payload)
    assert res_hook.status_code == 200
    assert res_hook.json()["status"] == "queued"

    res_flush = client.post(
        "/connectors/whatsapp/process-batches?force=true",
        headers={"X-User-ID": "usr_synesis_default"},
    )
    assert res_flush.status_code == 200
    assert res_flush.json()["ok"] is True
    assert res_flush.json()["processed_batches"] >= 1

    res_hist = client.get("/connectors/whatsapp/history")
    assert res_hist.status_code == 200
    assert len(res_hist.json()) >= 1

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


def test_whatsapp_message_auto_applies_diagram_to_excalidraw(db_session: Session):
    """
    Validates end-to-end pipeline:
    WhatsApp Message In -> Classified to Project -> Evidence persisted.

    Canvas regeneration is deferred until a project has accumulated enough
    evidence to describe an architecture. A single message must not produce a
    diagram, because the planner would fill the gaps from its own priors
    rather than from the project's record. Once the threshold is met the
    canvas still updates automatically, with no UI interaction needed.
    """
    from app.models.visual_revision import VisualRevision

    agent_service = ProjectAgentService()
    service = WhatsAppIntelligenceService()

    proj = agent_service.get_or_create_project(
        project_id="proj_auto_diagram",
        name="Auto Pipeline Service",
        description="Autonomous diagram generation test",
        workspace_id="ws_default",
        db=db_session,
    )

    artifact = service.excal_service.get_or_create_artifact(
        project_id=proj.id,
        db=db_session,
    )
    assert artifact.version == 1

    payload = {
        "message_id": "wamid.AUTO12345",
        "sender_jid": "919999999999@s.whatsapp.net",
        "sender_name": "DevOps Architect",
        "group_jid": "120363025812345678@g.us",
        "group_name": "Core Architecture",
        "text": (
            f"Regarding {proj.id}: We are designing a microservices architecture with an "
            "API Gateway that directs requests to Auth Service and Payment Service, "
            "persisting into Postgres DB with a Redis cache."
        ),
        "auto_apply_diagram": True,
    }

    result = service.process_incoming_message(payload, db_session)

    assert result["ok"] is True
    assert result["processed"] is True
    assert result["matched_project"]["id"] == proj.id

    # First message: evidence is captured, but the canvas is left alone because
    # one message is not an architecture.
    assert result["excalidraw_updated"] is False
    db_session.refresh(artifact)
    assert artifact.version == 1

    # Second message crosses the evidence threshold and triggers the diagram.
    payload2 = dict(payload)
    payload2["message_id"] = "wamid.AUTO12346"
    payload2["text"] = (
        f"Regarding {proj.id}: Follow-up - the API Gateway also needs rate limiting, "
        "and Auth Service must issue refresh tokens before Payment Service is called."
    )
    result2 = service.process_incoming_message(payload2, db_session)
    assert result2["ok"] is True
    assert result2["excalidraw_updated"] is True
    assert result2["visual_proposal_pending"] is False

    # Verify artifact updated directly
    db_session.refresh(artifact)
    assert artifact.version >= 2
    elements = json.loads(artifact.elements_json)
    assert len(elements) > 0

    nodes = json.loads(artifact.extracted_nodes_json)
    assert len(nodes) >= 1
    node_labels = [n.lower() for n in nodes]
    assert any("api" in n or "gateway" in n for n in node_labels)

    # Verify visual revision was committed
    revisions = (
        db_session.query(VisualRevision)
        .filter(VisualRevision.project_id == proj.id)
        .all()
    )
    assert len(revisions) >= 2  # v1 (clean baseline) + v2 (auto-applied architecture)
    latest_rev = max(revisions, key=lambda r: r.revision_number)
    assert latest_rev.revision_number == 2


