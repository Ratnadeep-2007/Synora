"""Mem0 per plan.md: provider interface, proactive patterns, adoption gate.

Canonical memory stays in Synora's DB. Mem0 is an optional adapter that
mirrors only provenance-linked claims and must degrade to unavailable —
never fabricate — without a key/SDK.
"""
import json

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.context_resolution import UnknownContextItem, UnknownItemStatus
from app.models.intelligence import CandidateKnowledge
from app.models.project import Project
from app.models.project_state import ProjectState
from app.services import memory_provider
from app.services.memory_provider import (
    Mem0AdapterProvider,
    MemoryProviderUnavailable,
    SynoraNativeProvider,
    get_retrieval_provider,
)
from app.services.proactive_memory import ProactiveMemoryService, detect_intent


def _project(db: Session, project_id: str, name: str, description: str = "") -> Project:
    project = Project(id=project_id, workspace_id="ws_default", name=name, description=description, is_system=False)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _claim(db: Session, claim_id: str, project_id: str, title: str, content: str, status: str = "approved", evidence=("ev_1",)):
    claim = CandidateKnowledge(
        id=claim_id, project_id=project_id, title=title, content=content,
        category="knowledge", classification="Requirement", status=status,
        evidence_ids_json=json.dumps(list(evidence)),
    )
    db.add(claim)
    db.commit()
    return claim


def test_native_provider_paraphrase_and_scope(db_session: Session):
    _project(db_session, "proj_mem_a", "SolarRickshaw")
    _project(db_session, "proj_mem_b", "PaaniMeter")
    _claim(db_session, "claim_swap", "proj_mem_a", "Swap station placement",
           "Battery exchange station locations are planned near market")
    _claim(db_session, "claim_sms", "proj_mem_b", "SMS alert",
           "SMS alert to sarpanch before the water tank empties")
    _claim(db_session, "claim_old", "proj_mem_a", "Old vendor", "Rejected vendor plan", status="superseded")

    provider = SynoraNativeProvider()
    hits = provider.search(db_session, "proj_mem_a", "swap map locations")
    assert hits and hits[0]["claim_id"] == "claim_swap"
    assert hits[0]["evidence_ids"] == ["ev_1"]

    # Scope isolation: PaaniMeter content never leaks into SolarRickshaw.
    hits_b = provider.search(db_session, "proj_mem_a", "SMS alert sarpanch tank")
    assert all(hit["project_id"] == "proj_mem_a" for hit in hits_b)
    assert not any(hit.get("claim_id") == "claim_sms" for hit in hits_b)
    # Inactive claims are not surfaced.
    assert not any(hit.get("claim_id") == "claim_old" for hit in provider.search(db_session, "proj_mem_a", "rejected vendor"))


def test_mem0_adapter_unavailable_without_key(db_session: Session, monkeypatch):
    monkeypatch.setattr(settings, "MEM0_API_KEY", "")
    adapter = Mem0AdapterProvider()
    assert adapter.health()["available"] is False
    claim = _claim(db_session, "claim_x", "proj_mem_a", "T", "Content")
    with pytest.raises(MemoryProviderUnavailable):
        adapter.search(db_session, "proj_mem_a", "anything")
    with pytest.raises(MemoryProviderUnavailable):
        adapter.mirror_claim(claim)


def test_mem0_adapter_refuses_unprovenanced_claims(db_session: Session, monkeypatch):
    monkeypatch.setattr(settings, "MEM0_API_KEY", "test-key")

    class FakeMem0:
        def add(self, messages, user_id=None, metadata=None):
            return {"results": [{"id": "m1"}]}

    adapter = Mem0AdapterProvider(client=FakeMem0())
    orphan = _claim(db_session, "claim_orphan", "proj_mem_a", "T", "No evidence", evidence=())
    with pytest.raises(MemoryProviderUnavailable):
        adapter.mirror_claim(orphan)


def test_factory_falls_back_to_native(db_session: Session, monkeypatch):
    monkeypatch.setattr(settings, "MEMORY_PROVIDER", "mem0")
    monkeypatch.setattr(settings, "MEM0_API_KEY", "")
    assert get_retrieval_provider().name == "synora"
    health = memory_provider.provider_health()
    assert health["active"] == "synora"
    assert health["mem0"]["available"] is False


def test_detect_intent_gate():
    assert detect_intent("ok")["decision"] == "NO_DEMAND"
    assert detect_intent("thanks, that makes sense")["decision"] == "NO_DEMAND"
    demand = detect_intent("Check battery swap station wala purana decision")
    assert demand["decision"] == "DEMAND" and demand["query"]
    assert detect_intent("where we left off on the dashboard?")["decision"] == "DEMAND"


def test_detect_intent_regex_overrides_hedged_llm():
    class HedgingClient:
        def generate_structured(self, prompt, schema):
            return schema(decision="NO_DEMAND", query=None)

    result = detect_intent("fix the auth error in login.py", llm_client=HedgingClient())
    assert result["decision"] == "DEMAND"
    assert result["source"] == "regex_fallback"


def test_session_start_scan_and_hint_refresh_idempotent(db_session: Session):
    _project(db_session, "proj_mem_a", "SolarRickshaw")
    db_session.add(ProjectState(
        project_id="proj_mem_a", current_version=2, title="SolarRickshaw",
        decisions_json=json.dumps([{"title": "Use battery swap model"}]),
        open_questions_json=json.dumps([{"title": "Which towns first?"}]),
        constraints_json=json.dumps([]), requirements_json=json.dumps([]),
        architecture_json=json.dumps([]), assumptions_json=json.dumps([]),
        agent_workflow_json=json.dumps([]),
    ))
    db_session.commit()

    service = ProactiveMemoryService(provider=SynoraNativeProvider())
    first = service.refresh_hints(db_session, "proj_mem_a")
    second = service.refresh_hints(db_session, "proj_mem_a")
    assert first["created"] >= 1 and second["created"] == 0

    scan = service.session_start_scan(db_session, "proj_mem_a", user_id="usr_1")
    assert scan["blockers"] == ["Which towns first?"]
    assert scan["active_decisions"] == ["Use battery swap model"]
    assert scan["hints"]
    again = service.session_start_scan(db_session, "proj_mem_a", user_id="usr_1")
    assert again["suppressed"] is True  # cooldown: do not fire every open


def test_project_created_suggests_but_never_assigns(db_session: Session):
    item = UnknownContextItem(
        id="unk_proactive_1", project_id="proj_unknown_context", tenant_id="default_tenant",
        source="whatsapp", actor_id="sender", content="Battery swap station locations for rickshaw fleet",
        status=UnknownItemStatus.PENDING.value,
    )
    db_session.add(item)
    db_session.commit()

    project = _project(db_session, "proj_new_solar", "SolarRickshaw Fleet", "Battery swap stations for e-rickshaw fleet")
    result = ProactiveMemoryService().on_project_created(db_session, project)
    assert result["suggested"] == 1

    from app.models.context_resolution import PossibleProjectMatch
    match = db_session.query(PossibleProjectMatch).filter_by(unknown_item_id=item.id).first()
    assert match is not None and match.candidate_project_id == project.id
    db_session.refresh(item)
    assert item.status == UnknownItemStatus.PENDING.value  # still human's call
    # Idempotent: a second scan adds no duplicate suggestion.
    assert ProactiveMemoryService().on_project_created(db_session, project)["suggested"] == 0
