"""Meeting hard-delete contract.

DELETE /meetings/{id} must remove the meeting tree (participants,
transcripts, entries) and the meeting canvas, while preserving evidence rows
with their meeting links cleared — evidence is immutable ground truth and
candidate knowledge built from it must keep provenance.
"""

from app.models.evidence import Evidence
from app.models.excalidraw import ExcalidrawArtifact
from app.models.meeting import (
    Meeting,
    Participant,
    Transcript,
    TranscriptEntry,
)
from app.models.source_event import SourceEvent


def _seed_meeting_tree(db_session, user_id="usr_test_user_001", meeting_id="mtg_del_test"):
    meeting = Meeting(
        id=meeting_id,
        user_id=user_id,
        provider="google_meet",
        provider_conference_id=f"conf_{meeting_id}",
        title="Delete me",
        status="ENDED",
    )
    db_session.add(meeting)
    participant = Participant(
        id=f"part_{meeting_id}",
        meeting_id=meeting_id,
        provider_participant_id="part_speaker_00",
        display_name="SPEAKER_00",
    )
    db_session.add(participant)
    transcript = Transcript(
        id=f"trsc_{meeting_id}",
        meeting_id=meeting_id,
        provider="google_meet",
        provider_transcript_id=f"trsc_conf_{meeting_id}",
        state="AVAILABLE",
    )
    db_session.add(transcript)
    entry = TranscriptEntry(
        id=f"tent_{meeting_id}",
        transcript_id=transcript.id,
        provider="google_meet",
        provider_entry_id="entry_0",
        participant_id=participant.id,
        text="We will use face recognition.",
        language_code="en-US",
    )
    db_session.add(entry)
    event = SourceEvent(
        project_id="proj_default",
        source="google_meet",
        source_event_id=f"evt_{meeting_id}",
        event_type="transcript_entry",
        actor_id="SPEAKER_00",
        payload_json='{"text": "We will use face recognition."}',
    )
    db_session.add(event)
    db_session.flush()
    evidence = Evidence(
        project_id="proj_default",
        source="google_meet",
        source_event_id=event.event_id,
        meeting_id=meeting_id,
        transcript_id=transcript.id,
        transcript_entry_id=entry.id,
        actor_id="SPEAKER_00",
        content="We will use face recognition.",
    )
    db_session.add(evidence)
    db_session.add(
        ExcalidrawArtifact(
            project_id=f"meeting_canvas:{meeting_id}",
            name="Meeting Notes",
        )
    )
    db_session.commit()
    return meeting, evidence


def test_delete_meeting_removes_tree_but_keeps_evidence(client, db_session):
    meeting, evidence = _seed_meeting_tree(db_session)
    evidence_id = evidence.id

    resp = client.delete(
        f"/meetings/{meeting.id}", headers={"X-User-ID": "usr_test_user_001"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    # Meeting tree gone.
    assert db_session.query(Meeting).filter(Meeting.id == meeting.id).first() is None
    assert (
        db_session.query(Participant).filter(Participant.meeting_id == meeting.id).count()
        == 0
    )
    assert (
        db_session.query(Transcript).filter(Transcript.meeting_id == meeting.id).count()
        == 0
    )
    assert (
        db_session.query(TranscriptEntry)
        .filter(TranscriptEntry.transcript_id == f"trsc_{meeting.id}")
        .count()
        == 0
    )
    # Meeting canvas gone.
    assert (
        db_session.query(ExcalidrawArtifact)
        .filter(ExcalidrawArtifact.project_id == f"meeting_canvas:{meeting.id}")
        .count()
        == 0
    )
    # Evidence preserved with links cleared.
    kept = db_session.query(Evidence).filter(Evidence.id == evidence_id).first()
    assert kept is not None
    assert kept.meeting_id is None
    assert kept.content == "We will use face recognition."

    # Re-get is 404.
    again = client.get(
        f"/meetings/{meeting.id}", headers={"X-User-ID": "usr_test_user_001"}
    )
    assert again.status_code == 404


def test_delete_meeting_404_for_unknown_or_other_user(client, db_session):
    resp = client.delete(
        "/meetings/mtg_does_not_exist", headers={"X-User-ID": "usr_test_user_001"}
    )
    assert resp.status_code == 404

    meeting, _ = _seed_meeting_tree(
        db_session, user_id="usr_test_user_001", meeting_id="mtg_del_other"
    )
    other = client.delete(
        f"/meetings/{meeting.id}", headers={"X-User-ID": "usr_synesis_default"}
    )
    assert other.status_code == 404
