"""Regression coverage for the open-ended V2 notebook + visual model."""

from app.schemas.visual_plan import (
    NoteBlock,
    NoteSection,
    NotesDocument,
    VisualPlan,
    VisualVisualization,
)
from app.services.excalidraw_compiler import ExcalidrawCompiler


def test_notes_document_supports_rich_blocks():
    doc = NotesDocument(
        title="Project Notes",
        sections=[
            NoteSection(
                id="status",
                title="Current Status",
                blocks=[
                    NoteBlock(
                        id="summary",
                        block_type="paragraph",
                        text="The project is entering integration testing.",
                    ),
                    NoteBlock(
                        id="work",
                        block_type="checklist",
                        items=["Connect the service", "Verify the database"],
                    ),
                    NoteBlock(
                        id="tradeoff",
                        block_type="key_value",
                        rows=[["Decision", "Keep processing asynchronous"]],
                    ),
                    NoteBlock(
                        id="comparison",
                        block_type="table",
                        rows=[
                            ["Option", "Pros", "Cons"],
                            ["A", "Fast", "More coupling"],
                            ["B", "Simple", "Slightly slower"],
                        ],
                    ),
                ],
            )
        ],
    )

    scene = ExcalidrawCompiler().compile(
        VisualPlan(title="Project", notes_document=doc)
    )

    assert any(
        (e.get("customData") or {}).get("visual", {}).get("type") == "project_notes_page"
        for e in scene
    )
    block_types = {
        (e.get("customData") or {}).get("visual", {}).get("block_type")
        for e in scene
        if (e.get("customData") or {}).get("visual", {}).get("type") == "note_block"
    }
    assert {"paragraph", "checklist", "key_value", "table"}.issubset(block_types)


def test_visualization_kind_is_not_limited_to_a_fixed_taxonomy():
    plan = VisualPlan(
        title="Custom Visual",
        visualizations=[
            VisualVisualization(
                id="risk_matrix",
                kind="risk-matrix",
                title="Risk Matrix",
                purpose="Map risks by impact and likelihood.",
                elements=[
                    {
                        "id": "high_impact",
                        "primitive_type": "diamond",
                        "text": "High impact",
                        "width": 180,
                        "height": 100,
                    },
                    {
                        "id": "low_impact",
                        "primitive_type": "ellipse",
                        "text": "Low impact",
                    },
                    {
                        "id": "connector",
                        "primitive_type": "arrow",
                        "source": "high_impact",
                        "target": "low_impact",
                        "style": {"strokeStyle": "dashed"},
                    },
                ],
            )
        ],
    )

    scene = ExcalidrawCompiler().compile(plan)
    frames = [
        e for e in scene
        if (e.get("customData") or {}).get("visual", {}).get("type") == "freeform_visual_frame"
    ]
    assert len(frames) == 1
    assert frames[0]["customData"]["visual"]["kind"] == "risk-matrix"
    assert any(e["type"] == "diamond" for e in scene)


def test_visual_primitive_position_is_compiler_owned():
    plan = VisualPlan(
        title="Position Ownership",
        visualizations=[
            VisualVisualization(
                id="flow",
                kind="custom-flow",
                elements=[
                    {
                        "id": "first",
                        "primitive_type": "rectangle",
                        "text": "First",
                        "x": 99999,
                        "y": 99999,
                        "position": {"x": 123, "y": 456},
                    },
                    {
                        "id": "second",
                        "primitive_type": "rectangle",
                        "text": "Second",
                    },
                ],
            )
        ],
    )

    scene = ExcalidrawCompiler().compile(plan)
    first = next(
        e for e in scene
        if (e.get("customData") or {}).get("visual", {}).get("primitive_id") == "first"
    )

    assert first["x"] != 99999
    assert first["y"] != 99999
    assert first["x"] >= 80
    assert first["y"] >= 80
