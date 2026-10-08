"""Regression coverage for the V2 living project notebook canvas."""

from app.schemas.visual_plan import (
    VisualNoteSection,
    VisualPlan,
    VisualVisualization,
)
from app.services.excalidraw_compiler import ExcalidrawCompiler


def test_text_first_notes_render_as_a_document_page():
    plan = VisualPlan(
        title="Project Notebook",
        canvas_strategy="text",
        notes_sections=[
            VisualNoteSection(
                id="overview",
                title="Overview",
                body="This project is maintained from persisted project memory.",
                bullets=["Keep the notes readable.", "Do not force a diagram."],
            ),
            VisualNoteSection(
                id="decisions",
                title="Key Decisions",
                bullets=["Use text when relationships are not meaningful."],
                order=1,
            ),
        ],
    )

    scene = ExcalidrawCompiler().compile(plan)
    visual_types = [
        (e.get("customData") or {}).get("visual", {}).get("type")
        for e in scene
    ]

    assert "project_notes_page" in visual_types
    assert "note_section_body" in visual_types
    assert any(e["id"].startswith("lbl_notes_hdr_") for e in scene)
    # The visible note representation is no longer a sticky-note rectangle.
    assert not any(
        t == "architectural_note" and e.get("type") == "rectangle"
        for e, t in zip(scene, visual_types)
    )


def test_lightweight_visualization_can_coexist_with_text_notes():
    plan = VisualPlan(
        title="Mixed Canvas",
        notes_sections=[
            VisualNoteSection(
                id="summary",
                title="Summary",
                body="The project is currently stable.",
            )
        ],
        visualizations=[
            VisualVisualization(
                id="health",
                kind="status",
                title="Project Health",
                value="Stable",
            )
        ],
    )

    scene = ExcalidrawCompiler().compile(plan)

    assert any(
        (e.get("customData") or {}).get("visual", {}).get("type")
        == "freeform_visual_frame"
        for e in scene
    )
    assert any(
        e.get("type") == "text" and "Stable" in (e.get("text") or "")
        for e in scene
    )


def test_text_only_plan_is_valid_without_nodes():
    plan = VisualPlan(
        title="Text Only",
        canvas_strategy="text",
        notes_sections=[
            VisualNoteSection(
                id="notes",
                title="Notes",
                body="No meaningful diagram exists yet.",
            )
        ],
    )

    scene = ExcalidrawCompiler().compile(plan)
    assert scene
    assert not any(e["id"].startswith("node_") for e in scene)
    assert not any(e["type"] == "arrow" for e in scene)


def test_genuine_diagram_still_renders_in_mixed_canvas():
    from app.schemas.visual_plan import VisualNode, VisualRelationship

    plan = VisualPlan(
        title="Architecture",
        canvas_strategy="mixed",
        nodes=[
            VisualNode(id="a", label="Client", node_type="client", evidence_ids=["ev_1"]),
            VisualNode(id="b", label="API", node_type="service", evidence_ids=["ev_1"]),
        ],
        relationships=[
            VisualRelationship(
                source="a",
                target="b",
                evidence_ids=["ev_1"],
            )
        ],
        notes_sections=[
            VisualNoteSection(
                id="overview",
                title="Overview",
                body="The client sends requests to the API.",
            )
        ],
    )

    scene = ExcalidrawCompiler().compile(plan)
    assert any(e["id"] == "node_a" for e in scene)
    assert any(e["type"] == "arrow" for e in scene)
    assert any(
        (e.get("customData") or {}).get("visual", {}).get("type")
        == "project_notes_page"
        for e in scene
    )
