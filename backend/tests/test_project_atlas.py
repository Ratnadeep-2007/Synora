import json

from sqlalchemy.orm import Session

from app.models.context_feedback import ContextFeedback
from app.models.project import Project, Workspace
from app.models.project_state import ProjectState
from app.services.project_semantic_profile_service import ProjectSemanticProfileService
from app.services.workspace_atlas_service import (
    COLUMN_GUTTER,
    COLUMN_GUTTER_CM,
    COLUMN_WIDTH,
    COLUMN_WIDTH_CM,
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
            and el.get("width") == service.NOTE_W if hasattr(service, "NOTE_W") else True
            for el in elements
        )
