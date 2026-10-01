import json

from sqlalchemy.orm import Session

from app.models.context_feedback import ContextFeedback
from app.models.project import Project, Workspace
from app.models.project_state import ProjectState
from app.services.project_semantic_profile_service import ProjectSemanticProfileService
from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship
from app.services.excalidraw_compiler import ExcalidrawCompiler

from app.services.workspace_atlas_service import (
    COLUMN_GUTTER,
    COLUMN_GUTTER_CM,
    COLUMN_WIDTH,
    COLUMN_WIDTH_CM,
    NOTE_H,
    NOTE_W,
    WorkspaceAtlasService,
)


def _project(db: Session, project_id: str, name: str, workspace_id: str = "ws_atlas_test") -> Project:
    project = Project(
        id=project_id,
        name=name,
        description=f"{name} project",
        workspace_id=workspace_id,
        is_system=False,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def test_atlas_columns_use_explicit_fixed_width_and_gap(db_session: Session):
    atlas = WorkspaceAtlasService()

    slots = atlas._assign_slots(
        [_project(db_session, "proj_atlas_a", "Alpha"), _project(db_session, "proj_atlas_b", "Beta")],
        {},
    )
    assert slots == {"proj_atlas_a": 1, "proj_atlas_b": 2}
    assert COLUMN_WIDTH_CM == 36.0
    assert COLUMN_GUTTER_CM == 3.0
    assert COLUMN_WIDTH > COLUMN_GUTTER > 0


def test_atlas_keeps_existing_project_column_when_another_project_is_deleted(db_session: Session):
    atlas = WorkspaceAtlasService()
    a = _project(db_session, "proj_stable_a", "Alpha")
    b = _project(db_session, "proj_stable_b", "Beta")
    first = atlas._assign_slots([a, b], {})

    c = _project(db_session, "proj_stable_c", "Gamma")
    second = atlas._assign_slots([a, c], first)

    assert second["proj_stable_a"] == first["proj_stable_a"]
    assert second["proj_stable_c"] == max(first.values()) + 1
    assert second["proj_stable_b"] == first["proj_stable_b"]


def test_atlas_project_columns_do_not_overlap(db_session: Session):
    workspace = Workspace(id="ws_scene_test", name="Atlas Test")
    db_session.add(workspace)
    db_session.commit()

    a = _project(db_session, "proj_scene_a", "Alpha", workspace_id="ws_scene_test")
    b = _project(db_session, "proj_scene_b", "Beta", workspace_id="ws_scene_test")

    scene, _ = WorkspaceAtlasService()._build_scene(
        [a, b],
        db_session,
        tenant_id="default_tenant",
        workspace_id="ws_scene_test",
        slot_map={"proj_scene_a": 1, "proj_scene_b": 2},
    )

    frames = {
        el["id"]: el
        for el in scene
        if el.get("type") == "rectangle"
        and el.get("width") == COLUMN_WIDTH
        and el.get("height", 0) >= 900
    }
    frame_a = frames[WorkspaceAtlasService._id("proj_scene_a", "frame")]
    frame_b = frames[WorkspaceAtlasService._id("proj_scene_b", "frame")]

    assert frame_a["x"] + frame_a["width"] + COLUMN_GUTTER <= frame_b["x"]


def test_semantic_profile_refreshes_after_project_state_version_changes(db_session: Session):
    project = _project(db_session, "proj_profile_refresh", "Synora")
    state = ProjectState(
        project_id=project.id,
        current_version=1,
        title="Synora",
        vision="Project intelligence and living architecture",
        requirements_json=json.dumps([]),
        architecture_json=json.dumps([]),
        agent_workflow_json=json.dumps([]),
        decisions_json=json.dumps([]),
        constraints_json=json.dumps([]),
        assumptions_json=json.dumps([]),
        open_questions_json=json.dumps([]),
    )
    db_session.add(state)
    db_session.commit()

    service = ProjectSemanticProfileService()
    profile_v1 = service.get_or_create_profile(project.id, db_session)

    state.current_version = 2
    state.requirements_json = json.dumps([{
        "id": "req_1",
        "title": "Context routing",
        "content": "Route WhatsApp and Google Meet evidence by project domain",
    }])
    db_session.commit()

    profile_v2 = service.get_or_create_profile(project.id, db_session)

    assert profile_v2.id == profile_v1.id
    assert profile_v2.state_version == 2
    assert "context routing" in profile_v2.get_business_concepts()


def test_context_feedback_is_tenant_scoped(db_session: Session):
    db_session.add_all([
        ContextFeedback(
            id="ctxfb_tenant_a",
            tenant_id="tenant_a",
            selected_project_id="proj_feedback_a",
            action="assigned",
            text_snippet="restaurant table booking",
        ),
        ContextFeedback(
            id="ctxfb_tenant_b",
            tenant_id="tenant_b",
            selected_project_id="proj_feedback_a",
            action="assigned",
            text_snippet="medical claims",
        ),
    ])
    db_session.commit()

    from app.services.context_feedback_service import ContextFeedbackService

    service = ContextFeedbackService(db_session)
    rows = service.get_feedback_for_prompt(
        ["proj_feedback_a"],
        tenant_id="tenant_a",
    )

    assert len(rows) == 1
    assert rows[0]["text"] == "restaurant table booking"


def test_knowledge_notes_include_visual_explainer_steps(db_session: Session):
    project = _project(db_session, "proj_note_visual", "DineIn")
    notes = WorkspaceAtlasService()._knowledge_cards(
        project.id,
        reqs=[{"title": "QR ordering", "content": "Customers scan a table code to order."}],
        decs=[{"title": "Use realtime KDS", "content": "Kitchen tickets are pushed immediately."}],
        questions=[{"title": "Offline mode", "content": "What happens when the tablet loses connectivity?"}],
        constraints=[{"title": "POS constraint", "content": "Settlement must stay consistent."}],
        assumptions=[{"title": "Stable network", "content": "Connected devices are available during normal operations."}],
    )

    service = WorkspaceAtlasService()
    for note in notes:
        stages = service._mini_visual_stages(
            note["category"],
            note["title"],
            note["content"],
        )
        assert len(stages) == 4
        assert all(stage["label"] and stage["detail"] for stage in stages)

        elements = service._note_card(
            project.id,
            note,
            x=100,
            y=100,
        )
        assert any(
            el.get("customData", {}).get("atlas", {}).get("type") == "knowledge_mini_visual"
            for el in elements
        )
        assert sum(1 for el in elements if el.get("type") == "arrow") >= 3
        assert any(
            el.get("type") == "text"
            and "Read left" in el.get("text", "")
            for el in elements
        )
        assert any(
            el.get("type") == "rectangle"
            and el.get("width") == NOTE_W
            and el.get("height") == NOTE_H
            for el in elements
        )


def test_atlas_build_scene_includes_divider_lines(db_session: Session):
    project = _project(db_session, "proj_atlas_scene", "AtlasSceneTest")
    state = ProjectState(
        id="pstate_test_scene",
        project_id=project.id,
        current_version=1,
        vision="Test Vision",
        requirements_json=json.dumps([{"title": "Req 1", "content": "Content"}]),
        architecture_json="[]",
        decisions_json=json.dumps([{"title": "Dec 1", "content": "Content"}]),
        constraints_json="[]",
        assumptions_json="[]",
    )
    db_session.add(state)
    db_session.commit()

    service = WorkspaceAtlasService()
    scene, metadata = service._build_scene(
        projects=[project],
        db=db_session,
        tenant_id="default_tenant",
        workspace_id="ws_atlas_test",
        slot_map={project.id: 1},
    )
    assert len(scene) > 0
    # Ensure line elements rendered properly without stroke_width error
    lines = [el for el in scene if el.get("type") == "line"]
    assert len(lines) > 0
    assert all(line.get("strokeWidth") is not None for line in lines)


def test_column_height_dynamically_increases_with_content(db_session: Session):
    service = WorkspaceAtlasService()

    # Project with minimal content (1 req, 1 dec)
    proj_small = _project(db_session, "proj_height_small", "SmallProject")
    state_small = ProjectState(
        id="pstate_small",
        project_id=proj_small.id,
        current_version=1,
        requirements_json=json.dumps([{"title": "R1", "content": "C1"}]),
        decisions_json=json.dumps([{"title": "D1", "content": "C1"}]),
    )
    db_session.add(state_small)

    # Project with substantial architecture and knowledge content
    proj_large = _project(db_session, "proj_height_large", "LargeProject")
    state_large = ProjectState(
        id="pstate_large",
        project_id=proj_large.id,
        current_version=1,
        architecture_json=json.dumps([{"component": f"Tier_{i}", "tier": "api"} for i in range(8)]),
        requirements_json=json.dumps([{"title": f"Req {i}", "content": f"Content {i}"} for i in range(5)]),
        decisions_json=json.dumps([{"title": f"Dec {i}", "content": f"Content {i}"} for i in range(5)]),
        constraints_json=json.dumps([{"title": "Constraint 1", "content": "Limitation"}]),
        assumptions_json=json.dumps([{"title": "Assumption 1", "content": "Premise"}]),
        open_questions_json=json.dumps([{"title": "Question 1", "content": "Query"}]),
    )
    db_session.add(state_large)
    db_session.commit()

    scene_small = service._project_column(proj_small, db_session, "default_tenant", 100)
    scene_large = service._project_column(proj_large, db_session, "default_tenant", 100)

    frame_small = next(el for el in scene_small if el["id"] == service._id(proj_small.id, "frame"))
    frame_large = next(el for el in scene_large if el["id"] == service._id(proj_large.id, "frame"))

    # Large project column must be significantly taller than minimal project column
    assert frame_large["height"] > frame_small["height"]
    assert frame_large["height"] >= 1600
    assert frame_small["height"] <= 1000

    # Ensure knowledge cards are generated
    note_cards_large = [
        el for el in scene_large
        if el.get("type") == "rectangle"
        and el.get("customData", {}).get("atlas", {}).get("type") == "knowledge_note"
    ]
    assert len(note_cards_large) > 0




def test_visual_compiler_uses_semantic_shapes_group_lanes_and_edge_labels():
    plan = VisualPlan(
        title="DineIn Flow",
        layout_direction="horizontal",
        nodes=[
            VisualNode(id="actor", label="Customer", node_type="actor", group="experience"),
            VisualNode(id="order", label="Ordering Service", node_type="service", group="core", emphasis="primary"),
            VisualNode(id="decision", label="Fraud Check", node_type="decision", group="core"),
            VisualNode(id="db", label="Orders DB", node_type="datastore", group="data"),
        ],
        relationships=[
            VisualRelationship(source="actor", target="order", label="order request"),
            VisualRelationship(source="order", target="decision", label="validate"),
            VisualRelationship(source="decision", target="db", label="persist result"),
        ],
        notes=[],
    )

    scene = ExcalidrawCompiler().compile(plan)

    assert any(
        el.get("type") == "ellipse"
        and el.get("customData", {}).get("visual", {}).get("node_type") == "actor"
        for el in scene
    )
    assert any(
        el.get("type") == "diamond"
        and el.get("customData", {}).get("visual", {}).get("node_type") == "decision"
        for el in scene
    )
    assert sum(
        1
        for el in scene
        if el.get("customData", {}).get("visual", {}).get("type") == "architecture_group"
    ) == 3
    assert sum(1 for el in scene if el.get("type") == "arrow") == 3
    assert sum(
        1
        for el in scene
        if el.get("type") == "text"
        and el.get("customData", {}).get("visual", {}).get("type") == "relationship_label"
    ) == 3
