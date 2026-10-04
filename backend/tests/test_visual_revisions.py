"""Immutable visual revision tests (spec section 19, cases 18-25)."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.excalidraw import ExcalidrawArtifact, ExcalidrawProposal
from app.models.project import Project
from app.services.excalidraw_service import ExcalidrawService
from app.services.visual_revision_service import VisualRevisionError, VisualRevisionService


def _project(db: Session, project_id: str = "proj_visual_test") -> Project:
    p = Project(id=project_id, workspace_id="ws_default", name="Visual Test Project")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _add_evidence(db: Session, project_id: str = "proj_visual_test", content: str = "The platform uses Redis for session storage."):
    """Grounding requires citable evidence before any plan may be compiled."""
    from app.models.evidence import Evidence
    from app.models.source_event import SourceEvent

    event = SourceEvent(
        event_id="sev_visual_test",
        project_id=project_id,
        source="test",
        source_event_id="visual-test-1",
        event_type="test",
        payload_json="{}",
    )
    db.add(event)
    db.commit()

    row = Evidence(
        project_id=project_id,
        source="test",
        source_event_id="sev_visual_test",
        content=content,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _scene(labels):
    """Scene where the element id is derived from the label, so a label swap is
    reported as added+removed rather than a change to the same element."""
    return [
        {"id": f"el_{label}", "type": "text", "text": label, "x": i * 100, "y": 0}
        for i, label in enumerate(labels)
    ]


def _ensure_state(db: Session, project_id: str):
    from app.services.project_state_service import ProjectStateService

    return ProjectStateService().get_or_create_state(project_id, db)


# 18/19/20. Current revision is latest; history is immutable and viewable ----
def test_revisions_are_immutable_and_ordered(db_session: Session):
    _project(db_session)
    service = VisualRevisionService()

    r1 = service.commit_revision(
        project_id="proj_visual_test", scene=_scene(["A", "B"]), db=db_session, reason="First"
    )
    r2 = service.commit_revision(
        project_id="proj_visual_test", scene=_scene(["A", "B", "C"]), db=db_session, reason="Second"
    )

    assert r1.revision_number == 1
    assert r2.revision_number == 2
    assert r2.parent_revision_id == r1.id

    current = service.current_revision("proj_visual_test", db_session)
    assert current.id == r2.id

    # Historical revision 1 is unchanged even after revision 2 exists.
    old = service.get_revision("proj_visual_test", 1, db_session)
    assert json.loads(old.scene_json) == _scene(["A", "B"])
    assert len(service.list_revisions("proj_visual_test", db_session)) == 2


# 21. Compare produces a structured diff ------------------------------------
def test_compare_revisions_structured_diff(db_session: Session):
    _project(db_session)
    service = VisualRevisionService()
    service.commit_revision(project_id="proj_visual_test", scene=_scene(["A", "B"]), db=db_session)
    service.commit_revision(project_id="proj_visual_test", scene=_scene(["A", "C"]), db=db_session)

    diff = service.compare("proj_visual_test", 1, 2, db_session)
    assert "B" in diff["removed"]
    assert "C" in diff["added"]
    assert diff["from_revision"] == 1
    assert diff["to_revision"] == 2


# 22. Restore creates a NEW revision (never destructive) ----------------------
def test_restore_creates_new_revision(db_session: Session):
    _project(db_session)
    service = VisualRevisionService()
    service.commit_revision(project_id="proj_visual_test", scene=_scene(["A"]), db=db_session)
    service.commit_revision(project_id="proj_visual_test", scene=_scene(["A", "B"]), db=db_session)

    restored = service.restore_as_new_revision(
        project_id="proj_visual_test",
        target_revision_number=1,
        db=db_session,
        actor_id="usr_test",
    )
    assert restored.revision_number == 3
    assert json.loads(restored.scene_json) == _scene(["A"])
    # All three revisions still exist; nothing was deleted.
    assert len(service.list_revisions("proj_visual_test", db_session)) == 3


def test_get_missing_revision_errors(db_session: Session):
    _project(db_session)
    with pytest.raises(VisualRevisionError):
        VisualRevisionService().get_revision("proj_visual_test", 99, db_session)


# 23/25. Proposal does not mutate workspace before approval; links state+evidence
def test_proposal_pending_does_not_mutate_current_revision(db_session: Session):
    _project(db_session)
    _add_evidence(db_session)
    _ensure_state(db_session, "proj_visual_test")
    excal = ExcalidrawService()
    artifact = excal.get_or_create_artifact("proj_visual_test", db_session)
    revisions = VisualRevisionService()

    before = revisions.current_revision("proj_visual_test", db_session)
    assert before is not None

    proposal = excal.generate_proposal_from_state(
        project_id="proj_visual_test",
        state_version=1,
        db=db_session,
        reason="Test proposal",
    )
    assert proposal.status == "pending"

    # Current revision is unchanged while the proposal is pending.
    still = revisions.current_revision("proj_visual_test", db_session)
    assert still.id == before.id
    assert still.revision_number == before.revision_number


def test_approval_creates_traceable_revision(db_session: Session):
    _project(db_session)
    _add_evidence(db_session)
    _ensure_state(db_session, "proj_visual_test")
    excal = ExcalidrawService()
    excal.get_or_create_artifact("proj_visual_test", db_session)
    revisions = VisualRevisionService()

    proposal = excal.generate_proposal_from_state(
        project_id="proj_visual_test",
        state_version=7,
        db=db_session,
        reason="Align diagram",
    )
    proposal.evidence_ids_json = json.dumps(["ev_abc"])
    db_session.commit()

    _, artifact = excal.review_proposal(
        proposal_id=proposal.id,
        action="approve",
        actor_id="usr_reviewer",
        db=db_session,
        reason="Looks right",
    )
    assert artifact is not None

    latest = revisions.current_revision("proj_visual_test", db_session)
    # Traceable to the Project State version and evidence that motivated it.
    assert latest.derived_from_project_state_version == 7
    assert latest.proposal_id == proposal.id
    assert "ev_abc" in json.loads(latest.evidence_ids_json)
    assert latest.revision_number >= 2


# API surface ---------------------------------------------------------------
def test_visual_revision_api(client: TestClient, test_user, db_session: Session):
    _project(db_session)
    service = VisualRevisionService()
    service.commit_revision(project_id="proj_visual_test", scene=_scene(["A"]), db=db_session)
    service.commit_revision(project_id="proj_visual_test", scene=_scene(["A", "B"]), db=db_session)

    headers = {"X-User-ID": test_user.id}

    listed = client.get("/projects/proj_visual_test/visual/revisions", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["current_revision_number"] == 2

    current = client.get("/projects/proj_visual_test/visual/current", headers=headers)
    assert current.status_code == 200
    assert current.json()["revision_number"] == 2

    one = client.get("/projects/proj_visual_test/visual/revisions/1", headers=headers)
    assert one.status_code == 200
    assert one.json()["revision_number"] == 1

    diff = client.get(
        "/projects/proj_visual_test/visual/revisions/compare?from_revision=1&to_revision=2",
        headers=headers,
    )
    assert diff.status_code == 200
    assert "B" in diff.json()["added"]

    restored = client.post(
        "/projects/proj_visual_test/visual/revisions/1/restore",
        headers=headers,
    )
    assert restored.status_code == 200
    assert restored.json()["revision"]["revision_number"] == 3
