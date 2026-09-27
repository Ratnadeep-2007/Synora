"""
Unit & Integration Tests for Checkpoint 1: Ingestion + Evidence (Phase 3).
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.source_event import SourceEvent
from app.models.user import User
from app.schemas.source_event import SourceEventCreate
from app.services.ingestion_service import IngestionError, IngestionService


@pytest.fixture
def ingestion_service() -> IngestionService:
    return IngestionService()


@pytest.fixture
def sample_meeting_with_transcript(db_session: Session, test_user: User) -> Meeting:
    """Creates a meeting with a transcript and entries for ingestion testing."""
    meeting = Meeting(
        id="mtg_test_ingestion",
        project_id="proj_101",
        user_id=test_user.id,
        provider="google",
        provider_conference_id="conf_test_ingest",
        title="Architecture Discussion",
        status="ENDED",
    )
    db_session.add(meeting)
    db_session.commit()

    participant = Participant(
        id="part_alice",
        meeting_id=meeting.id,
        provider_participant_id="conf_test_ingest/participants/p_alice",
        display_name="Alice (Lead Architect)",
    )
    transcript = Transcript(
        id="trsc_test_1",
        meeting_id=meeting.id,
        provider="google",
        provider_transcript_id="conf_test_ingest/transcripts/t1",
        state="ENDED",
    )
    db_session.add_all([participant, transcript])
    db_session.commit()

    e1 = TranscriptEntry(
        id="tent_1",
        transcript_id=transcript.id,
        provider="google",
        provider_entry_id="entry_001",
        participant_id=participant.id,
        text="We should add a general onboarding agent before BA.",
        language_code="en-US",
        start_time=datetime(2026, 9, 24, 10, 5, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 24, 10, 5, 5, tzinfo=timezone.utc),
    )
    e2 = TranscriptEntry(
        id="tent_2",
        transcript_id=transcript.id,
        provider="google",
        provider_entry_id="entry_002",
        participant_id=participant.id,
        text="One requirement is that users must provide business context.",
        language_code="en-US",
        start_time=datetime(2026, 9, 24, 10, 5, 6, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 24, 10, 5, 10, tzinfo=timezone.utc),
    )
    db_session.add_all([e1, e2])
    db_session.commit()
    db_session.refresh(meeting)
    return meeting


def test_normal_event_ingestion(ingestion_service: IngestionService, db_session: Session):
    event_in = SourceEventCreate(
        tenant_id="tenant_alpha",
        project_id="proj_101",
        source="google_meet",
        source_event_id="entry_abc_123",
        event_type="transcript_entry",
        actor_id="Bob",
        occurred_at=datetime.now(timezone.utc),
        payload={"text": "Test statement from Bob"},
    )
    event = ingestion_service.ingest_event(event_in, db_session)
    assert event.event_id.startswith("evt_")
    assert event.source == "google_meet"
    assert event.status == "received"

    # Verify persisted in database
    db_event = db_session.query(SourceEvent).filter_by(event_id=event.event_id).first()
    assert db_event is not None
    assert db_event.actor_id == "Bob"


def test_duplicate_event_deduplication(ingestion_service: IngestionService, db_session: Session):
    """The same provider event received twice must result in one logical event."""
    event_in = SourceEventCreate(
        tenant_id="tenant_alpha",
        project_id="proj_101",
        source="google_meet",
        source_event_id="entry_duplicate_target",
        event_type="transcript_entry",
        actor_id="Charlie",
        payload={"text": "Charlie speaking once"},
    )
    # First ingestion
    ev1 = ingestion_service.ingest_event(event_in, db_session)
    # Second ingestion
    ev2 = ingestion_service.ingest_event(event_in, db_session)

    assert ev1.event_id == ev2.event_id
    total_count = (
        db_session.query(SourceEvent)
        .filter_by(project_id="proj_101", source_event_id="entry_duplicate_target")
        .count()
    )
    assert total_count == 1, "Duplicate SourceEvent rows were created!"


def test_malformed_event_rejected(ingestion_service: IngestionService, db_session: Session):
    """Event missing source or source_event_id must raise IngestionError."""
    with pytest.raises(IngestionError, match="must have non-empty"):
        ingestion_service.ingest_event(
            SourceEventCreate(
                project_id="proj_101",
                source="",  # Empty source
                source_event_id="abc",
                payload={"text": "no source"},
            ),
            db_session,
        )


def test_evidence_creation_from_event(ingestion_service: IngestionService, db_session: Session):
    """Verify evidence references source event, retains verbatim content, and updates event status."""
    event_in = SourceEventCreate(
        project_id="proj_101",
        source="google_meet",
        source_event_id="speech_utterance_55",
        payload={"text": "Verbatim quote about architecture."},
        actor_id="Dave",
    )
    event = ingestion_service.ingest_event(event_in, db_session)
    assert event.status == "received"

    evidence = ingestion_service.create_evidence_from_event(
        event=event,
        db=db_session,
        meeting_id="mtg_123",
        content="Verbatim quote about architecture.",
        metadata={"confidence": 0.98},
    )

    assert evidence.id.startswith("ev_")
    assert evidence.source_event_id == event.event_id
    assert evidence.content == "Verbatim quote about architecture."
    assert evidence.actor_id == "Dave"
    assert evidence.meeting_id == "mtg_123"

    # Event status should be updated to processed
    db_session.refresh(event)
    assert event.status == "processed"


def test_meeting_normalization_to_evidence(
    ingestion_service: IngestionService,
    sample_meeting_with_transcript: Meeting,
    db_session: Session,
):
    """Normalize meeting transcript entries into SourceEvents and Evidence."""
    evidence_list = ingestion_service.normalize_meeting_to_evidence(
        meeting_id=sample_meeting_with_transcript.id,
        project_id=sample_meeting_with_transcript.project_id,
        db=db_session,
    )

    assert len(evidence_list) == 2
    e1, e2 = evidence_list

    assert "onboarding agent" in e1.content
    assert e1.actor_id == "Alice (Lead Architect)"
    assert e1.transcript_entry_id == "tent_1"
    assert e1.meeting_id == sample_meeting_with_transcript.id

    assert "business context" in e2.content
    assert e2.transcript_entry_id == "tent_2"

    # Verify idempotency: re-running normalization returns existing evidence without duplicates
    second_run = ingestion_service.normalize_meeting_to_evidence(
        meeting_id=sample_meeting_with_transcript.id,
        project_id=sample_meeting_with_transcript.project_id,
        db=db_session,
    )
    assert len(second_run) == 2
    assert second_run[0].id == e1.id
    assert second_run[1].id == e2.id

    ev_count = db_session.query(Evidence).filter_by(meeting_id=sample_meeting_with_transcript.id).count()
    assert ev_count == 2
