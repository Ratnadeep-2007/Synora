"""Batched meeting-canvas plans: coverage for long meetings + short retry."""

from datetime import datetime, timezone
from types import SimpleNamespace

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
    # Same-titled sections collapse into one, blocks chronological.
    assert [s.id for s in merged.notes_sections] == ["m0_s"]
    assert [s.order for s in merged.notes_sections] == [0]
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


def test_discussion_snippets_use_complete_transcript_without_project_filter():
    entries = [
        SimpleNamespace(
            id="entry_2", text="Implement the API worker and queue retry flow.",
            start_time=datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc),
            participant=SimpleNamespace(display_name="SPEAKER_01"), metadata_json="{}",
        ),
        SimpleNamespace(
            id="entry_1", text="Let us discuss the product first.",
            start_time=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            participant=SimpleNamespace(display_name="SPEAKER_00"), metadata_json="{}",
        ),
    ]
    evidence = [SimpleNamespace(
        id="ev_routed", actor_id="SPEAKER_00", source="google_meet",
        content="This routed evidence must not limit the meeting canvas.",
    )]

    snippets = MeetingSessionIntelligenceService._discussion_snippets(entries, evidence)

    assert [snippet["id"] for snippet in snippets] == ["entry_1", "entry_2"]
    assert all(snippet["source"] == "meeting_transcript" for snippet in snippets)
    assert all("project_name" not in snippet for snippet in snippets)
    assert "API worker" in snippets[1]["content"]


def test_minor_filter_drops_only_filler_not_work():
    keep = MeetingSessionIntelligenceService._is_work_discussion
    # Pure filler / casual statements are dropped, in English and Hindi.
    for filler in ("हाँ।", "होगा।", "हम्म।", "चलिए।", "हो गया।", "ok", "Oh wow.", "good morning everyone"):
        assert keep(filler) is False, filler
    # Work/development statements are kept regardless of length or project.
    for work in (
        "Implement the API worker with queue retries and deployment checks.",
        "Excalidraw.",
        "Synora",
        "Agent है।",
        "Pricing for early users needs a decision this week.",
    ):
        assert keep(work) is True, work


def test_global_outline_keeps_late_implementation_context():
    snippets = [
        {"id": f"e{i}", "content": f"Speaker: short note {i}", "source": "meeting_transcript"}
        for i in range(20)
    ]
    snippets.append({
        "id": "late",
        "content": "Speaker: Implement the worker with API retries, queue ordering, deployment checks, and failure alerts.",
        "source": "meeting_transcript",
    })

    outline = MeetingSessionIntelligenceService._global_meeting_outline(snippets, ["SPEAKER_00"])

    assert "Complete discussion size: 21 statements." in outline
    assert "API retries" in outline
    assert "deployment checks" in outline


def test_batch_focus_includes_global_context_without_only_this_part_filter(monkeypatch):
    service = MeetingSessionIntelligenceService()
    focuses = []

    class FakePlanner:
        def build_plan(self, **kwargs):
            focuses.append(kwargs["focus_prompt"])
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

    snippets = [{"id": f"e{i}", "content": f"statement {i}"} for i in range(17)]
    service._build_canvas_plans(
        meeting=meeting_models.Meeting(id="mtg_x", title="T"),
        state_summary={},
        current_nodes=[],
        evidence_snippets=snippets,
        focus_prompt="Freely design implementation notes.",
        global_outline="GLOBAL IMPLEMENTATION CONTEXT",
    )

    assert len(focuses) == 2
    assert "GLOBAL MEETING CONTEXT" in focuses[1]
    assert "GLOBAL IMPLEMENTATION CONTEXT" in focuses[1]
    assert "record ONLY" not in focuses[1]


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
