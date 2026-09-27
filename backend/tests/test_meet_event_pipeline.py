import base64
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.meet_event_record import MeetEventRecord
from app.models.meet_subscription import MeetSubscriptionStatus
from app.models.meeting import Meeting, Transcript, TranscriptEntry
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.source_event import SourceEvent
from app.services.encryption_service import EncryptionService
from app.services.meet_event_worker import (
    TRANSCRIPT_READY_EVENT,
    MeetEventWorker,
    extract_transcript_notification,
    parse_pubsub_envelope,
    verify_pubsub_request,
)


@pytest.fixture
def active_connection(
    db_session: Session,
    test_user,
    encryption_service: EncryptionService,
) -> SourceConnection:
    conn = SourceConnection(
        id="conn_meet_pipeline_test",
        user_id=test_user.id,
        provider="google",
        provider_account_id="google_sub_pipeline_test",
        provider_account_email="pipeline@example.com",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict(
            {
                "access_token": "ya29.pipeline_test_token",
                "refresh_token": "1//pipeline_refresh_token",
                "token_type": "Bearer",
            }
        ),
    )
    db_session.add(conn)
    db_session.commit()
    db_session.refresh(conn)
    return conn


def _envelope(payload: dict, message_id: str = "msg_1") -> dict:
    return {
        "message": {
            "data": base64.b64encode(json.dumps(payload).encode()).decode(),
            "messageId": message_id,
            "attributes": {},
        },
        "subscription": "projects/p/subscriptions/s",
    }


def _transcript_payload() -> dict:
    return {
        "id": "evt_provider_1",
        "eventType": TRANSCRIPT_READY_EVENT,
        "time": "2026-09-27T10:00:00Z",
        "data": {
            "transcript": "conferenceRecords/conf_ev_1/transcripts/tr_ev_1",
            "conferenceRecord": "conferenceRecords/conf_ev_1",
        },
    }


# 1. OAuth scope correctness -------------------------------------------------
def test_default_scopes_use_space_readonly():
    from app.core.config import settings

    joined = " ".join(settings.GOOGLE_OAUTH_SCOPES)
    assert "meetings.space.readonly" in joined


# 2. Invalid obsolete scope absent + rejected --------------------------------
def test_obsolete_conference_scope_absent_and_rejected():
    from app.core.config import settings

    joined = " ".join(settings.GOOGLE_OAUTH_SCOPES)
    assert "meetings.conference.readonly" not in joined
    with pytest.raises(ValueError):
        Settings(
            GOOGLE_OAUTH_SCOPES=[
                "openid",
                "https://www.googleapis.com/auth/meetings.conference.readonly",
            ]
        )
    with pytest.raises(ValueError):
        Settings(
            GOOGLE_OAUTH_SCOPES=[
                "openid",
                "https://www.googleapis.com/auth/drive.readonly",
            ]
        )


# 3. Subscription creation ----------------------------------------------------
def test_create_meet_subscription(client: TestClient, test_user, active_connection):
    resp = client.post(
        "/meet/subscriptions",
        json={"target_resource": "spaces/AAA", "project_id": "proj_ev_1"},
        headers={"X-User-ID": test_user.id},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["target_resource"] == "spaces/AAA"
    assert data["status"] == "active"
    assert TRANSCRIPT_READY_EVENT in data["event_types"]
    assert data["expires_at"] is not None


def test_duplicate_subscription_returns_existing(client: TestClient, test_user, active_connection):
    first = client.post(
        "/meet/subscriptions",
        json={"target_resource": "spaces/DUP"},
        headers={"X-User-ID": test_user.id},
    )
    second = client.post(
        "/meet/subscriptions",
        json={"target_resource": "spaces/DUP"},
        headers={"X-User-ID": test_user.id},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_renew_and_expiration_scan(client: TestClient, test_user, active_connection, db_session: Session):
    created = client.post(
        "/meet/subscriptions",
        json={"target_resource": "spaces/RENEW"},
        headers={"X-User-ID": test_user.id},
    ).json()
    renewed = client.post(
        f"/meet/subscriptions/{created['id']}/renew",
        headers={"X-User-ID": test_user.id},
    )
    assert renewed.status_code == 200
    assert renewed.json()["status"] == "active"
    scanned = client.post(
        "/meet/subscriptions/refresh-expirations",
        headers={"X-User-ID": test_user.id},
    )
    assert scanned.status_code == 200


# 4/5. Pub/Sub parsing + fileGenerated handling --------------------------------
def test_pubsub_envelope_parsing_and_extraction():
    parsed = parse_pubsub_envelope(_envelope(_transcript_payload(), "msg_ev_1"))
    assert parsed["message_id"] == "msg_ev_1"
    notif = extract_transcript_notification(parsed["payload"])
    assert notif["event_type"] == TRANSCRIPT_READY_EVENT
    assert notif["transcript_resource"] == "conferenceRecords/conf_ev_1/transcripts/tr_ev_1"
    assert notif["conference_record_id"] == "conferenceRecords/conf_ev_1"


def test_pubsub_push_records_event(client: TestClient, test_user):
    resp = client.post("/pubsub/meet-events", json=_envelope(_transcript_payload(), "msg_ev_2"))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["acknowledged"] is False
    assert data["action"] == "recorded"


def test_pubsub_unsupported_event_ignored(client: TestClient):
    payload = {"id": "evt_other", "eventType": "google.workspace.meet.recording.v2.fileGenerated"}
    resp = client.post("/pubsub/meet-events", json=_envelope(payload, "msg_other"))
    assert resp.status_code == 200
    assert resp.json()["action"] == "ignored"


def test_pubsub_malformed_envelope_rejected(client: TestClient):
    resp = client.post("/pubsub/meet-events", json={"nope": True})
    assert resp.status_code == 400


# 6/18. Deduplication + redelivery ---------------------------------------------
def test_pubsub_redelivery_deduplicated(client: TestClient, db_session: Session):
    first = client.post("/pubsub/meet-events", json=_envelope(_transcript_payload(), "msg_ev_3"))
    second = client.post("/pubsub/meet-events", json=_envelope(_transcript_payload(), "msg_ev_3"))
    assert first.json()["action"] == "recorded"
    assert second.json()["action"] == "duplicate"
    rows = (
        db_session.query(MeetEventRecord)
        .filter(MeetEventRecord.provider_event_id == "evt_provider_1")
        .all()
    )
    assert len(rows) == 1


# 21. Project Agent receives correct project context ---------------------------
def test_pipeline_uses_tenant_and_context(db_session: Session):
    from app.models.meeting import Participant
    from app.services.pipeline_coordinator import PipelineCoordinator
    from datetime import datetime, timezone

    meeting = Meeting(
        id="meet_ctx_1",
        user_id="usr_ctx",
        project_id="proj_ctx_1",
        provider="google",
        provider_conference_id="conferenceRecords/conf_ctx_1",
        title="Ctx meeting",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
    )
    db_session.add(meeting)
    db_session.flush()
    tr = Transcript(
        id="tr_ctx_1",
        meeting_id=meeting.id,
        provider="google",
        provider_transcript_id="conferenceRecords/conf_ctx_1/transcripts/t1",
        state="AVAILABLE",
    )
    db_session.add(tr)
    db_session.flush()
    part = Participant(
        id="part_ctx_1",
        meeting_id=meeting.id,
        provider_participant_id="conferenceRecords/conf_ctx_1/participants/p1",
        display_name="Ctx Speaker",
    )
    db_session.add(part)
    db_session.flush()
    db_session.add(
        TranscriptEntry(
            id="tent_ctx_1",
            transcript_id=tr.id,
            provider="google",
            provider_entry_id="conferenceRecords/conf_ctx_1/transcripts/t1/entries/e1",
            participant_id=part.id,
            text="We should add a review step before release.",
        )
    )
    db_session.commit()

    result = PipelineCoordinator().process_meeting_with_context(
        meeting_id=meeting.id,
        project_id="proj_ctx_1",
        db=db_session,
        actor_id="meet_event:mev_test",
        workspace_id="ws_ctx",
        tenant_id="tenant_ctx",
        correlation_id="mev_test",
    )
    assert result.success is True
    assert result.authoritative_version_before == result.authoritative_version_after
    events = (
        db_session.query(SourceEvent)
        .filter(SourceEvent.project_id == "proj_ctx_1")
        .all()
    )
    assert len(events) >= 1


# 22. High-impact changes require approval --------------------------------------
def test_high_impact_changes_stay_proposed(db_session: Session):
    from datetime import datetime, timezone
    from app.models.meeting import Participant
    from app.services.pipeline_coordinator import PipelineCoordinator

    meeting = Meeting(
        id="meet_hi_1",
        user_id="usr_hi",
        project_id="proj_hi_1",
        provider="google",
        provider_conference_id="conferenceRecords/conf_hi_1",
        title="Hi meeting",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
    )
    db_session.add(meeting)
    db_session.flush()
    tr = Transcript(
        id="tr_hi_1",
        meeting_id=meeting.id,
        provider="google",
        provider_transcript_id="conferenceRecords/conf_hi_1/transcripts/t1",
        state="AVAILABLE",
    )
    db_session.add(tr)
    db_session.flush()
    db_session.add(
        TranscriptEntry(
            id="tent_hi_1",
            transcript_id=tr.id,
            provider="google",
            provider_entry_id="conferenceRecords/conf_hi_1/transcripts/t1/entries/e1",
            text="Okay, let's do it and place the onboarding agent before BA.",
        )
    )
    db_session.commit()
    result = PipelineCoordinator().process_meeting(
        meeting_id=meeting.id, project_id="proj_hi_1", db=db_session
    )
    assert result.success is True
    assert result.authoritative_version_before == result.authoritative_version_after
    assert result.proposals_created >= 1
