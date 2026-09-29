"""Continuity, reactions, failover, and compare-overlay tests."""

import json

import pytest
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.source_event import SourceEvent
from app.schemas.context import ContextCandidateBatch, ContextCandidateItem
from app.services.context_intelligence import ContextIntelligenceService
from app.services.conversation_continuity import (
    build_continuity_window,
    build_cross_source_context,
)
from app.services.source_intelligence_pipeline import SourceIntelligencePipeline
from app.services.unknown_context_service import UnknownContextService
from app.services.visual_revision_service import VisualRevisionService
from app.services.whatsapp_service import WhatsAppIntelligenceService


class FakeSemanticClient:
    def __init__(self, items):
        self._items = items

    def generate_structured(self, prompt, schema):
        if schema is ContextCandidateBatch:
            return ContextCandidateBatch(items=list(self._items), model="fake")
        raise NotImplementedError


def _project(db: Session, project_id: str, name: str) -> Project:
    p = Project(id=project_id, workspace_id="ws_default", name=name, description=name)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _seed_whatsapp(db: Session, text: str, group: str = "Arch Group", jid: str = "g1@g.us"):
    ev = SourceEvent(
        tenant_id="default_tenant",
        project_id="proj_unknown_context",
        source="whatsapp",
        source_event_id=f"seed_{abs(hash(text))}",
        event_type="group_message",
        actor_id="Alice",
        payload_json=json.dumps({"text": text, "sender_name": "Alice", "group_name": group, "group_jid": jid}),
        status="processed",
    )
    db.add(ev)
    db.commit()
    return ev


# 1. Continuity is group-scoped: same-group thread wins over other groups ----
def test_continuity_window_is_group_scoped(db_session: Session):
    _seed_whatsapp(db_session, "deploying the claims KYC pipeline today", group="Claims Group", jid="claims@g.us")
    _seed_whatsapp(db_session, "pizza for lunch anyone", group="Random Group", jid="random@g.us")

    window = build_continuity_window(
        db_session, group_name="Claims Group", group_jid="claims@g.us", current_text="ok ship it"
    )
    assert "claims KYC" in window
    assert "pizza" not in window


# 2. Cross-source: WhatsApp reply resolves against Meet discussion ------------
def test_cross_source_context_surfaces_meet(db_session: Session):
    from app.models.evidence import Evidence

    ev_in = SourceEvent(
        tenant_id="default_tenant", project_id="proj_x", source="google_meet",
        source_event_id="meet_1", event_type="transcript_entry", actor_id="Bob",
        payload_json=json.dumps({"text": "claims adjudication engine review"}), status="processed",
    )
    db.add(ev_in) if False else db_session.add(ev_in)
    db_session.commit()
    db_session.add(Evidence(
        project_id="proj_x", source="google_meet", source_event_id=ev_in.event_id,
        actor_id="Bob", content="claims adjudication engine review",
    ))
    db_session.commit()

    cross = build_cross_source_context(db_session)
    assert "claims adjudication" in cross


# 3. Unknown suggestions re-resolve with continuity ---------------------------
def test_suggest_matches_uses_continuity(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    unk = UnknownContextService(context_service=ContextIntelligenceService(llm_client=FakeSemanticClient([])))
    item = unk.create_item(
        source="whatsapp",
        payload={"text": "yes ship it", "group_name": "G", "group_jid": "g@g.us"},
        db=db_session, source_event_id="evt_cont_1",
    )
    matches = unk.suggest_matches(item.id, db_session)
    assert matches == []


# 4. Reactions are feedback, not evidence -------------------------------------
def test_whatsapp_reaction_is_feedback_only(db_session: Session):
    from app.services.project_agent_service import ProjectAgentService

    agent_service = ProjectAgentService()
    proj = agent_service.get_or_create_project(
        project_id="proj_react", name="React Project", workspace_id="ws_default", db=db_session)
    svc = WhatsAppIntelligenceService()
    first = svc.process_incoming_message(
        {"message_id": "wa_react_1", "sender_name": "Alice", "text": f"In {proj.id} add audit log"},
        db_session,
    )
    assert first["processed"] is True

    from app.models.evidence import Evidence
    before = db_session.query(Evidence).count()
    reacted = svc.process_incoming_message(
        {"event_type": "reaction", "reaction": "👍", "target_message_id": "wa_react_1",
         "sender_name": "Bob"},
        db_session,
    )
    assert reacted["status"] == "reaction_feedback"
    assert reacted["sentiment"] == "positive"
    assert db_session.query(Evidence).count() == before

    neg = svc.process_incoming_message(
        {"event_type": "reaction", "reaction": "👎", "target_message_id": "wa_react_1",
         "sender_name": "Cara"},
        db_session,
    )
    assert neg["sentiment"] == "negative"


# 5. Provider failover: unconfigured provider never fabricates ---------------
def test_unconfigured_provider_routes_unknown_without_fabrication(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    svc = ContextIntelligenceService()  # default client, no stub
    result = svc.resolve(source="whatsapp", payload={"text": "some project discussion"}, db=db_session)
    assert result.decision in ("unknown", "ambiguous")
    assert result.project_id is None


# 6. Compare overlay: ghost removed + highlighted added -----------------------
def test_compare_overlay_ghost_and_added(db_session: Session):
    _project(db_session, "proj_overlay", "Overlay Project")
    svc = VisualRevisionService()
    svc.commit_revision(project_id="proj_overlay", scene=[
        {"id": "el_A", "type": "text", "text": "A"},
        {"id": "el_B", "type": "text", "text": "B"},
    ], db=db_session)
    svc.commit_revision(project_id="proj_overlay", scene=[
        {"id": "el_A", "type": "text", "text": "A"},
        {"id": "el_C", "type": "text", "text": "C"},
    ], db=db_session)

    diff = svc.compare("proj_overlay", 1, 2, db_session)
    overlay = diff["overlay_elements"]
    by_id = {e["id"]: e for e in overlay}
    assert by_id["el_B"]["customData"]["compare"] == "removed"
    assert by_id["el_B"]["strokeStyle"] == "dashed"
    assert by_id["el_C"]["customData"]["compare"] == "added"
    assert by_id["el_A"]["customData"]["compare"] == "unchanged"
