"""Join tracking for the Vexa meeting bot.

Covers: spawn logging in start_capture, lifecycle lookup by meeting code,
transition tracking in wait_for_bot_active, and fast failure when the bot
can never join. All Vexa I/O is stubbed; no test touches the network.
"""

import logging

import pytest

from app.services.vexa_sarvam_service import (
    VexaSarvamError,
    VexaSarvamService,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_start_capture_logs_and_returns_spawn(monkeypatch, caplog):
    service = VexaSarvamService(vexa_api_key="test")

    async def fake_request(client, method, path, **kwargs):
        assert method == "POST" and path == "bots"
        return _FakeResponse(
            {"id": 7, "status": "requested", "bot_container_id": "mtg-7-x"}
        )

    monkeypatch.setattr(service, "_request", fake_request)
    with caplog.at_level(logging.INFO, logger="app.services.vexa_sarvam_service"):
        data = await service.start_capture("abc-defg-hij", "Synora")
    assert data["id"] == 7
    messages = [r.getMessage() for r in caplog.records]
    assert any("vexa_bot_spawn_requested" in m for m in messages)
    assert any("vexa_bot_spawn_accepted" in m for m in messages)


@pytest.mark.asyncio
async def test_get_bot_lifecycle_matches_meeting_code(monkeypatch):
    service = VexaSarvamService(vexa_api_key="test")

    async def fake_request(client, method, path, **kwargs):
        assert path == "bots/status"
        return _FakeResponse(
            {
                "running": [
                    {"native_meeting_id": "other", "status": "active"},
                    {
                        "native_meeting_id": "abc-defg-hij",
                        "status": "awaiting_admission",
                        "bot_container_id": "mtg-7-x",
                    },
                ]
            }
        )

    monkeypatch.setattr(service, "_request", fake_request)
    bot = await service.get_bot_lifecycle("abc-defg-hij")
    assert bot["status"] == "awaiting_admission"
    assert bot["bot_container_id"] == "mtg-7-x"
    assert await service.get_bot_lifecycle("missing") == {}


@pytest.mark.asyncio
async def test_get_bot_lifecycle_never_raises(monkeypatch):
    service = VexaSarvamService(vexa_api_key="test")

    async def boom(client, method, path, **kwargs):
        raise VexaSarvamError("down")

    monkeypatch.setattr(service, "_request", boom)
    assert await service.get_bot_lifecycle("abc-defg-hij") == {}


def _make_meeting(db, meeting_id="mtg_jointest", conference_code="abc-defg-hij"):
    from app.models.meeting import Meeting

    meeting = Meeting(
        id=meeting_id,
        user_id="usr_test",
        provider="google_meet",
        provider_conference_id=conference_code,
        title="t",
        status="ACTIVE",
        metadata_json="{}",
    )
    db.add(meeting)
    db.commit()
    return meeting


@pytest.mark.asyncio
async def test_wait_for_bot_active_tracks_transitions(
    monkeypatch, caplog, db_session
):
    service = VexaSarvamService(vexa_api_key="test")
    stages = iter([
        {"status": "joining", "bot_container_id": "mtg-7-x"},
        {"status": "awaiting_admission", "bot_container_id": "mtg-7-x"},
        {"status": "active", "bot_container_id": "mtg-7-x", "start_time": "t"},
    ])

    async def fake_lifecycle(code):
        return next(stages)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(service, "get_bot_lifecycle", fake_lifecycle)
    monkeypatch.setattr("app.services.vexa_sarvam_service.asyncio.sleep", fake_sleep)

    meeting = _make_meeting(db_session)
    with caplog.at_level(logging.INFO, logger="app.services.vexa_sarvam_service"):
        bot = await service.wait_for_bot_active(
            "abc-defg-hij", db_session, meeting, timeout_seconds=60
        )
    assert bot["status"] == "active"
    messages = [r.getMessage() for r in caplog.records]
    assert any("vexa_bot_stage" in m and "joining" in m for m in messages)
    assert any("vexa_bot_joined" in m for m in messages)
    # Transitions are persisted for the status endpoint.
    from app.services.vexa_sarvam_service import get_capture_metadata

    assert get_capture_metadata(meeting)["bot_status"] == "active"


@pytest.mark.asyncio
async def test_get_completed_recording_finds_finalized(monkeypatch):
    service = VexaSarvamService(vexa_api_key="test")

    async def fake_artifacts(code):
        return {"recordings": [
            {"id": 1, "status": "recording"},
            {"id": 2, "status": "completed", "completed_at": "2026-10-15T00:00:00Z"},
        ]}

    monkeypatch.setattr(service, "get_meeting_artifacts", fake_artifacts)
    recording = await service.get_completed_recording("abc-defg-hij")
    assert recording["id"] == 2


@pytest.mark.asyncio
async def test_wait_for_bot_active_returns_completed_when_bot_gone(monkeypatch, db_session):
    service = VexaSarvamService(vexa_api_key="test")

    async def fake_lifecycle(code):
        return {}

    async def fake_completed(code):
        return {"id": 9, "status": "completed"}

    monkeypatch.setattr(service, "get_bot_lifecycle", fake_lifecycle)
    monkeypatch.setattr(service, "get_completed_recording", fake_completed)
    meeting = _make_meeting(db_session, "mtg_jointest_done")
    bot = await service.wait_for_bot_active(
        "abc-defg-hij", db_session, meeting, timeout_seconds=60
    )
    assert bot["status"] == "completed"
    assert bot["recording_id"] == 9


@pytest.mark.asyncio
async def test_process_meeting_transcribes_recovered_recording(monkeypatch, db_session):
    from sqlalchemy.orm import sessionmaker
    from app.models.meeting import Meeting
    import app.core.database as database

    # The ingestion worker owns a new session. Point that factory at this
    # test's connection, not the separate empty application SQLite database.
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    service = VexaSarvamService(vexa_api_key="test", sarvam_api_key="")

    async def fake_completed(code):
        return {"id": 99, "status": "completed"}

    async def fail_join(*args, **kwargs):
        raise AssertionError("join wait must be skipped for a completed recording")

    async def fake_download(recording):
        return "99", b"audio-bytes", "audio/webm"

    async def fake_transcribe(*args, **kwargs):
        assert not db_session.in_transaction(), "Do not hold a database transaction during STT"
        return (
            [{"speaker": "SPEAKER_00", "text": "hello", "start_seconds": 0.0, "end_seconds": 1.0, "id": "s1"}],
            "whisper_faster_whisper", "model", "job", "en", None,
        )

    monkeypatch.setattr(service, "get_completed_recording", fake_completed)
    monkeypatch.setattr(service, "wait_for_bot_active", fail_join)
    monkeypatch.setattr(service, "download_recording", fake_download)
    monkeypatch.setattr(service, "_transcribe_with_fallback", fake_transcribe)
    monkeypatch.setattr(
        service, "_persist_transcript",
        lambda *args, **kwargs: {"status": "completed", "entries_count": 1},
    )

    meeting = _make_meeting(db_session, "mtg_recover_test")
    result = await service.process_meeting(meeting.id, db_session)
    assert result["status"] == "completed"
    from app.services.vexa_sarvam_service import get_capture_metadata

    stored = db_session.query(Meeting).filter(Meeting.id == "mtg_recover_test").first()
    assert get_capture_metadata(stored)["recording_id"] == 99


def test_processing_claim_is_single_flight():
    from app.services.vexa_sarvam_service import _PROCESSING_MEETINGS, claim_meeting_processing

    _PROCESSING_MEETINGS.discard("mtg_claim")
    assert claim_meeting_processing("mtg_claim") is True
    assert claim_meeting_processing("mtg_claim") is False
    _PROCESSING_MEETINGS.discard("mtg_claim")


@pytest.mark.asyncio
async def test_shutdown_stops_bots_still_in_meets(monkeypatch, db_session):
    import json as _json

    import app.core.database as database
    from app.services import vexa_sarvam_service as vexa_module

    meeting = _make_meeting(db_session, "mtg_shutdown")
    meeting.metadata_json = _json.dumps({"vexa_capture": {"status": "joining", "meeting_code": "abc-defg-hij"}})
    db_session.commit()

    stopped = []

    class _FakeService:
        async def stop_capture(self, code):
            stopped.append(code)
            return {"stopped": True}

    monkeypatch.setattr(database, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(vexa_module, "VexaSarvamService", _FakeService)
    result = await vexa_module.stop_active_captures_on_shutdown()
    assert result["stopped"] == 1
    assert stopped == ["abc-defg-hij"]
    from app.models.meeting import Meeting
    from app.services.vexa_sarvam_service import get_capture_metadata

    stored = db_session.query(Meeting).filter(Meeting.id == "mtg_shutdown").first()
    assert get_capture_metadata(stored)["status"] == "stopping"


@pytest.mark.asyncio
async def test_startup_reconcile_resumes_unfinished_and_failed_with_recording(monkeypatch, db_session):
    import json as _json

    import app.core.database as database
    from app.services import vexa_sarvam_service as vexa_module

    live = _make_meeting(db_session, "mtg_reconcile_live", "live-code-1")
    live.metadata_json = _json.dumps({"vexa_capture": {"status": "waiting_for_recording", "meeting_code": "live-code"}})
    failed = _make_meeting(db_session, "mtg_reconcile_failed", "failed-code-1")
    failed.metadata_json = _json.dumps({"vexa_capture": {"status": "failed", "meeting_code": "failed-code"}})
    dead = _make_meeting(db_session, "mtg_reconcile_dead", "dead-code-1")
    dead.metadata_json = _json.dumps({"vexa_capture": {"status": "failed", "meeting_code": "dead-code"}})
    db_session.commit()

    resumed = []

    async def fake_background(meeting_id):
        resumed.append(meeting_id)

    class _FakeService:
        async def get_completed_recording(self, code):
            return {"id": 1} if code == "failed-code" else None

    monkeypatch.setattr(database, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(vexa_module, "VexaSarvamService", _FakeService)
    monkeypatch.setattr(vexa_module, "process_vexa_meeting_background", fake_background)
    result = await vexa_module.reconcile_captures_on_startup()
    import asyncio

    await asyncio.sleep(0.05)
    assert result["resumed"] == 2
    assert sorted(resumed) == ["mtg_reconcile_failed", "mtg_reconcile_live"]


@pytest.mark.asyncio
async def test_wait_for_bot_active_rejects_failed_bot(monkeypatch, db_session):
    service = VexaSarvamService(vexa_api_key="test")

    async def fake_lifecycle(code):
        return {"status": "failed", "failure_stage": "join", "completion_reason": "evicted"}

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(service, "get_bot_lifecycle", fake_lifecycle)
    monkeypatch.setattr("app.services.vexa_sarvam_service.asyncio.sleep", fake_sleep)

    meeting = _make_meeting(db_session, "mtg_jointest2")
    with pytest.raises(VexaSarvamError, match="did not join"):
        await service.wait_for_bot_active(
            "abc-defg-hij", db_session, meeting, timeout_seconds=60
        )
