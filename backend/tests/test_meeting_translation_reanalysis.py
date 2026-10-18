import json
from types import SimpleNamespace

import httpx

from app.core.config import settings
from app.services import translation_service as translation


HINDI = "\u0938\u094d\u091f\u0949\u0915 \u092c\u0926\u0932\u0928\u0947 \u0938\u0947 \u092a\u0939\u0932\u0947 \u0905\u0928\u0941\u092e\u0924\u093f \u091c\u0930\u0942\u0930\u0940 \u0939\u0948"


def configure(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SARVAM_TRANSLATE_ENABLED", True)
    monkeypatch.setattr(settings, "TRANSLATION_FALLBACK_ENABLED", True)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-groq-key")


def test_sarvam_no_credits_uses_independent_translation(monkeypatch):
    configure(monkeypatch)
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, *args, **kwargs):
            calls.append(kwargs["json"])
            return httpx.Response(402, json={"error": "No credits"})

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr("app.services.llm.GroqLLMClient.generate_structured", lambda self, prompt, schema: schema.model_validate({"translations": [{"id": 0, "text": "Approval is required before changing stock."}]}))
    details = {}
    source = [HINDI, "Existing English statement."]
    result, status = translation.translate_texts(source, details=details)
    assert source[0] == HINDI
    assert result == ["Approval is required before changing stock.", source[1]]
    assert status == "translated"
    assert details["provider"] == "groq/" + settings.TRANSLATION_GROQ_MODEL
    assert details["successful_ids"] == [0]
    assert len(calls) == 1


def test_invalid_translation_ids_and_script_are_not_accepted(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(settings, "SARVAM_TRANSLATE_ENABLED", False)
    monkeypatch.setattr("app.services.llm.GroqLLMClient.generate_structured", lambda self, prompt, schema: schema.model_validate({"translations": [{"id": 99, "text": "Invented fact."}, {"id": 0, "text": HINDI}]}))
    details = {}
    result, status = translation.translate_texts([HINDI], details=details)
    assert result == [HINDI]
    assert status == "unavailable"
    assert details["pending_count"] == 1
    assert translation.english_note_text(HINDI, json.dumps({"translation_required": True})) == ""


def test_marathi_hint_and_english_skip(monkeypatch):
    assert translation.normalize_source_language("mr") == "mr-IN"
    assert translation.needs_translation("aapan udya karuya", "mr-IN")
    monkeypatch.setattr(translation, "_llm_translations", lambda *args: (_ for _ in ()).throw(AssertionError("English must not call a translation provider")))
    assert translation.translate_texts(["The stock remains unchanged."]) == (["The stock remains unchanged."], "skipped")


def test_unidentified_blank_fragment_does_not_discard_valid_translations(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(settings, "SARVAM_TRANSLATE_ENABLED", False)
    monkeypatch.setattr("app.services.llm.GroqLLMClient.generate_structured", lambda self, prompt, schema: schema.model_validate({"translations": ["", {"id": 0, "text": "Approval is required."}]}))
    details = {}
    result, status = translation.translate_texts([HINDI], details=details)
    assert result == ["Approval is required."]
    assert status == "translated"


def test_mixed_meeting_translates_roman_speech_alongside_native_script(monkeypatch):
    calls = []
    def translate(texts, **kwargs):
        calls.append(kwargs)
        return ["Approval is required.", "Notify the manager immediately."], "translated"
    monkeypatch.setattr(translation, "translate_texts", translate)
    mapping, status, source = translation.translate_segments([
        {"id": "native", "text": HINDI},
        {"id": "roman", "text": "manager ko turanth alert milna chaiye"},
    ], "unknown")
    assert calls[0]["source_language"] == "hi-IN"
    assert mapping["roman"] == "Notify the manager immediately."
    translation.translate_segments([{"id": "native", "text": HINDI}], "en-US")
    assert calls[-1]["source_language"] == "hi-IN"


def test_explicit_project_exclusion_is_not_a_name_match():
    from app.services.vexa_sarvam_service import VexaSarvamService
    projects = [SimpleNamespace(id="birch", name="Birch_inventory")]
    exclude = VexaSarvamService._explicit_project_exclusions
    assert exclude("This is not a Birch issue.", projects) == {"birch"}
    assert exclude("Do not write these notes in Birch. Cedar has an unapproved budget.", projects) == {"birch"}
    assert exclude("Nobody can approve their own correction in Birch.", projects) == set()


def test_project_switch_quarantines_every_unknown_group_until_known_return():
    from app.services.vexa_sarvam_service import VexaSarvamService
    texts = ["For Birch inventory, use PostgreSQL.", "Now switching to a different project.",
             "This is not a Birch issue.", "For Cedar cold chain", "trucks need sensors",
             "For refrigerated delivery", "Do not write these notes in Birch.",
             "Unapproved budget of 50000.", "We will automate it.",
             "Birch inventory has a stock blocker.", "Final recap for Birch."]
    segments = [{"text": text, "speaker": "S", "start_seconds": i * 10, "end_seconds": i * 10 + 1} for i, text in enumerate(texts)]
    scoped = VexaSarvamService._scoped_routing_groups(segments, [SimpleNamespace(name="Birch_inventory")])
    quarantined = {index for group, unknown in scoped if unknown for index in group}
    assert quarantined == set(range(1, 9))


def test_reanalysis_reuses_sources_and_updates_only_derived_metadata(monkeypatch, db_session, test_user):
    from app.models.context_resolution import UnknownContextItem
    from app.models.evidence import Evidence
    from app.models.meeting import Meeting, Transcript, TranscriptEntry
    from app.models.project import Project, Workspace, SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    from app.models.source_event import SourceEvent
    from app.services.meeting_reanalysis_service import reanalyze_saved_meeting

    db = db_session
    db.add(Workspace(id="ws_reanalysis", name="Test workspace"))
    db.flush()
    db.add(Project(id="proj_birch", workspace_id="ws_reanalysis", name="Birch inventory"))
    meeting = Meeting(id="mtg_saved_retry", workspace_id="ws_reanalysis", project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, user_id=test_user.id, provider_conference_id="retry-abc-def", metadata_json="{}")
    db.add(meeting)
    db.flush()
    transcript = Transcript(meeting_id=meeting.id, provider_transcript_id="saved-retry-transcript")
    db.add(transcript)
    db.flush()
    entry = TranscriptEntry(id="entry_saved", transcript_id=transcript.id, provider_entry_id="saved-0", text=HINDI, language_code="hi-IN")
    event = SourceEvent(project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, source="google_meet", source_event_id="saved-event", payload_json=json.dumps({"text": HINDI}))
    db.add_all([entry, event])
    db.flush()
    evidence = Evidence(id="ev_saved", project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, source="google_meet", source_event_id=event.event_id, meeting_id=meeting.id, transcript_id=transcript.id, transcript_entry_id=entry.id, content=HINDI)
    db.add(evidence)
    item = UnknownContextItem(project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, source="google_meet", evidence_id=evidence.id, content=HINDI)
    db.add(item)
    db.commit()

    def translate(segments, source_language, translation_metadata):
        translation_metadata.update(provider="test-translator", successful_ids=[0])
        return {entry.id: "Approval is required before changing stock."}, "translated", "hi-IN"

    monkeypatch.setattr("app.services.meeting_reanalysis_service.translate_segments", translate)
    monkeypatch.setattr("app.services.vexa_sarvam_service.VexaSarvamService._resolve_project", lambda *args: "proj_birch")
    monkeypatch.setattr("app.services.pipeline_coordinator.PipelineCoordinator", lambda: SimpleNamespace(process_meeting_with_context=lambda **kwargs: SimpleNamespace(success=True)))
    result = reanalyze_saved_meeting(meeting.id, db)
    assert result["routed"] == 1
    assert db.query(TranscriptEntry).filter_by(transcript_id=transcript.id).count() == 1
    assert db.query(Evidence).filter_by(meeting_id=meeting.id).count() == 1
    assert db.get(TranscriptEntry, entry.id).text == HINDI
    assert db.get(Evidence, evidence.id).content == HINDI
    assert db.get(Evidence, evidence.id).project_id == "proj_birch"
    assert json.loads(db.get(Evidence, evidence.id).metadata_json)["text_en"] == "Approval is required before changing stock."
    db.refresh(item)
    assert item.status == "assigned"
    monkeypatch.setattr("app.services.meeting_reanalysis_service.translate_segments", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Accepted translations must be reused")))
    reanalyze_saved_meeting(meeting.id, db)
    assert db.get(Evidence, evidence.id).content == HINDI


def test_rerouting_retracts_only_displaced_memory_and_preserves_history(db_session, test_user):
    from app.models.project import Project, Workspace
    from app.models.meeting import Meeting
    from app.models.intelligence import CandidateKnowledge
    from app.models.project_state import ProjectStateVersion, StateChange
    from app.models.memory_engine import MemoryClaimRevision
    from app.services.project_state_service import ProjectStateService
    from app.services.meeting_reanalysis_service import _retract_displaced_claims
    db = db_session
    db.add(Workspace(id="ws_retract", name="Retraction test"))
    db.flush()
    db.add(Project(id="proj_retract", workspace_id="ws_retract", name="Birch"))
    meeting = Meeting(id="mtg_retract", workspace_id="ws_retract", project_id="proj_retract", user_id=test_user.id, provider_conference_id="retract-test")
    db.add(meeting)
    db.flush()
    candidate = CandidateKnowledge(id="cand_wrong_scope", project_id="proj_retract", meeting_id=meeting.id,
        category="assumption", title="Other project's tentative budget", content="Unapproved budget.",
        evidence_ids_json='["ev_displaced"]', status="approved")
    db.add(candidate)
    db.flush()
    state = ProjectStateService().get_or_create_state("proj_retract", db)
    state.assumptions_json = json.dumps([
        {"id": "wrong", "source_candidate_id": candidate.id, "evidence_ids": ["ev_displaced"]},
        {"id": "keep", "title": "Existing reviewed knowledge"},
    ])
    db.add(MemoryClaimRevision(id="claim_wrong_scope", candidate_id=candidate.id, project_id="proj_retract",
        status="approved", snapshot_json='{"title":"Budget"}'))
    db.add(StateChange(project_id="proj_retract", candidate_id=candidate.id, state_version_before=1,
        operation="insert", target_section="assumptions", value_json="{}", reason="test", actor_id="test", approval_status="proposed"))
    db.commit()
    previous = state.current_version
    _retract_displaced_claims(meeting.id, {"proj_retract": {"ev_displaced"}}, db, "repair")
    assert candidate.status == "superseded"
    assert state.current_version == previous + 1
    assert json.loads(state.assumptions_json) == [{"id": "keep", "title": "Existing reviewed knowledge"}]
    assert db.query(ProjectStateVersion).filter_by(project_id="proj_retract", version_number=previous).first()
    assert db.get(MemoryClaimRevision, "claim_wrong_scope").valid_to is not None
    count = db.query(ProjectStateVersion).filter_by(project_id="proj_retract").count()
    _retract_displaced_claims(meeting.id, {"proj_retract": {"ev_displaced"}}, db, "repair")
    assert db.query(ProjectStateVersion).filter_by(project_id="proj_retract").count() == count
