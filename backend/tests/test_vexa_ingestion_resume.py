import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.evidence import Evidence
from app.models.meeting import Meeting, Transcript, TranscriptEntry
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.models.source_event import SourceEvent
from app.services.vexa_sarvam_service import VexaSarvamService


def segment(index, text, start, end, speaker="Unknown Speaker"):
    return {"id": f"seg{index}", "text": text, "speaker": speaker, "start_seconds": start, "end_seconds": end}


def test_routing_groups_preserve_entries_and_project_introductions():
    items = [segment(0,"For Harbor Inventory Demo.",0,3),segment(1,"Keep PostgreSQL.",3,6),segment(2,"For Nimbus Cold Chain.",7,10),segment(3,"Buffer readings offline.",10,14)]
    assert VexaSarvamService._routing_groups(items) == [[0,1],[2,3]]
    assert [i for group in VexaSarvamService._routing_groups(items) for i in group] == list(range(4))


def test_routing_groups_bound_speaker_gap_time_and_size():
    items = [segment(0,"a"*400,0,5),segment(1,"b"*400,5,10),segment(2,"c",10,11,"SPEAKER_01"),segment(3,"d",15,16,"SPEAKER_01"),segment(4,"e",16,70,"SPEAKER_01")]
    assert VexaSarvamService._routing_groups(items) == [[0],[1],[2],[3],[4]]


def test_partial_ingestion_resumes_without_rewriting_evidence(monkeypatch, db_session, test_user):
    db = db_session
    service = VexaSarvamService()
    calls = []
    monkeypatch.setattr(service,"_get_projects",lambda db: [])
    monkeypatch.setattr(service,"_resolve_project",lambda content,*args: calls.append(content) or SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID)
    monkeypatch.setattr("app.services.vexa_sarvam_service.PipelineCoordinator",lambda: SimpleNamespace(process_meeting_with_context=lambda **kwargs: None))
    meeting = Meeting(id="mtg_resume",user_id=test_user.id,workspace_id="ws_default",provider="google",provider_conference_id="abc-defg-hij",start_time=datetime.now(timezone.utc),metadata_json="{}")
    db.add(meeting);db.flush()
    transcript = Transcript(meeting_id=meeting.id,provider="google",provider_transcript_id="vexa_mtg_resume")
    db.add(transcript);db.flush()
    first = TranscriptEntry(transcript_id=transcript.id,provider="google",provider_entry_id="vexa_whisper_faster_whisper:seg0",text="For Harbor Inventory Demo.")
    event = SourceEvent(source="google_meet",project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,source_event_id="original-provider-key",payload_json="{}")
    db.add_all([first,event]);db.flush()
    evidence = Evidence(project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,source="google_meet",source_event_id=event.event_id,meeting_id=meeting.id,transcript_id=transcript.id,transcript_entry_id=first.id,content=first.text)
    db.add(evidence);db.commit()
    evidence_id,original_content = evidence.id,evidence.content
    items = [segment(0,first.text,0,3),segment(1,"Keep PostgreSQL.",3,6),segment(2,"For Nimbus Cold Chain.",7,10)]
    result = service._persist_transcript(meeting,items,"whisper_faster_whisper","small.en","job","en","recording",db)
    assert result["entries_count"] == 3
    assert db.query(TranscriptEntry).filter_by(transcript_id=transcript.id).count() == 3
    assert db.query(Evidence).filter_by(meeting_id=meeting.id).count() == 3
    assert db.get(Evidence,evidence_id).content == original_content
    # Explicit named projects absent from the catalog remain quarantined
    # across their subsequent fragments without a semantic name guess.
    assert len(calls) == 0
    assert db.query(SourceEvent).filter(SourceEvent.source_event_id.like("vexa:mtg_resume:%")).count() == 2
    service._persist_transcript(meeting,items,"whisper_faster_whisper","small.en","job","en","recording",db)
    assert db.query(Evidence).filter_by(meeting_id=meeting.id).count() == 3
    assert db.query(TranscriptEntry).filter_by(transcript_id=transcript.id).count() == 3
    assert len(calls) == 0
