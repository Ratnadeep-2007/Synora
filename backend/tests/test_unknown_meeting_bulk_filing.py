from types import SimpleNamespace
from app.models.context_resolution import UnknownContextItem
from app.services.unknown_context_service import UnknownContextService


def evidence(index, content="Original spoken words"):
    return SimpleNamespace(id=f"ev_bulk{index}",content=content,source="google_meet",actor_id="SPEAKER_00",occurred_at=None)


def test_meeting_inbox_bulk_filing_is_atomic_and_idempotent(db_session, monkeypatch):
    context = SimpleNamespace(ensure_unknown_context_project=lambda db: None)
    service = UnknownContextService(context_service=context)
    commits = []
    commit = db_session.commit
    monkeypatch.setattr(db_session,"commit",lambda: (commits.append(True),commit())[-1])
    records = [evidence(0),evidence(1),evidence(1),evidence(2,"")]
    assert service.file_unresolved_meeting_evidence("mtg_bulk",records,db_session) == 2
    assert len(commits) == 1
    assert db_session.query(UnknownContextItem).filter_by(meeting_id="mtg_bulk").count() == 2
    assert service.file_unresolved_meeting_evidence("mtg_bulk",records,db_session) == 0
    assert len(commits) == 1


def test_meeting_inbox_does_not_refile_dismissed_evidence(db_session):
    service = UnknownContextService(context_service=SimpleNamespace(ensure_unknown_context_project=lambda db: None))
    records = [evidence(9)]
    service.file_unresolved_meeting_evidence("mtg_bulk_dismissed",records,db_session)
    item = db_session.query(UnknownContextItem).filter_by(evidence_id="ev_bulk9").one()
    item.status = "dismissed"
    db_session.commit()
    assert service.file_unresolved_meeting_evidence("mtg_bulk_dismissed",records,db_session) == 0
    assert item.status == "dismissed"
