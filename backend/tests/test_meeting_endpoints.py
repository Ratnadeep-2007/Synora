from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.schemas.meeting import MeetingSyncResponse
from app.services.encryption_service import EncryptionService


@pytest.fixture
def seeded_meeting(
    db_session: Session,
    test_user: User,
) -> Meeting:
    meeting = Meeting(
        id="mtg_seeded_123",
        project_id="proj_default",
        user_id=test_user.id,
        provider="google",
        provider_conference_id="conferenceRecords/conf_seeded_123",
        meeting_space_id="spaces/test_space",
        title="Google Meet seeded_123",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        status="ENDED",
    )
    db_session.add(meeting)
    db_session.flush()

    participant = Participant(
        id="part_seeded_123",
        meeting_id=meeting.id,
        provider_participant_id="conferenceRecords/conf_seeded_123/participants/p1",
        display_name="Sarah Connor",
        email="sarah@example.com",
    )
    db_session.add(participant)
    db_session.flush()

    transcript = Transcript(
        id="trsc_seeded_123",
        meeting_id=meeting.id,
        provider="google",
        provider_transcript_id="conferenceRecords/conf_seeded_123/transcripts/t1",
        state="ENDED",
    )
    db_session.add(transcript)
    db_session.flush()

    entry = TranscriptEntry(
        id="tent_seeded_123",
        transcript_id=transcript.id,
        provider="google",
        provider_entry_id="conferenceRecords/conf_seeded_123/transcripts/t1/entries/e1",
        participant_id=participant.id,
        text="We should add a general onboarding agent.",
        language_code="en-US",
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(meeting)
    return meeting


def test_list_meetings(client: TestClient, test_user: User, seeded_meeting: Meeting):
    response = client.get("/meetings", headers={"X-User-ID": test_user.id})

    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 1
    assert items[0]["id"] == seeded_meeting.id
    assert items[0]["provider_conference_id"] == "conferenceRecords/conf_seeded_123"


def test_get_meeting_detail(client: TestClient, test_user: User, seeded_meeting: Meeting):
    response = client.get(f"/meetings/{seeded_meeting.id}", headers={"X-User-ID": test_user.id})

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == seeded_meeting.id
    assert len(data["participants"]) == 1
    assert data["participants"][0]["display_name"] == "Sarah Connor"
    assert len(data["transcripts"]) == 1
    assert data["transcripts"][0]["state"] == "ENDED"


def test_get_meeting_transcript_with_entries(client: TestClient, test_user: User, seeded_meeting: Meeting):
    response = client.get(f"/meetings/{seeded_meeting.id}/transcript", headers={"X-User-ID": test_user.id})

    assert response.status_code == 200
    data = response.json()
    assert data["meeting_id"] == seeded_meeting.id
    assert len(data["entries"]) == 1
    assert data["entries"][0]["text"] == "We should add a general onboarding agent."
    assert data["entries"][0]["participant_display_name"] == "Sarah Connor"


def test_get_meeting_not_found(client: TestClient, test_user: User):
    response = client.get("/meetings/mtg_nonexistent", headers={"X-User-ID": test_user.id})
    assert response.status_code == 404


def test_sync_google_meetings_no_connection(client: TestClient, test_user: User):
    # Without an active Google connection
    response = client.post("/meetings/sync", headers={"X-User-ID": test_user.id})
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "connection_not_found"


def test_sync_google_meetings_success(
    client: TestClient,
    test_user: User,
    db_session: Session,
    encryption_service: EncryptionService,
):
    # Create active connection
    creds = {"access_token": "ya29.sync_test_token", "refresh_token": "1//sync_refresh"}
    conn = SourceConnection(
        user_id=test_user.id,
        provider="google",
        provider_account_id="g_sync_sub",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict(creds),
    )
    db_session.add(conn)
    db_session.commit()

    mock_sync_return = MeetingSyncResponse(
        success=True,
        message="Synced successfully",
        total_conferences_discovered=1,
        total_conferences_synced=1,
        total_transcripts_synced=1,
        total_entries_synced=4,
        meetings=[],
    )

    with patch(
        "app.services.google_meet.GoogleMeetService.sync_conferences",
        new_callable=AsyncMock,
    ) as mock_sync:
        mock_sync.return_value = mock_sync_return

        response = client.post(
            "/meetings/sync?max_conferences=5",
            headers={"X-User-ID": test_user.id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_conferences_synced"] == 1
        assert data["total_entries_synced"] == 4
