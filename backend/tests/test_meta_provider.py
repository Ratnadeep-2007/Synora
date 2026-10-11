"""Meta Muse Spark as primary agent branch, Groq as secondary.

The endpoint details are unconfirmed, so these tests never touch the network:
client construction, factory selection order, the free-design prompt variant,
and the compiler grounding flag are all verified locally with stubs.
"""

import pytest

from app.core.config import settings
from app.schemas.visual_plan import VisualNode, VisualPlan
from app.services.excalidraw_compiler import ExcalidrawCompiler
from app.services.llm import (
    DeterministicRuleLLMClient,
    GroqLLMClient,
    MetaLLMClient,
    get_default_llm_client,
)
from app.services.visual_plan_service import VisualPlanService


def _plan() -> VisualPlan:
    return VisualPlan(
        title="t",
        layout_direction="horizontal",
        grouping_intent=[],
        nodes=[
            VisualNode(
                id="n1",
                label="Grounded Service",
                node_type="service",
                evidence_ids=["ev_1"],
                support_type="explicit",
            ),
            VisualNode(
                id="n2",
                label="Imagined Cache",
                node_type="service",
                evidence_ids=[],
                support_type="inferred",
            ),
        ],
        relationships=[],
        preserve=[],
        add=[],
        change=[],
        remove=[],
        notes=[],
    )


def test_meta_client_unconfigured_falls_back_without_network():
    client = MetaLLMClient(api_key="", base_url="", model_name="muse-spark-1.3-contributor")
    assert client._configured() is False
    # Must not raise and must not touch the network.
    from app.services.llm import ExtractionBatchResult

    out = client.generate_structured("anything", ExtractionBatchResult)
    assert isinstance(out, ExtractionBatchResult)


def test_factory_meta_primary_groq_secondary(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "meta")
    monkeypatch.setattr(settings, "META_API_KEY", "test-meta-key")
    monkeypatch.setattr(settings, "META_BASE_URL", "https://meta.example/v1")
    monkeypatch.setattr(settings, "META_MODEL", "muse-spark-1.3-contributor")
    client = get_default_llm_client()
    assert isinstance(client, MetaLLMClient)
    assert client._fallback_client is not None


def test_factory_meta_missing_falls_to_groq(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "meta")
    monkeypatch.setattr(settings, "META_API_KEY", "")
    monkeypatch.setattr(settings, "META_BASE_URL", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-groq-key")
    client = get_default_llm_client()
    assert isinstance(client, GroqLLMClient)


def test_factory_meta_missing_nothing_configured_is_deterministic(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "meta")
    monkeypatch.setattr(settings, "META_API_KEY", "")
    monkeypatch.setattr(settings, "META_BASE_URL", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "")
    client = get_default_llm_client()
    assert isinstance(client, DeterministicRuleLLMClient)


def test_free_prompt_has_no_boilerplate_ban():
    svc = VisualPlanService()
    prompt = svc._build_prompt(
        {"title": "Demo"}, ["Existing"], ["snippet"], None, None, free=True
    )
    assert "DESIGN FREEDOM" in prompt
    assert "no fixed taxonomy for visual form" in prompt
    assert "NEVER provide x, y, position" in prompt


def test_grounded_prompt_unchanged(monkeypatch):
    from app.core.config import settings as cfg

    monkeypatch.setattr(cfg, "VISUAL_DESIGN_MODE", "grounded")
    svc = VisualPlanService()
    prompt = svc._build_prompt(
        {"title": "Demo"}, ["Existing"], ["snippet"], None, None, free=False
    )
    assert "GROUNDING: cite evidence_ids" in prompt
    assert "CONTENT AND REPRESENTATION ARE OPEN-ENDED" in prompt


def test_compiler_free_mode_keeps_ungrounded_nodes():
    elements = ExcalidrawCompiler().compile(_plan(), enforce_grounding=False)
    labels = json_labels(elements)
    assert any("Grounded Service" in label for label in labels)
    assert any("Imagined Cache" in label for label in labels)


def test_compiler_enforce_mode_drops_ungrounded_nodes():
    elements = ExcalidrawCompiler().compile(_plan(), enforce_grounding=True)
    labels = json_labels(elements)
    assert any("Grounded Service" in label for label in labels)
    assert not any("Imagined Cache" in label for label in labels)


def test_visual_design_free_flag(monkeypatch):
    monkeypatch.setattr(settings, "VISUAL_DESIGN_MODE", "free")
    assert settings.visual_design_free is True
    monkeypatch.setattr(settings, "VISUAL_DESIGN_MODE", "grounded")
    assert settings.visual_design_free is False


def test_free_mode_applies_despite_critique(db_session, monkeypatch):
    """Mirror of the grounded critique-gate test: in free mode the agent owns
    the result, so critique findings are recorded but do not block."""
    import app.services.visual_critique_service as critique_mod
    from app.core.config import settings as cfg
    from app.models.project import Project
    from app.services.excalidraw_service import ExcalidrawService

    class _AlwaysFailsCritique:
        def critique(self, plan, elements):
            from app.schemas.visual_plan import VisualCritique

            return VisualCritique(ok=False, issues=["overlaps badly"])

    monkeypatch.setattr(critique_mod, "VisualCritiqueService", _AlwaysFailsCritique)
    monkeypatch.setattr(cfg, "VISUAL_DESIGN_MODE", "free")

    db_session.add(
        Project(id="proj_free_gate", workspace_id="ws_default", name="Free Gate")
    )
    db_session.commit()

    result = ExcalidrawService().generate_diagram_from_text(
        project_id="proj_free_gate",
        text="the client calls the API which writes to the database",
        db=db_session,
        auto_apply=True,
    )
    assert result["critique_ok"] is False
    assert result["critique_issues"]
    assert result["auto_applied"] is True


def json_labels(elements):
    out = []
    for el in elements:
        if el.get("type") == "text":
            out.append(str(el.get("text", "")))
    return out
