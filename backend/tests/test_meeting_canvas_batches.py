"""Batched meeting-canvas plans: coverage for long meetings + short retry."""

from app.schemas.visual_plan import (
    NoteBlock,
    NoteSection,
    NotesDocument,
    VisualNode,
    VisualPlan,
    VisualRelationship,
)
from app.services.meeting_session_intelligence import (
    MEETING_CANVAS_BATCH_SIZE,
    MeetingSessionIntelligenceService,
    _merge_meeting_plans,
)


def _plan(nodes=(), rels=(), sections=(), title="P"):
    return VisualPlan(
        title=title,
        canvas_strategy="mixed",
        nodes=list(nodes),
        relationships=list(rels),
        notes_sections=list(sections),
        prompt_version="v",
    )


def test_merge_single_plan_passthrough():
    plan = _plan(nodes=[VisualNode(id="n1", label="L", evidence_ids=["e1"])])
    assert _merge_meeting_plans([plan], "M") is plan


def test_merge_namespaces_ids_and_remaps_relationships():
    a = _plan(
        nodes=[VisualNode(id="n1", label="A", evidence_ids=["e1"])],
        rels=[VisualRelationship(source="n1", target="n1")],
        sections=[NoteSection(id="s", title="S", blocks=[NoteBlock(id="b", text="t")], order=2)],
    )
    b = _plan(
        nodes=[VisualNode(id="n1", label="B", evidence_ids=["e2"])],
        sections=[NoteSection(id="s", title="S", blocks=[NoteBlock(id="b", text="t2")], order=1)],
    )
    merged = _merge_meeting_plans([a, b], "M")
    node_ids = [n.id for n in merged.nodes]
    assert node_ids == ["m0_n1", "m1_n1"]
    assert [(r.source, r.target) for r in merged.relationships] == [("m0_n1", "m0_n1")]
    assert [s.id for s in merged.notes_sections] == ["m0_s", "m1_s"]
    # Chronological order preserved across batches.
    assert [s.order for s in merged.notes_sections] == [2, 10001]
    assert [blk.id for s in merged.notes_sections for blk in s.blocks] == ["m0_b", "m1_b"]
    assert merged.model == "merged/2-batches"


def test_merge_combines_documents_and_viz():
    from app.schemas.visual_plan import VisualPrimitive, VisualVisualization

    a = _plan()
    a.notes_document = NotesDocument(title="Doc", subtitle="sub", sections=[
        NoteSection(id="s", title="S", blocks=[NoteBlock(id="b", text="t")]),
    ])
    b = _plan()
    b.visualizations = [VisualVisualization(
        id="v", elements=[VisualPrimitive(id="p", primitive_type="rectangle", text="t")],
    )]
    merged = _merge_meeting_plans([a, b], "M")
    assert merged.notes_document is not None
    assert [s.id for s in merged.notes_document.sections] == ["m0_s"]
    assert merged.visualizations[0].id == "m1_v"
    assert merged.visualizations[0].elements[0].id == "m1_p"


def test_batch_size_constant_matches_prompt_cap():
    assert MEETING_CANVAS_BATCH_SIZE == 16


def test_retry_succeeds_on_second_attempt(monkeypatch):
    service = MeetingSessionIntelligenceService()
    calls = {"n": 0}

    class FakePlanner:
        def build_plan(self, **kwargs):
            calls["n"] += 1
            from app.services.meeting_session_intelligence import _merge_meeting_plans  # noqa

            if calls["n"] == 1:
                return _plan(), "deterministic"
            return _plan(), "ai"

    monkeypatch.setattr(
        "app.services.meeting_session_intelligence.VisualPlanService",
        lambda: FakePlanner(),
    )
    monkeypatch.setattr(
        "app.services.meeting_session_intelligence._semantic_provider_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.meeting_session_intelligence.time.sleep", lambda s: None
    )
    import app.models.meeting as meeting_models

    meeting = meeting_models.Meeting(id="mtg_x", title="T")
    merged, overall, info = service._build_canvas_plans(
        meeting=meeting,
        state_summary={},
        current_nodes=[],
        evidence_snippets=[{"id": "e1", "content": "hello"}],
        focus_prompt="focus",
    )
    assert calls["n"] == 2
    assert overall == "ai"
    assert info == {"batches": 1, "batches_ai": 1}


def test_no_retry_without_provider(monkeypatch):
    service = MeetingSessionIntelligenceService()
    calls = {"n": 0}

    class FakePlanner:
        def build_plan(self, **kwargs):
            calls["n"] += 1
            return _plan(), "deterministic"

    monkeypatch.setattr(
        "app.services.meeting_session_intelligence.VisualPlanService",
        lambda: FakePlanner(),
    )
    monkeypatch.setattr(
        "app.services.meeting_session_intelligence._semantic_provider_configured",
        lambda: False,
    )
    import app.models.meeting as meeting_models

    meeting = meeting_models.Meeting(id="mtg_x", title="T")
    _, overall, info = service._build_canvas_plans(
        meeting=meeting,
        state_summary={},
        current_nodes=[],
        evidence_snippets=[{"id": "e1", "content": "hello"}],
        focus_prompt="focus",
    )
    assert calls["n"] == 1
    assert overall == "deterministic"
    assert info == {"batches": 1, "batches_ai": 0}
