import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.project_state import ProjectState


def test_ingest_raw_transcript_text(db_session: Session, client: TestClient):
    """Verifies ingesting raw speaker-colon text creates meeting, participants, and entries."""
    raw_text = """
    Sarah Chen: We decided to deploy PostgreSQL 16 on AWS Aurora.
    Marcus Vance: Agreed. We will also add Redis Cluster for session caching.
    Elena Rostova: Let me write the migration script by Friday.
    """

    response = client.post(
        "/meetings/ingest-transcript",
        json={
            "project_id": "proj_default",
            "title": "Architecture Sync - Zero Quota",
            "provider": "manual_transcript",
            "raw_transcript": raw_text,
            "auto_process": True,
        },
        headers={"X-User-ID": "usr_synesis_default"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["entries_count"] == 3
    assert data["project_id"] == "proj_default"
    assert "meeting_id" in data
    assert data["pipeline_result"] is not None

    # Verify database persistence
    meeting_id = data["meeting_id"]
    meeting = db_session.query(Meeting).filter(Meeting.id == meeting_id).first()
    assert meeting is not None
    assert meeting.title == "Architecture Sync - Zero Quota"
    assert meeting.provider == "manual_transcript"

    participants = db_session.query(Participant).filter(Participant.meeting_id == meeting_id).all()
    assert len(participants) == 3
    names = {p.display_name for p in participants}
    assert "Sarah Chen" in names
    assert "Marcus Vance" in names
    assert "Elena Rostova" in names

    transcript = db_session.query(Transcript).filter(Transcript.meeting_id == meeting_id).first()
    assert transcript is not None
    entries = db_session.query(TranscriptEntry).filter(TranscriptEntry.transcript_id == transcript.id).all()
    assert len(entries) == 3


def test_ingest_structured_entries(db_session: Session, client: TestClient):
    """Verifies ingesting structured entries without auto-processing."""
    entries_payload = [
        {"speaker": "Alice Security", "text": "All endpoints must enforce OAuth2 JWT verification."},
        {"speaker": "Bob DevOps", "text": "We will configure Linkerd mTLS across all Kubernetes pods."},
    ]

    response = client.post(
        "/meetings/ingest-transcript",
        json={
            "project_id": "proj_default",
            "title": "Security Review Session",
            "provider": "google_meet_captions",
            "entries": entries_payload,
            "auto_process": False,
        },
        headers={"X-User-ID": "usr_synesis_default"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["entries_count"] == 2
    assert data["pipeline_result"] is None
