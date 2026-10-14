"""Free-note rendering for Unknown Context and the meeting canvas fallback.

One free note per item: raw content wrapped, height growing with content,
notes stacked vertically with a 12px gap, provenance only in customData.
The meeting canvas deterministic fallback keeps one stacked note per
evidence item instead of joining a section into one paragraph.
"""
import json

from sqlalchemy.orm import Session

from app.models.context_resolution import PossibleProjectMatch, UnknownContextItem, UnknownItemStatus
from app.models.excalidraw import ExcalidrawArtifact
from app.models.project import Project, SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.services.unknown_context_visual import NOTE_GAP, render_unknown_context_board
from app.services.visual_plan_service import VisualPlanService
from app.services.workspace_atlas_service import UNKNOWN_NOTE_GAP, WorkspaceAtlasService

TEMPLATE_MARKERS = ("NEEDS CONTEXT", "Possible project:", "Should go to:", "human decides")


def _item(item_id: str, content: str) -> UnknownContextItem:
    return UnknownContextItem(
        id=item_id,
        project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        tenant_id="default_tenant",
        source="whatsapp",
        actor_id="sender-1",
        evidence_id=f"ev_{item_id}",
        content=content,
        status=UnknownItemStatus.PENDING.value,
    )


def _visible_texts(scene):
    return [" ".join(el.get("text", "").split()) for el in scene if el.get("type") == "text" and not el.get("isDeleted")]


def _note_rects(scene):
    rects = []
    for el in scene:
        if el.get("type") != "rectangle":
            continue
        custom = el.get("customData", {})
        prov = custom.get("atlas", {}) or custom.get("unknown_context", {})
        if prov.get("type") == "unknown_item":
            rects.append(el)
    return sorted(rects, key=lambda el: el["y"])


def test_atlas_unknown_column_is_one_growing_free_note_per_item(db_session: Session):
    project = Project(id="proj_suggested", name="Suggested Project", workspace_id="ws_default", is_system=False)
    db_session.add(project)
    short = _item("unk_note_short", "Short unassigned note.")
    long_content = "Long unassigned note. " + ("This sentence keeps the raw content going. " * 12)
    long_item = _item("unk_note_long", long_content)
    db_session.add_all([short, long_item])
    db_session.add(PossibleProjectMatch(
        id="pmatch_note_1", unknown_item_id=short.id, candidate_project_id=project.id,
    ))
    db_session.commit()

    service = WorkspaceAtlasService()
    scene = service._unknown_column([short, long_item], db_session, "ws_default")

    texts = _visible_texts(scene)
    for text in texts:
        for marker in TEMPLATE_MARKERS:
            assert marker not in text
    assert any(" ".join(long_content.split()) in text for text in texts)
    assert all(short.id not in text and long_item.id not in text for text in texts)

    notes = _note_rects(scene)
    assert len(notes) == 2
    first, second = notes
    assert second["height"] > first["height"]
    assert second["y"] - (first["y"] + first["height"]) == UNKNOWN_NOTE_GAP == 12

    provenance = first["customData"]["atlas"]
    assert provenance["item_id"] == short.id
    assert provenance["source"] == "whatsapp"
    assert provenance["evidence_id"] == "ev_unk_note_short"
    assert provenance["suggestions"] == ["Suggested Project"]
    assert provenance["suggestion_ids"] == ["proj_suggested"]


def test_unknown_board_is_one_growing_free_note_per_item(db_session: Session):
    short = _item("unk_board_short", "Board note one.")
    long_content = "Board note two. " + ("More raw board content follows here. " * 12)
    long_item = _item("unk_board_long", long_content)
    db_session.add_all([short, long_item])
    db_session.commit()

    result = render_unknown_context_board(db_session)
    assert result["notes"] == 2

    artifact = db_session.query(ExcalidrawArtifact).filter(
        ExcalidrawArtifact.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    ).first()
    scene = json.loads(artifact.elements_json)
    texts = _visible_texts(scene)
    for text in texts:
        for marker in TEMPLATE_MARKERS:
            assert marker not in text
    assert any(" ".join(long_content.split()) in text for text in texts)

    notes = _note_rects(scene)
    assert len(notes) == 2
    first, second = notes
    # Board order is newest-first; height must grow with content either way.
    assert max(n["height"] for n in notes) > min(n["height"] for n in notes)
    assert second["y"] - (first["y"] + first["height"]) == NOTE_GAP == 12
    assert first["customData"]["unknown_context"]["source"] == "whatsapp"


def test_board_agent_may_draw_diagram_and_uncovered_items_are_appended(db_session: Session, monkeypatch):
    from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship
    from app.services import visual_plan_service

    short = _item("unk_board_short", "Board note one.")
    long_content = "Board note two. " + ("More raw board content follows here. " * 12)
    long_item = _item("unk_board_long", long_content)
    db_session.add_all([short, long_item])
    db_session.commit()

    plan = VisualPlan(
        title="Unknown Context Board",
        canvas_strategy="mixed",
        nodes=[
            VisualNode(id="concept", label="SolarRickshaw", node_type="service", evidence_ids=[short.id]),
            VisualNode(id="feat", label="Battery Swap Live Map", node_type="service", evidence_ids=[short.id]),
        ],
        relationships=[VisualRelationship(source="concept", target="feat")],
    )
    monkeypatch.setattr(
        visual_plan_service.VisualPlanService, "build_plan", lambda self, **kwargs: (plan, "ai")
    )

    result = render_unknown_context_board(db_session)
    assert result["ai_status"] == "ai"

    artifact = db_session.query(ExcalidrawArtifact).filter(
        ExcalidrawArtifact.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    ).first()
    scene = json.loads(artifact.elements_json)
    texts = _visible_texts(scene)
    # The agent diagram is present...
    assert any("SolarRickshaw" in text for text in texts)
    assert any(el.get("type") == "arrow" for el in scene)
    # ...and the item the design did not represent is appended verbatim.
    assert any(" ".join(long_content.split()) in text for text in texts)


def test_atlas_unknown_column_delegates_to_current_board(db_session: Session):
    db_session.add(Project(
        id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, name="Unknown Context",
        workspace_id="ws_default", is_system=True,
    ))
    item = _item("unk_board_short", "Board note one.")
    db_session.add(item)
    db_session.commit()
    render_unknown_context_board(db_session)

    scene = WorkspaceAtlasService()._unknown_column([item], db_session, "ws_default")
    texts = _visible_texts(scene)
    assert any("Board note one." in text for text in texts)
    assert any(
        el.get("customData", {}).get("atlas", {}).get("type") == "project_canvas_element"
        for el in scene
    )


def test_meeting_canvas_fallback_stacks_one_note_per_evidence_item():
    plan = VisualPlanService()._deterministic_plan(
        state_summary={"title": "Meeting Notes"},
        current_nodes=[],
        focus_prompt="MEETING CANVAS MODE",
        evidence_snippets=[
            {"id": "ev_1", "content": "Speaker A: first discussion point"},
            {"id": "ev_2", "content": "Speaker B: second discussion point"},
            {"id": "ev_3", "content": "Speaker C: third discussion point"},
        ],
    )
    assert plan.notes_document is not None
    blocks = [b for section in plan.notes_document.sections for b in section.blocks]
    assert [b.text for b in blocks] == [
        "Speaker A: first discussion point",
        "Speaker B: second discussion point",
        "Speaker C: third discussion point",
    ]
    assert [b.evidence_ids for b in blocks] == [["ev_1"], ["ev_2"], ["ev_3"]]
