"""Editable canvas contract.

POST /projects/{id}/excalidraw/scene must persist user-drawn edits as a new
visual revision and update the live artifact — without creating evidence,
proposals, or touching the agent-managed pipeline.
"""

from app.models.excalidraw import ExcalidrawArtifact
from app.models.visual_revision import VisualRevision


def test_save_scene_persists_edits_without_evidence(client, db_session):
    pid = "proj_canvas_save_test"
    elements = [
        {"id": "user_rect_1", "type": "rectangle", "x": 10, "y": 10,
         "width": 200, "height": 100},
        {"id": "user_text_1", "type": "text", "x": 20, "y": 20,
         "width": 180, "height": 30, "text": "My whiteboard note",
         "originalText": "My whiteboard note"},
    ]
    resp = client.post(
        f"/projects/{pid}/excalidraw/scene",
        json={"name": "Test board", "elements": elements,
              "app_state": {"viewBackgroundColor": "#ffffff"}},
        headers={"X-User-ID": "usr_test_user_001"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["elements"]) == 2
    assert body["version"] >= 2

    # A visual revision records the user edit.
    revs = (
        db_session.query(VisualRevision)
        .filter(VisualRevision.project_id == pid)
        .order_by(VisualRevision.revision_number.desc())
        .all()
    )
    assert len(revs) >= 1
    assert "user_rect_1" in (revs[0].scene_json or "")

    # Live artifact carries the scene for reads.
    art = (
        db_session.query(ExcalidrawArtifact)
        .filter(ExcalidrawArtifact.project_id == pid)
        .first()
    )
    assert art is not None
    assert "My whiteboard note" in (art.elements_json or "")


def test_save_scene_rejects_non_dict_elements(client, db_session):
    pid = "proj_canvas_save_filter"
    resp = client.post(
        f"/projects/{pid}/excalidraw/scene",
        json={"elements": [{"id": "ok", "type": "rectangle"}, "junk", 42]},
        headers={"X-User-ID": "usr_test_user_001"},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["elements"]) == 1
