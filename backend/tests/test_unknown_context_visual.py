"""Unknown Context board rendering regression tests.

The board compiler enforces evidence grounding for diagram nodes; board
notes must cite their backing evidence (or the item itself) or rendering
the whole board is refused and the artifact silently goes stale.
"""
import json

from sqlalchemy.orm import Session

from app.models.context_resolution import UnknownContextItem, UnknownItemStatus
from app.models.excalidraw import ExcalidrawArtifact
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.services.unknown_context_visual import render_unknown_context_board


def _item(item_id: str, content: str, evidence_id=None) -> UnknownContextItem:
    return UnknownContextItem(
        id=item_id,
        project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        tenant_id="default_tenant",
        source="manual",
        actor_id="tester",
        evidence_id=evidence_id,
        content=content,
        status=UnknownItemStatus.PENDING.value,
    )


def test_unknown_board_renders_pending_items(db_session: Session):
    db_session.add_all([
        _item("unk_board_a", "Unassigned board note one.", evidence_id="ev_board_a"),
        _item("unk_board_b", "Unassigned board note two without evidence row."),
    ])
    db_session.commit()

    result = render_unknown_context_board(db_session)

    assert result["ok"] is True
    assert result["notes"] == 2
    artifact = db_session.query(ExcalidrawArtifact).filter(
        ExcalidrawArtifact.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    ).first()
    # Compiler wraps label text to box width; compare whitespace-normalized.
    texts = [" ".join(el.get("text", "").split()) for el in json.loads(artifact.elements_json)]
    assert any("Unassigned board note one." in text for text in texts)
    assert any("Unassigned board note two" in text for text in texts)


def test_unknown_board_renders_empty_state(db_session: Session):
    result = render_unknown_context_board(db_session)

    assert result["ok"] is True
    assert result["notes"] == 0
