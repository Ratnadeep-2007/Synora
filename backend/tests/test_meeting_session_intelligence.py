from datetime import datetime, timedelta, timezone
import json

from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.source_event import SourceEvent
from app.services.meeting_session_intelligence import MeetingSessionIntelligenceService


def test_meeting_session_intelligence_persists_session_projection(db_session, test_user):
    meeting = Meeting(
        id="mtg_session_intel_1",
        user_id=test_user.id,
        project_id="proj_session_intel",
        provider="google",
        provider_conference_id="conferenceRecords/session_intel_1",
        title="Architecture Sync",
        start_time=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 10, 2, 10, 5, tzinfo=timezone.utc),
        status="ENDED",
    )
    participant = Participant(
        id="part_session_alice",
        meeting_id=meeting.id,
        provider_participant_id="alice",
        display_name="Alice",
    )
    transcript = Transcript(
        id="trsc_session_intel_1",
        meeting_id=meeting.id,
        provider="google",
        provider_transcript_id="google_session_intel_1",
        state="ENDED",
        start_time=meeting.start_time,
        end_time=meeting.end_time,
    )
    db_session.add_all([meeting, participant, transcript])
    db_session.flush()

    base_time = meeting.start_time
    entries = [
        TranscriptEntry(
            id="tent_session_1",
            transcript_id=transcript.id,
            provider="google",
            provider_entry_id="entry_session_1",
            participant_id=participant.id,
            text="We decided to use Redis for session caching.",
            start_time=base_time,
            end_time=base_time + timedelta(seconds=5),
        ),
        TranscriptEntry(
            id="tent_session_2",
            transcript_id=transcript.id,
            provider="google",
            provider_entry_id="entry_session_2",
            participant_id=participant.id,
            text="Please document the cache invalidation flow.",
            start_time=base_time + timedelta(seconds=10),
            end_time=base_time + timedelta(seconds=15),
        ),
        TranscriptEntry(
            id="tent_session_3",
            transcript_id=transcript.id,
            provider="google",
            provider_entry_id="entry_session_3",
            participant_id=participant.id,
            text="Alice will add the cache invalidation tests by Friday.",
            start_time=base_time + timedelta(seconds=60),
            end_time=base_time + timedelta(seconds=65),
        ),
    ]
    db_session.add_all(entries)
    db_session.flush()

    evidence = []
    for idx, entry in enumerate(entries, start=1):
        event = SourceEvent(
            event_id=f"evt_session_{idx}",
            tenant_id="tenant_default",
            project_id=meeting.project_id,
            source="google_meet",
            source_event_id=entry.provider_entry_id,
            event_type="transcript_entry",
            actor_id="Alice",
            occurred_at=entry.start_time,
            payload_json=json.dumps({"text": entry.text}),
            status="received",
        )
        db_session.add(event)
        db_session.flush()
        evidence.append(
            Evidence(
                id=f"ev_session_{idx}",
                project_id=meeting.project_id,
                source="google_meet",
                source_event_id=event.event_id,
                meeting_id=meeting.id,
                transcript_id=transcript.id,
                transcript_entry_id=entry.id,
                actor_id="Alice",
                occurred_at=entry.start_time,
                content=entry.text,
            )
        )
    db_session.add_all(evidence)
    db_session.flush()

    decision = CandidateKnowledge(
        id="cand_session_decision",
        project_id=meeting.project_id,
        meeting_id=meeting.id,
        category="decision_candidate",
        classification="Decision",
        title="Use Redis for session caching",
        content="The team decided to use Redis for session caching.",
        confidence=0.95,
        evidence_ids_json=json.dumps(["ev_session_1"]),
        status="approved",
    )
    action = CandidateKnowledge(
        id="cand_session_action",
        project_id=meeting.project_id,
        meeting_id=meeting.id,
        category="action_item",
        classification="ActionItem",
        title="Add cache invalidation tests",
        content="Alice will add the cache invalidation tests by Friday.",
        confidence=0.93,
        evidence_ids_json=json.dumps(["ev_session_3"]),
        status="approved",
    )
    db_session.add_all([decision, action])
    db_session.commit()

    service = MeetingSessionIntelligenceService()
    result = service.get_or_build(
        meeting_id=meeting.id,
        db=db_session,
        candidates=[decision, action],
        memory_results={
            meeting.project_id: {
                "state_version_before": 3,
                "state_version_after": 4,
                "applied": 2,
                "skipped": 0,
            }
        },
        persist=True,
    )

    assert result["segment_count"] == 2
    assert result["participant_count"] == 1
    assert result["participants"] == ["Alice"]
    assert result["decisions"][0]["title"] == "Use Redis for session caching"
    assert result["action_items"][0]["owner_hints"] == ["Alice"]
    assert result["action_items"][0]["due_hint"].lower().startswith("friday")
    assert result["memory_delta"][0]["version_before"] == 3
    assert result["memory_delta"][0]["version_after"] == 4

    db_session.refresh(meeting)
    metadata = json.loads(meeting.metadata_json or "{}")
    assert metadata["session_intelligence"]["meeting_id"] == meeting.id
    assert metadata["session_intelligence"]["version"] == "v2"
    assert metadata["session_intelligence"]["transcript_entry_count"] == 3
    assert metadata["session_intelligence"]["routing_window_count"] == 2
    assert metadata["session_intelligence"]["source_sync"]["retrieval_mode"] == "completed_meeting_once"
    assert metadata["session_intelligence"]["source_sync"]["intelligence_input"] == "full_persisted_transcript"
    assert metadata["session_intelligence"]["source_sync"]["google_api_calls_after_persistence"] == 0


def test_meet_worker_uses_45_second_session_windows():
    worker = __import__(
        "app.services.meet_event_worker",
        fromlist=["MeetEventWorker"],
    ).MeetEventWorker()
    base = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)

    def entry(idx, offset):
        return type(
            "Entry",
            (),
            {
                "id": f"entry_{idx}",
                "text": f"utterance {idx}",
                "start_time": base + timedelta(seconds=offset),
            },
        )()

    entries = [entry(1, 0), entry(2, 10), entry(3, 55)]
    windows = worker._segment_entries(entries)

    assert len(windows) == 2
    assert len(windows[0]) == 2
    assert len(windows[1]) == 1



def test_meeting_intelligence_keeps_full_context_across_routing_window_boundary(
    db_session, test_user
):
    """A >45s gap creates a timeline window, not a separate intelligence pass."""
    meeting = Meeting(
        id="mtg_session_full_context",
        user_id=test_user.id,
        project_id="proj_full_context",
        provider="google",
        provider_conference_id="conferenceRecords/full_context",
        title="Full Context Sync",
        start_time=datetime(2026, 10, 2, 11, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 10, 2, 11, 8, tzinfo=timezone.utc),
        status="ENDED",
    )
    participant = Participant(
        id="part_full_context",
        meeting_id=meeting.id,
        provider_participant_id="speaker",
        display_name="Speaker",
    )
    transcript = Transcript(
        id="trsc_full_context",
        meeting_id=meeting.id,
        provider="google",
        provider_transcript_id="google_full_context",
        state="ENDED",
        start_time=meeting.start_time,
        end_time=meeting.end_time,
    )
    db_session.add_all([meeting, participant, transcript])
    db_session.flush()

    base = meeting.start_time
    entries = [
        TranscriptEntry(
            id="tent_fc_1",
            transcript_id=transcript.id,
            provider="google",
            provider_entry_id="entry_fc_1",
            participant_id=participant.id,
            text="We are discussing cache invalidation for the API.",
            start_time=base,
            end_time=base + timedelta(seconds=5),
        ),
        TranscriptEntry(
            id="tent_fc_2",
            transcript_id=transcript.id,
            provider="google",
            provider_entry_id="entry_fc_2",
            participant_id=participant.id,
            text="We decided Redis should hold the session cache.",
            start_time=base + timedelta(seconds=60),
            end_time=base + timedelta(seconds=65),
        ),
        TranscriptEntry(
            id="tent_fc_3",
            transcript_id=transcript.id,
            provider="google",
            provider_entry_id="entry_fc_3",
            participant_id=participant.id,
            text="Alice will document the invalidation flow by Friday.",
            start_time=base + timedelta(seconds=70),
            end_time=base + timedelta(seconds=75),
        ),
    ]
    db_session.add_all(entries)
    db_session.flush()

    evidence = []
    for idx, entry in enumerate(entries, start=1):
        event = SourceEvent(
            event_id=f"evt_fc_{idx}",
            tenant_id="tenant_default",
            project_id=meeting.project_id,
            source="google_meet",
            source_event_id=entry.provider_entry_id,
            event_type="transcript_entry",
            actor_id="Alice",
            occurred_at=entry.start_time,
            payload_json=json.dumps({"text": entry.text}),
            status="received",
        )
        db_session.add(event)
        db_session.flush()
        evidence.append(
            Evidence(
                id=f"ev_fc_{idx}",
                project_id=meeting.project_id,
                source="google_meet",
                source_event_id=event.event_id,
                meeting_id=meeting.id,
                transcript_id=transcript.id,
                transcript_entry_id=entry.id,
                actor_id="Alice",
                occurred_at=entry.start_time,
                content=entry.text,
            )
        )
    db_session.add_all(evidence)
    db_session.flush()

    decision = CandidateKnowledge(
        id="cand_fc_decision",
        project_id=meeting.project_id,
        meeting_id=meeting.id,
        category="decision_candidate",
        classification="Decision",
        title="Use Redis for session cache",
        content=(
            "The team discussed invalidation first, then decided to use Redis "
            "for the session cache after the 60-second conversation gap."
        ),
        confidence=0.96,
        evidence_ids_json=json.dumps(["ev_fc_2", "ev_fc_3"]),
        status="approved",
    )
    db_session.add(decision)
    db_session.commit()

    payload = MeetingSessionIntelligenceService().build_session_intelligence(
        meeting_id=meeting.id,
        db=db_session,
        candidates=[decision],
        memory_results={
            meeting.project_id: {
                "state_version_before": 4,
                "state_version_after": 5,
                "applied": 1,
                "skipped": 0,
            }
        },
    )

    assert payload["routing_window_count"] == 2
    assert payload["decisions"][0]["title"] == "Use Redis for session cache"
    assert payload["decisions"][0]["evidence_ids"] == ["ev_fc_2", "ev_fc_3"]
    assert payload["source_sync"]["google_api_calls_after_persistence"] == 0
