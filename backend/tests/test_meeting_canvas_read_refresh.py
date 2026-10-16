"""Meeting canvas reads must never burn LLM quota; refresh is explicit."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.meetings as meetings_api
from app.models.excalidraw import ExcalidrawArtifact
from app.models.meeting import Meeting
from app.models.user import User


@pytest.fixture
def seeded_canvas_meeting(db_session: Session, test_user: User) -> Meeting:
    meeting = Meeting(
        id="mtg_canvas_read_1",
        project_id="proj_default",
        user_id=test_user.id,
        provider="google",
        provider_conference_id="dei-test-canvas",
        title="Canvas read test",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        status="ENDED",
    )
    db_session.add(meeting)
    db_session.commit()
    return meeting


def _seed_artifact(db_session: Session, meeting_id: str, meta: dict) -> ExcalidrawArtifact:
    artifact = ExcalidrawArtifact(
        id="art_canvas_read_1",
        project_id=f"meeting_canvas:{meeting_id}",
        tenant_id="default_tenant",
        name="Meeting Notes",
        version=3,
        elements_json="[]",
        app_state_json=json.dumps({"viewBackgroundColor": "#ffffff", "meeting_canvas": meta}),
        extracted_nodes_json="[]",
    )
    db_session.add(artifact)
    db_session.commit()
    return artifact


class _CountingSync:
    calls = 0

    def sync_meeting_canvas(self, **kwargs):
        type(self).calls += 1
        return {"meeting_id": kwargs["meeting_id"], "synced": True, "reason": "fake_sync"}


@pytest.fixture
def counting_sync(monkeypatch):
    _CountingSync.calls = 0
    monkeypatch.setattr(meetings_api, "MeetingSessionIntelligenceService", _CountingSync)
    return _CountingSync


def test_canvas_read_never_syncs_by_default(client: TestClient, test_user: User, seeded_canvas_meeting, counting_sync):
    response = client.get(f"/meetings/{seeded_canvas_meeting.id}/canvas", headers={"X-User-ID": test_user.id})
    assert response.status_code == 200
    body = response.json()
    assert body["synced"] is False
    assert body["reason"] == "cached"
    assert counting_sync.calls == 0


def test_canvas_read_partial_ai_status_still_cached(client: TestClient, db_session: Session, test_user: User, seeded_canvas_meeting, counting_sync):
    _seed_artifact(db_session, seeded_canvas_meeting.id, {"ai_status": "partial", "evidence_ids": []})
    response = client.get(f"/meetings/{seeded_canvas_meeting.id}/canvas", headers={"X-User-ID": test_user.id})
    assert response.status_code == 200
    body = response.json()
    assert body["synced"] is False
    assert body["ai_status"] == "partial"
    assert body["refresh_available"] is True
    assert counting_sync.calls == 0


def test_canvas_refresh_respects_cooldown(client: TestClient, db_session: Session, test_user: User, seeded_canvas_meeting, counting_sync):
    recent = datetime.now(timezone.utc).isoformat()
    _seed_artifact(db_session, seeded_canvas_meeting.id, {"ai_status": "partial", "evidence_ids": [], "last_refresh_attempt_at": recent})
    response = client.get(f"/meetings/{seeded_canvas_meeting.id}/canvas?refresh=true", headers={"X-User-ID": test_user.id})
    assert response.status_code == 200
    body = response.json()
    assert body["synced"] is False
    assert body["reason"] == "refresh_cooldown"
    assert body["retry_after_seconds"] > 0
    assert counting_sync.calls == 0


def test_canvas_refresh_syncs_once_after_cooldown(client: TestClient, db_session: Session, test_user: User, seeded_canvas_meeting, counting_sync):
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _seed_artifact(db_session, seeded_canvas_meeting.id, {"ai_status": "deterministic", "evidence_ids": [], "last_refresh_attempt_at": old})
    response = client.get(f"/meetings/{seeded_canvas_meeting.id}/canvas?refresh=true", headers={"X-User-ID": test_user.id})
    assert response.status_code == 200
    assert response.json()["reason"] == "fake_sync"
    assert counting_sync.calls == 1
