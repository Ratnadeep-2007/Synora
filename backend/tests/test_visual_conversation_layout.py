from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship
from app.services.excalidraw_compiler import ExcalidrawCompiler


def test_context_notes_stack_one_below_another():
    plan = VisualPlan(
        title="DineIn",
        layout_direction="horizontal",
        nodes=[
            VisualNode(id="customer", label="Customer", node_type="actor", group="frontend"),
            VisualNode(id="ordering", label="Ordering App", node_type="client", group="frontend"),
            VisualNode(id="order", label="Order Service", node_type="service", group="core"),
            VisualNode(id="kds", label="Kitchen Display", node_type="service", group="core"),
        ],
        relationships=[
            VisualRelationship(source="customer", target="ordering"),
            VisualRelationship(source="ordering", target="order"),
            VisualRelationship(source="order", target="kds"),
        ],
        context_notes=[
            "PURPOSE — Table QR ordering lets guests place orders directly from their table.",
            "CURRENT STATE — Orders need immediate dispatch to the kitchen display.",
            "CONSTRAINT — Payment confirmation is required before the order is finalized.",
        ],
    )

    elements = ExcalidrawCompiler().compile(plan)
    cards = [
        e for e in elements
        if e.get("semantic_type") == "note"
        and str(e.get("id", "")).startswith("context_note_")
    ]

    assert len(cards) == 3
    assert len({card["x"] for card in cards}) == 1
    ys = [card["y"] for card in cards]
    assert ys == sorted(ys)
    assert ys[1] > ys[0]
    assert ys[2] > ys[1]


def test_architecture_layout_follows_dependency_depth():
    plan = VisualPlan(
        title="DineIn",
        layout_direction="horizontal",
        nodes=[
            VisualNode(id="customer", label="Customer", node_type="actor"),
            VisualNode(id="ordering", label="Ordering App", node_type="client"),
            VisualNode(id="order", label="Order Service", node_type="service"),
            VisualNode(id="db", label="Orders DB", node_type="datastore"),
        ],
        relationships=[
            VisualRelationship(source="customer", target="ordering"),
            VisualRelationship(source="ordering", target="order"),
            VisualRelationship(source="order", target="db"),
        ],
    )

    elements = ExcalidrawCompiler().compile(plan)
    nodes = {
        e["semantic_id"]: e
        for e in elements
        if e.get("semantic_type") == "node"
    }

    assert nodes["customer"]["x"] < nodes["ordering"]["x"]
    assert nodes["ordering"]["x"] < nodes["order"]["x"]
    assert nodes["order"]["x"] < nodes["db"]["x"]


def test_group_frames_are_generated_for_grouped_architecture():
    plan = VisualPlan(
        title="Grouped",
        nodes=[
            VisualNode(id="a", label="Client", node_type="client", group="frontend"),
            VisualNode(id="b", label="Service", node_type="service", group="core"),
        ],
    )

    elements = ExcalidrawCompiler().compile(plan)
    frames = [
        e for e in elements
        if e.get("semantic_type") == "group_frame"
    ]

    assert len(frames) == 2
