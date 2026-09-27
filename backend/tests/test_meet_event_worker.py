from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import TranscriptUnavailableError
from app.models.meet_event_record import MeetEventRecord
from app.models.meeting import Meeting, Transcript, TranscriptEntry
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.services.encryption_service import EncryptionService
from app.services.meet_event_worker import MeetEventWorker, UNASSIGNED_PROJECT_ID


def _connection(db_session: Session, encryption: EncryptionService, user_id: str) -> SourceConnection:
    conn = SourceConnection(
        user_id=user_id,
        provider="google",
        provider_account_id="sub_worker_test",
        provider_account_email="worker@test.internal",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption.encrypt_dict(
            {"access_token": "tok_worker", "refresh_token": "ref_worker"}
        ),
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn


def _record(db_session: Session, user_id: str) -> MeetEventRecord:
    rec = MeetEventRecord(
        provider_event_id="evt_worker_1",
        event_type="google.workspace.meet.transcript.v2.fileGenerated",
        conference_record_id="conferenceRecords/conf_w1",
        transcript_resource="conferenceRecords/conf_w1/transcripts/t_w1",
        status="received",
        attempts="0",
        user_id=user_id,
    )
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)
    return rec


# 7. Transcript retrieval + 8. entry pagination + 9. participant resolution -----
def test_worker_retrieves_persists_entries_and_participants(
    db_session: Session, test_user, encryption_service: EncryptionService
):
    conn = _connection(db_session, encryption_service, test_user.id)
    rec = _record(db_session, test_user.id)
    worker = MeetEventWorker()

    entries_page_1 = [
        {
            "name": "conferenceRecords/conf_w1/transcripts/t_w1/entries/e1",
            "text": "We should add a review step before release.",
            "participant": "conferenceRecords/conf_w1/participants/p1",
            "startTime": "2026-09-27T10:00:01Z",
            "languageCode": "en-US",
        },
        {
            "name": "conferenceRecords/conf_w1/transcripts/t_w1/entries/e2",
            "text": "Agreed, let's do it.",
            "participant": "conferenceRecords/conf_w1/participants/p2",
            "startTime": "2026-09-27T10:00:05Z",
            "languageCode": "en-US",
        },
    ]

    async def fake_get_transcript(**kwargs):
        return {"name": kwargs["transcript_name"], "state": "ENDED"}

    async def fake_participants(**kwargs):
        return [
            {"name": "conferenceRecords/conf_w1/participants/p1", "signedinUser": {"displayName": "W Speaker"}},
            {"name": "conferenceRecords/conf_w1/participants/p2", "anonymousUser": {"displayName": "Guest"}},
        ]

    async def fake_entries(**kwargs):
        return entries_page_1

    with patch.object(worker.meet_service, "get_transcript", new=AsyncMock(side_effect=fake_get_transcript)), \
        patch.object(worker.meet_service, "get_conference_record", new_callable=AsyncMock) as conf_mock, \
        patch.object(worker.meet_service, "fetch_all_participants", new=AsyncMock(side_effect=fake_participants)), \
        patch.object(worker.meet_service, "fetch_all_transcript_entries", new=AsyncMock(side_effect=fake_entries)):
        conf_mock.return_value = {"name": "conferenceRecords/conf_w1", "space": "spaces/W1"}
        result = worker.process_event_record(event_record_id=rec.id, db=db_session)

    assert result["status"] == "processed"
    assert result["entries_synced"] == 2
    meeting = db_session.query(Meeting).filter(Meeting.id == result["meeting_id"]).first()
    assert meeting is not None
    assert meeting.source_connection_id == conn.id
    transcript = db_session.query(Transcript).filter(Transcript.meeting_id == meeting.id).first()
    assert transcript is not None
    entries = db_session.query(TranscriptEntry).filter(TranscriptEntry.transcript_id == transcript.id).all()
    assert len(entries) == 2
    assert any(e.participant_id for e in entries)


# 10. PostgreSQL persistence + 13. duplicate processing -------------------------
def test_worker_rerun_is_idempotent(
    db_session: Session, test_user, encryption_service: EncryptionService
):
    _connection(db_session, encryption_service, test_user.id)
    rec = _record(db_session, test_user.id)
    worker = MeetEventWorker()

    async def fake_get_transcript(**kwargs):
        return {"name": kwargs["transcript_name"], "state": "AVAILABLE"}

    with patch.object(worker.meet_service, "get_transcript", new=AsyncMock(side_effect=fake_get_transcript)), \
        patch.object(worker.meet_service, "get_conference_record", new_callable=AsyncMock) as conf_mock, \
        patch.object(worker.meet_service, "fetch_all_participants", new_callable=AsyncMock) as part_mock, \
        patch.object(worker.meet_service, "fetch_all_transcript_entries", new_callable=AsyncMock) as entries_mock:
        conf_mock.return_value = {}
        part_mock.return_value = []
        entries_mock.return_value = [
            {
                "name": "conferenceRecords/conf_w1/transcripts/t_w1/entries/e1",
                "text": "Hello team.",
                "startTime": "2026-09-27T10:00:01Z",
            }
        ]
        first = worker.process_event_record(event_record_id=rec.id, db=db_session)
        before_entries = db_session.query(TranscriptEntry).count()
        second = worker.process_event_record(event_record_id=rec.id, db=db_session)

    assert first["status"] == "processed"
    assert second["status"] == "duplicate"
    assert db_session.query(TranscriptEntry).count() == before_entries


# 11. Project mapping: explicit subscription project wins; else unassigned ----
def test_unmapped_transcript_goes_to_unassigned(
    db_session: Session, test_user, encryption_service: EncryptionService
):
    _connection(db_session, encryption_service, test_user.id)
    rec = _record(db_session, test_user.id)
    worker = MeetEventWorker()

    async def fake_get_transcript(**kwargs):
        return {"name": kwargs["transcript_name"], "state": "AVAILABLE"}

    with patch.object(worker.meet_service, "get_transcript", new=AsyncMock(side_effect=fake_get_transcript)), \
        patch.object(worker.meet_service, "get_conference_record", new_callable=AsyncMock) as conf_mock, \
        patch.object(worker.meet_service, "fetch_all_participants", new_callable=AsyncMock) as part_mock, \
        patch.object(worker.meet_service, "fetch_all_transcript_entries", new_callable=AsyncMock) as entries_mock:
        conf_mock.return_value = {}
        part_mock.return_value = []
        entries_mock.return_value = []
        result = worker.process_event_record(event_record_id=rec.id, db=db_session)

    assert result["project_id"] == UNASSIGNED_PROJECT_ID


def test_assign_unmapped_meeting(client: TestClient, test_user, db_session: Session):
    from app.models.project import Project

    project = Project(id="proj_assign_target", workspace_id="ws_default", name="Assign Target")
    db_session.add(project)
    meeting = Meeting(
        id="meet_unassigned_1",
        user_id=test_user.id,
        project_id=UNASSIGNED_PROJECT_ID,
        provider="google",
        provider_conference_id="conferenceRecords/conf_unassigned_1",
        title="Unmapped",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
    )
    db_session.add(meeting)
    db_session.commit()

    resp = client.post(
        f"/meet/unassigned/{meeting.id}/assign?project_id=proj_assign_target",
        headers={"X-User-ID": test_user.id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] == "proj_assign_target"


# 12. Tenant/project isolation ---------------------------------------------------
def test_event_processing_is_user_scoped(client: TestClient, test_user, db_session: Session):
    other = MeetEventRecord(
        provider_event_id="evt_other_user",
        event_type="google.workspace.meet.transcript.v2.fileGenerated",
        conference_record_id="conferenceRecords/conf_other",
        transcript_resource="conferenceRecords/conf_other/transcripts/t",
        status="received",
        attempts="0",
        user_id="usr_someone_else",
    )
    db_session.add(other)
    db_session.commit()
    resp = client.post(
        f"/meet/events/{other.id}/process",
        headers={"X-User-ID": test_user.id},
    )
    assert resp.status_code == 403


# 16. Transcript not yet generated ------------------------------------------------
def test_transcript_pending_state(
    db_session: Session, test_user, encryption_service: EncryptionService
):
    _connection(db_session, encryption_service, test_user.id)
    rec = _record(db_session, test_user.id)
    worker = MeetEventWorker()

    async def fake_get_transcript(**kwargs):
        return {"name": kwargs["transcript_name"], "state": "STARTED"}

    with patch.object(worker.meet_service, "get_transcript", new=AsyncMock(side_effect=fake_get_transcript)):
        with pytest.raises(TranscriptUnavailableError):
            worker.process_event_record(event_record_id=rec.id, db=db_session)
    db_session.refresh(rec)
    assert rec.status == "awaiting_transcript"


# 15. Revoked authorization --------------------------------------------------------
def test_revoked_connection_blocks_processing(
    db_session: Session, test_user, encryption_service: EncryptionService
):
    from app.core.exceptions import CredentialsExpiredError

    conn = _connection(db_session, encryption_service, test_user.id)
    conn.status = ConnectionStatus.REVOKED.value
    db_session.commit()
    rec = _record(db_session, test_user.id)
    worker = MeetEventWorker()
    with pytest.raises(CredentialsExpiredError):
        worker.process_event_record(event_record_id=rec.id, db=db_session)
