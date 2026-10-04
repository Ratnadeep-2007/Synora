"""
Regression coverage for knowledge-note grounding and ordering.

Two defects motivated this file:

1. Knowledge cards filled every narrative stage from the same string, so a
   single-sentence candidate rendered BEHAVIOUR as a copy of REQUIREMENT and
   invented "Acceptance" for VALIDATE.
2. Visual plan notes were rendered in whatever order the model returned them,
   and a note that declared no evidence was rendered as if it were a
   directive. The notes header id used the builtin hash(), which is salted
   per interpreter and therefore changed on every backend restart.
"""

from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship
from app.services.excalidraw_compiler import ExcalidrawCompiler
from app.services.workspace_atlas_service import WorkspaceAtlasService


def _stages(category: str, title: str, content: str):
    svc = WorkspaceAtlasService.__new__(WorkspaceAtlasService)
    return {s["label"]: s["detail"] for s in svc._mini_visual_stages(category, title, content)}


def test_terse_requirement_does_not_repeat_itself():
    """A one-clause candidate must not echo itself into every stage."""
    stages = _stages(
        "REQUIREMENT",
        "Add an agentic layer for NLP embedding.",
        "Add an agentic layer for NLP embedding.",
    )
    assert stages["BEHAVIOUR"] == "Not specified"
    assert stages["VALIDATE"] == "Not specified"
    assert stages["NEED"] == "Not specified"
    # The only populated stage is the requirement itself.
    assert stages["REQUIREMENT"].startswith("Add an agentic")
    populated = [v for v in stages.values() if v != "Not specified"]
    assert len(populated) == 1


def test_rich_decision_fills_every_stage_distinctly():
    """A multi-sentence decision populates all four stages with distinct text."""
    stages = _stages(
        "DECISION",
        "Migrate session storage to Redis",
        "Peak load is causing latency. "
        "We will move sessions to Redis. "
        "Sessions must degrade gracefully.",
    )
    assert stages["SITUATION"].startswith("Peak load")
    assert stages["CHOICE"].startswith("Migrate session")
    assert stages["REASON"].startswith("We will move")
    assert stages["CONSEQUENCE"].startswith("Sessions must")

    values = list(stages.values())
    assert len(set(values)) == len(values), "stages must not repeat one another"
    assert "Not specified" not in values


def test_clause_equal_to_title_is_discarded():
    """Content that merely restates the title is not a distinct clause."""
    stages = _stages(
        "REQUIREMENT",
        "Auth must support OTP login",
        "Auth must support OTP login",
    )
    assert stages["NEED"] == "Not specified"
    assert stages["BEHAVIOUR"] == "Not specified"


def _plan(notes):
    return VisualPlan(
        title="Test Plan",
        layout_direction="horizontal",
        nodes=[
            VisualNode(id="a", label="Bot", node_type="client", evidence_ids=["ev_1"]),
            VisualNode(id="b", label="Layer", node_type="service", evidence_ids=["ev_1"]),
        ],
        relationships=[VisualRelationship(source="a", target="b")],
        notes=notes,
    )


def _note_texts(elements):
    texts = [e for e in elements if e["id"].startswith("sticky_text_")]
    return [e["text"] for e in sorted(texts, key=lambda x: int(x["id"].split("_")[-1]))]


def test_note_declaring_empty_evidence_is_dropped():
    """A note that claims evidence but lists none is an invention."""
    scene = ExcalidrawCompiler().compile(
        _plan(
            [
                {"text": "use OpenAI embeddings", "kind": "decision", "evidence_ids": []},
                {"text": "Auth must support OTP", "kind": "requirement", "evidence_ids": ["ev_2"]},
            ]
        )
    )
    texts = _note_texts(scene)
    assert not any("OpenAI" in t for t in texts)
    assert any("OTP" in t for t in texts)


def test_notes_are_ordered_by_kind_then_order():
    """Notes render as decision -> requirement -> directive -> risk -> note."""
    scene = ExcalidrawCompiler().compile(
        _plan(
            [
                {"text": "Risk: rate limits", "kind": "risk", "order": 1, "evidence_ids": ["ev_1"]},
                {"text": "Directive: ship behind flag", "kind": "directive", "order": 0, "evidence_ids": ["ev_3"]},
                {"text": "Decision: use Redis", "kind": "decision", "order": 1, "evidence_ids": ["ev_4"]},
                {"text": "Requirement: OTP login", "kind": "requirement", "order": 0, "evidence_ids": ["ev_2"]},
                "plain string note",
            ]
        )
    )
    texts = _note_texts(scene)
    assert len(texts) == 5
    order = ["Decision" in texts[0], "Requirement" in texts[1], "Directive" in texts[2], "Risk" in texts[3]]
    assert all(order), f"unexpected ordering: {texts}"


def test_notes_header_id_is_stable_across_processes():
    """
    The header id must not use the builtin hash(), which Python salts per
    interpreter. That made the id change on every backend restart and showed
    up as a spurious remove+add pair in compare mode.
    """
    plan = _plan([{"text": "a note", "kind": "note", "evidence_ids": ["ev_1"]}])
    first = [e["id"] for e in ExcalidrawCompiler().compile(plan) if e["id"].startswith("lbl_notes_hdr_")]
    second = [e["id"] for e in ExcalidrawCompiler().compile(plan) if e["id"].startswith("lbl_notes_hdr_")]
    assert first == second
    assert len(first) == 1
    # All-hex suffix derived from a digest, not a salted integer.
    assert all(ch in "0123456789abcdef" for ch in first[0].rsplit("_", 1)[-1])


def test_compile_remains_idempotent():
    plan = _plan([{"text": "note one", "kind": "decision", "evidence_ids": ["ev_1"]}])
    a = [e["id"] for e in ExcalidrawCompiler().compile(plan)]
    b = [e["id"] for e in ExcalidrawCompiler().compile(plan)]
    assert a == b