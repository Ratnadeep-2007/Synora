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


def _make_meeting(db, meeting_id="mtg_jointest"):
    from app.models.meeting import Meeting

    meeting = Meeting(
        id=meeting_id,
        user_id="usr_test",
        provider="google_meet",
        provider_conference_id="abc-defg-hij",
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
