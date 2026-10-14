"""Regression cases for retrieval quality, evidence scope, and context size."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.models.project import Project
from app.models.source_event import SourceEvent
from app.models.workspace_membership import WorkspaceMembership
from app.services.agent_context_packer import pack_agent_context, serialized_bytes
from app.services.context_builder import ContextBuilder
from app.services.excalidraw_service import ExcalidrawService
from app.services.project_memory_service import ProjectMemoryService
from app.services.project_state_service import ProjectStateService
from app.services.visual_plan_service import VisualPlanService


def seed_claim(db, key, text, *, project_id="proj_retrieval", tenant_id="tenant_alpha",
               status="approved", classification="Requirement", age=0, title=None):
    created = datetime.now(timezone.utc) - timedelta(days=age)
    event = SourceEvent(event_id=f"evt_{key}", source_event_id=f"msg_{key}",
                        project_id=project_id, tenant_id=tenant_id, source="whatsapp",
                        payload_json=json.dumps({"text": text}))
    evidence = Evidence(id=f"ev_{key}", project_id=project_id, source="whatsapp",
                        source_event_id=event.event_id, content=text,
                        created_at=created, occurred_at=created)
    claim = CandidateKnowledge(id=f"cand_{key}", project_id=project_id,
                               category="requirement_candidate", classification=classification,
                               title=title or text[:80], content=text, status=status,
                               evidence_ids_json=json.dumps([evidence.id]), created_at=created)
    db.add_all([event, evidence, claim])
    db.flush()
    return claim, evidence


def test_old_context_survives_recent_single_word_matches(db_session):
    old, source = seed_claim(db_session, "old_map", "Drivers need a live map of battery exchange station locations.", age=300)
    for index in range(190):
        seed_claim(db_session, f"recent_{index}", f"Station hardware inspection batch {index}.", age=1)
    memory = ProjectMemoryService().build_context(
        "proj_retrieval", db_session, tenant_id="tenant_alpha",
        query="Where is the live swap station map?", limit_knowledge=3, limit_evidence=3,
    )
    assert memory["knowledge"][0]["id"] == old.id
    assert memory["evidence"][0]["id"] == source.id
    assert source.id in memory["knowledge"][0]["evidence_ids"]
    assert memory["retrieval"]["strategy"] == "lexical_expansion"


def test_pending_rejected_and_superseded_are_not_agent_memory(db_session):
    for status in ("approved", "candidate", "rejected", "superseded"):
        seed_claim(db_session, f"status_{status}", f"Battery service requirement {status}.", status=status)
    seed_claim(db_session, "inactive_class", "Retired battery system.", classification="Superseded")
    builder = ContextBuilder()
    context = builder.build_agent_context("proj_retrieval", "tech_agent", db_session, tenant_id="tenant_alpha")
    assert [item["id"] for item in context["knowledge"]] == ["cand_status_approved"]
    history = ProjectMemoryService().build_context(
        "proj_retrieval", db_session, tenant_id="tenant_alpha", include_history=True,
    )
    assert {item["status"] for item in history["knowledge"]} >= {"approved", "candidate", "rejected", "superseded"}


def test_retrieval_does_not_expose_other_projects_or_source_tenants(db_session):
    own, own_source = seed_claim(db_session, "own", "Battery map for authorized team.")
    seed_claim(db_session, "other_tenant", "Battery map SECRET TENANT VALUE", tenant_id="tenant_bravo")
    seed_claim(db_session, "other_project", "Battery map SECRET PROJECT VALUE", project_id="proj_elsewhere")
    db_session.add(CandidateKnowledge(
        id="cand_unscoped", project_id="proj_retrieval", category="requirement_candidate",
        title="Battery map", content="SECRET ORPHAN VALUE", status="candidate", evidence_ids_json="[]",
    ))
    db_session.flush()
    memory = ProjectMemoryService().build_context("proj_retrieval", db_session, tenant_id="tenant_alpha", query="battery map")
    assert [item["id"] for item in memory["knowledge"]] == [own.id]
    assert [item["id"] for item in memory["evidence"]] == [own_source.id]
    assert "SECRET" not in json.dumps(memory)


def test_duplicate_claims_keep_all_corroborating_evidence(db_session):
    first, source_a = seed_claim(db_session, "corroboration_a", "Drivers need a battery map.")
    second, source_b = seed_claim(db_session, "corroboration_b", "Drivers need a battery map.")
    memory = ProjectMemoryService().build_context("proj_retrieval", db_session, tenant_id="tenant_alpha")
    assert len(memory["knowledge"]) == 1
    assert set(memory["knowledge"][0]["evidence_ids"]) == {source_a.id, source_b.id}
    assert db_session.query(CandidateKnowledge).filter(CandidateKnowledge.id.in_([first.id, second.id])).count() == 2


def test_repeated_statement_adds_sources_without_another_state_item(db_session):
    first, source_a = seed_claim(db_session, "state_a", "Drivers need a battery map.", title="Battery map")
    second, source_b = seed_claim(db_session, "state_b", "Drivers need a battery map.", title="Battery map")
    service = ProjectMemoryService()
    service.apply_candidates("proj_retrieval", [first], db_session)
    before = ProjectStateService().get_or_create_state("proj_retrieval", db_session).current_version
    service.apply_candidates("proj_retrieval", [second], db_session)
    state = ProjectStateService().get_or_create_state("proj_retrieval", db_session)
    rows = json.loads(state.requirements_json)
    assert len(rows) == 1
    assert set(rows[0]["evidence_ids"]) == {source_a.id, source_b.id}
    assert state.current_version == before + 1
    service.apply_candidates("proj_retrieval", [second], db_session)
    assert state.current_version == before + 1


def test_long_context_is_bounded_and_keeps_relevant_source_window(db_session):
    text = "Unrelated operational notes. " * 700 + "Battery exchange station map must update live." + " Historical appendix." * 700
    claim, evidence = seed_claim(db_session, "long_source", text)
    state = ProjectStateService().get_or_create_state("proj_retrieval", db_session)
    state.current_version = 3
    state.decisions_json = json.dumps([{"id": "dec_approved", "text": "Use PostgreSQL", "evidence_ids": [evidence.id]}])
    state.requirements_json = json.dumps([{"id": f"req_{i}", "content": "Many unrelated requirements. " * 50} for i in range(100)])
    db_session.commit()
    context = ContextBuilder().build_agent_context(
        "proj_retrieval", "tech_agent", db_session, tenant_id="tenant_alpha",
        query="live swap station map", token_budget=3000,
    )
    assert serialized_bytes(context) <= 9000
    assert context["context_metadata"]["estimated_tokens"] <= 3000
    assert not context["context_metadata"]["complete"]
    assert context["context_metadata"]["omitted_items"]
    assert context["project_state"]["decisions"][0]["id"] == "dec_approved"
    assert "Battery exchange station map" in context["evidence"][0]["text"]
    assert context["evidence"][0]["id"] == evidence.id
    assert context["evidence"][0]["excerpt"]["start"] > 0
    assert "project_memory" not in context
    db_session.refresh(evidence)
    db_session.refresh(state)
    assert evidence.content == text
    assert state.current_version == 3
    assert len(json.loads(state.requirements_json)) == 100


def test_unmatched_query_does_not_return_arbitrary_recent_hits(db_session):
    seed_claim(db_session, "unrelated", "Drivers need a battery map.")
    memory = ProjectMemoryService().build_context("proj_retrieval", db_session, tenant_id="tenant_alpha", query="quantum encryption")
    assert memory["knowledge"] == []
    assert memory["evidence"] == []


def test_database_alias_keeps_product_name_intact(db_session):
    claim, evidence = seed_claim(db_session, "postgres", "Use Postgres for durable project storage.")
    memory = ProjectMemoryService().build_context(
        "proj_retrieval", db_session, tenant_id="tenant_alpha", query="PostgreSQL storage",
    )
    assert memory["knowledge"][0]["id"] == claim.id
    assert memory["evidence"][0]["id"] == evidence.id


def test_budget_accounts_for_unicode_and_oversized_prior_runs():
    context = {"tenant_id": "tenant_alpha", "project_id": "proj_retrieval", "state_version": 1,
               "project_state": {"project_id": "proj_retrieval", "version": 1, "vision": chr(0x092D) * 2000,
                                 "decisions": [{"id": "dec_1", "text": "Use PostgreSQL"}]},
               "knowledge": [], "evidence": [],
               "prior_agent_outputs": [{"execution_id": "run_1", "payload": {"blob": "x" * 40000}}]}
    packed = pack_agent_context(context, token_budget=1024)
    assert serialized_bytes(packed) <= 3072
    assert packed["context_metadata"]["omitted_items"]["prior_agent_outputs"] == 1
    assert packed["project_state"]["decisions"][0]["id"] == "dec_1"


def test_focused_canvas_planning_uses_old_real_evidence(db_session):
    project = Project(id="proj_retrieval", workspace_id="ws_default", name="SolarRickshaw")
    db_session.add(project)
    claim, evidence = seed_claim(db_session, "canvas_old", "The live battery exchange station map needs location updates.",
                                age=200, tenant_id="default_tenant")
    for index in range(20):
        seed_claim(db_session, f"canvas_recent_{index}", "Driver profile details need review.", tenant_id="default_tenant")

    class CapturingPlanner:
        model_name = "test-visual"
        prompt = ""

        def generate_visual_plan(self, prompt):
            self.prompt = prompt
            return json.dumps({"title": "Battery map", "nodes": [
                {"id": "battery_map", "label": "Live battery map", "node_type": "service", "evidence_ids": [evidence.id]}
            ], "relationships": []})

    client = CapturingPlanner()
    proposal, artifact = ExcalidrawService().generate_ai_visual_architecture(
        project.id, db_session, focus_prompt="live swap station map",
        visual_plan_service=VisualPlanService(client=client),
    )
    assert evidence.id in client.prompt
    assert evidence.id in json.loads(proposal.evidence_ids_json)
    assert artifact is not None


def test_memory_briefing_endpoint_and_missing_project(client, db_session, test_user):
    db_session.add(Project(id="proj_retrieval", workspace_id="ws_default", name="SolarRickshaw"))
    claim, evidence = seed_claim(db_session, "briefing", "Drivers need a battery map.", tenant_id="default_tenant")
    ProjectMemoryService().apply_candidates("proj_retrieval", [claim], db_session)
    response = client.get("/projects/proj_retrieval/memory/briefing", headers={"X-User-ID": test_user.id})
    assert response.status_code == 200
    data = response.json()
    assert data["knowledge"][0]["status"] == "approved"
    assert data["evidence"][0]["id"] == evidence.id
    assert data["context_metadata"]["complete"]
    response = client.get("/projects/proj_missing/memory", headers={"X-User-ID": test_user.id})
    assert response.status_code == 404


def test_memory_access_requires_membership_of_actual_workspace(db_session, test_user, monkeypatch):
    from app.api.deps import get_accessible_memory_project
    from app.core.config import settings

    db_session.add(Project(id="proj_private", workspace_id="ws_private", name="Private"))
    db_session.flush()
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    with pytest.raises(HTTPException) as denied:
        get_accessible_memory_project("proj_private", db_session, test_user)
    assert denied.value.status_code == 403
    membership = WorkspaceMembership(workspace_id="ws_private", user_id=test_user.id, status="pending")
    db_session.add(membership)
    db_session.flush()
    with pytest.raises(HTTPException):
        get_accessible_memory_project("proj_private", db_session, test_user)
    membership.status = "active"
    db_session.flush()
    assert get_accessible_memory_project("proj_private", db_session, test_user).id == "proj_private"
