from fastapi import BackgroundTasks
import pytest
from app.api import vexa_meetings


@pytest.mark.asyncio
async def test_capture_queue_releases_request_session_before_long_worker(monkeypatch):
    events = []

    class RequestSession:
        def close(self):
            events.append("request_session_closed")

    async def process(meeting_id):
        assert events == ["request_session_closed"]
        events.append(meeting_id)

    monkeypatch.setattr(vexa_meetings, "process_vexa_meeting_background", process)
    tasks = BackgroundTasks()
    vexa_meetings._queue_capture_processing(tasks, RequestSession(), "mtg_regression")
    assert events == ["request_session_closed"]
    assert len(tasks.tasks) == 1
    await tasks()
    assert events == ["request_session_closed", "mtg_regression"]
