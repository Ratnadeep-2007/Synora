"""Unknown Context hard delete: single, bulk, and assigned-evidence safety."""
from sqlalchemy.orm import Session

from app.models.context_resolution import UnknownContextItem, UnknownItemStatus
from app.models.evidence import Evidence
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, Project
from app.models.source_event import SourceEvent
from app.services.unknown_context_service import UnknownContextService


def _unknown_item(db: Session, item_id: str, evidence_id: str, ev_project: str):
    event = SourceEvent(
        project_id=ev_project, source="google_meet",
        source_event_id=f"evt_{item_id}", payload_json="{}",
    )
    db.add(event)
    db.flush()
    db.add(
        Evidence(
            id=evidence_id, project_id=ev_project, source="google_meet",
            source_event_id=event.event_id, content=f"content for {item_id}",
        )
    )
    item = UnknownContextItem(
        id=item_id, project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        tenant_id="default_tenant", source="google_meet",
        evidence_id=evidence_id, content=f"content for {item_id}",
        status=UnknownItemStatus.PENDING.value,
    )
    db.add(item)
    db.commit()
    return item


def test_delete_unknown_item_removes_unassigned_content(client, db_session: Session):
    _unknown_item(db_session, "unk_sdel_1", "ev_sdel_1", SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID)

    resp = client.delete(
        "/api/v1/unknown-context/items/unk_sdel_1",
        headers={"X-User-ID": "usr_test_user_001"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted_items"] == 1
    assert resp.json()["deleted_evidence"] == 1
    assert db_session.query(UnknownContextItem).filter_by(id="unk_sdel_1").first() is None
    assert db_session.query(Evidence).filter_by(id="ev_sdel_1").first() is None

    again = client.delete(
        "/api/v1/unknown-context/items/unk_sdel_1",
        headers={"X-User-ID": "usr_test_user_001"},
    )
    assert again.status_code == 404


def test_delete_unknown_item_keeps_assigned_project_evidence(db_session: Session):
    db_session.add(Project(id="proj_skeep", name="Keep", workspace_id="ws_default", is_system=False))
    db_session.commit()
    _unknown_item(db_session, "unk_sdel_2", "ev_sdel_2", "proj_skeep")

    result = UnknownContextService().delete_item(
        "unk_sdel_2", db_session, actor_id="usr_test_user_001"
    )
    assert result["deleted_items"] == 1
    assert result["deleted_evidence"] == 0  # project memory is never deleted here
    assert db_session.query(Evidence).filter_by(id="ev_sdel_2").first() is not None


def test_delete_unknown_items_bulk_clears_pending(client, db_session: Session):
    _unknown_item(db_session, "unk_sbulk_1", "ev_sbulk_1", SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID)
    _unknown_item(db_session, "unk_sbulk_2", "ev_sbulk_2", SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID)

    resp = client.delete(
        "/api/v1/unknown-context/items?status=pending",
        headers={"X-User-ID": "usr_test_user_001"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted_items"] >= 2
    assert (
        db_session.query(UnknownContextItem)
        .filter(UnknownContextItem.status == UnknownItemStatus.PENDING.value)
        .count()
        == 0
    )
