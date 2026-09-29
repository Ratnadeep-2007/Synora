"""Context Intelligence + Unknown Context tests (spec section 19, cases 1-8)."""

import pytest
from sqlalchemy.orm import Session

from app.models.context_resolution import (
    ContextDecision,
    ContextResolution,
    UnknownContextItem,
    UnknownItemStatus,
)
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, Project
from app.schemas.context import ContextCandidateBatch, ContextCandidateItem
from app.services.context_intelligence import ContextIntelligenceService
from app.services.unknown_context_service import UnknownContextError, UnknownContextService


class FakeSemanticClient:
    """Stub semantic provider returning a fixed candidate batch."""

    def __init__(self, items, is_casual: bool = False):
        self._items = items
        self._is_casual = is_casual
        self.calls = 0

    def generate_structured(self, prompt, schema):
        self.calls += 1
        if schema is ContextCandidateBatch:
            return ContextCandidateBatch(items=list(self._items), is_casual=self._is_casual, model="fake", prompt_version="test")
        raise NotImplementedError


def _project(db: Session, project_id: str, name: str, description: str = "") -> Project:
    p = Project(id=project_id, workspace_id="ws_default", name=name, description=description)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# 1. Explicit project ID -> exact assignment ---------------------------------
def test_explicit_project_id_resolves(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    _project(db_session, "proj_beta", "Beta Platform")
    svc = ContextIntelligenceService(llm_client=FakeSemanticClient([]))

    result = svc.resolve(
        source="whatsapp",
        payload={"text": "Update for proj_beta please ship the invoice change"},
        db=db_session,
    )
    assert result.decision == ContextDecision.RESOLVED.value
    assert result.project_id == "proj_beta"
    assert result.requires_human_review is False


# 2. Explicit project tag -> correct assignment ------------------------------
def test_explicit_project_tag_resolves(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    _project(db_session, "proj_claims", "Healthcare Claims Engine")
    svc = ContextIntelligenceService(llm_client=FakeSemanticClient([]))

    result = svc.resolve(
        source="whatsapp",
        payload={"text": "[claims] we decided to add the KYC component"},
        db=db_session,
    )
    assert result.decision == ContextDecision.RESOLVED.value
    assert result.project_id == "proj_claims"


# 3. Strong semantic match -> resolved candidate ------------------------------
def test_strong_semantic_match_resolves(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    _project(db_session, "proj_beta", "Beta Platform")
    client = FakeSemanticClient([
        ContextCandidateItem(project_id="proj_alpha", confidence=0.93, reasons=["mentions alpha naming"]),
    ])
    svc = ContextIntelligenceService(llm_client=client)

    result = svc.resolve(
        source="google_meet",
        payload={"text": "discussion about the alpha platform rollout"},
        db=db_session,
    )
    assert client.calls == 1
    assert result.decision == ContextDecision.RESOLVED.value
    assert result.project_id == "proj_alpha"
    assert result.requires_human_review is False


# 4. Weak match -> Unknown Context -------------------------------------------
def test_weak_semantic_match_is_unknown(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    client = FakeSemanticClient([
        ContextCandidateItem(project_id="proj_alpha", confidence=0.30, reasons=["vague"]),
    ])
    svc = ContextIntelligenceService(llm_client=client)

    result = svc.resolve(
        source="whatsapp",
        payload={"text": "unrelated chatter about lunch"},
        db=db_session,
    )
    assert result.decision == ContextDecision.UNKNOWN.value
    assert result.project_id is None
    assert result.requires_human_review is True


# 5. Two similar projects -> ambiguous ---------------------------------------
def test_two_similar_projects_ambiguous(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    _project(db_session, "proj_beta", "Beta Platform")
    client = FakeSemanticClient([
        ContextCandidateItem(project_id="proj_alpha", confidence=0.90, reasons=["term x"]),
        ContextCandidateItem(project_id="proj_beta", confidence=0.88, reasons=["term x"]),
    ])
    svc = ContextIntelligenceService(llm_client=client)

    result = svc.resolve(
        source="whatsapp",
        payload={"text": "shared terminology between two initiatives"},
        db=db_session,
    )
    assert result.decision == ContextDecision.AMBIGUOUS.value
    assert result.project_id is None
    assert result.requires_human_review is True
    assert len(result.candidate_projects) == 2


def test_sub_threshold_match_is_unknown(db_session: Session):
    """A match with 0.65 confidence (sub-threshold under 0.72) is strictly UNKNOWN."""
    _project(db_session, "proj_alpha", "Alpha Platform")
    client = FakeSemanticClient([
        ContextCandidateItem(project_id="proj_alpha", confidence=0.65, reasons=["moderate confidence"]),
    ])
    svc = ContextIntelligenceService(llm_client=client)

    result = svc.resolve(
        source="whatsapp",
        payload={"text": "moderate relevance content"},
        db=db_session,
    )
    assert result.decision == ContextDecision.UNKNOWN.value
    assert result.project_id is None
    assert result.requires_human_review is True


def test_casual_chat_semantic_ignored(db_session: Session):
    """Casual chit-chat detected by semantic model is classified as CASUAL_IGNORED."""
    _project(db_session, "proj_alpha", "Alpha Platform")
    client = FakeSemanticClient([], is_casual=True)
    svc = ContextIntelligenceService(llm_client=client)

    result = svc.resolve(
        source="whatsapp",
        payload={"text": "what are your plans for this weekend guys?"},
        db=db_session,
    )
    assert result.decision == ContextDecision.CASUAL_IGNORED.value
    assert result.is_casual is True
    assert result.project_id is None
    assert result.requires_human_review is False



# 6. Unknown project -> Unknown Context --------------------------------------
def test_unknown_content_yields_unknown(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    svc = ContextIntelligenceService(llm_client=FakeSemanticClient([]))

    result = svc.resolve(
        source="excalidraw",
        payload={"text": "sketch of an unrelated system"},
        db=db_session,
    )
    assert result.decision == ContextDecision.UNKNOWN.value


def test_semantic_unavailable_never_fabricates(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    svc = ContextIntelligenceService(llm_client=FakeSemanticClient([]))

    result = svc.resolve(
        source="whatsapp",
        payload={"text": "some ambiguous project talk"},
        db=db_session,
    )
    unavailable = [s for s in result.signals if s.name == "ai_unavailable"]
    assert result.decision == ContextDecision.UNKNOWN.value
    # No fabricated candidate confidence when the semantic provider is unavailable.
    assert result.candidate_projects == []
    assert unavailable or result.project_id is None


# 8. Unknown Context never participates as a candidate ------------------------
def test_unknown_context_project_excluded(db_session: Session):
    svc = ContextIntelligenceService(llm_client=FakeSemanticClient([]))
    svc.ensure_unknown_context_project(db_session)
    _project(db_session, "proj_alpha", "Alpha Platform")

    authorized = svc._authorized_projects(db_session, "default_tenant")
    ids = {p.id for p in authorized}
    assert SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID not in ids

    # Even if the model suggests it, it must be rejected as a candidate.
    client = FakeSemanticClient([
        ContextCandidateItem(project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, confidence=0.99, reasons=["x"]),
    ])
    svc2 = ContextIntelligenceService(llm_client=client)
    result = svc2.resolve(
        source="whatsapp",
        payload={"text": "anything"},
        db=db_session,
    )
    assert result.project_id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    assert all(c.project_id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID for c in result.candidate_projects)


# 7. Unauthorized project -> assignment rejected -----------------------------
def test_unauthorized_assignment_rejected(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    _project(db_session, "proj_secret", "Secret Project")
    ctx = ContextIntelligenceService(llm_client=FakeSemanticClient([]))
    unk = UnknownContextService(context_service=ctx)

    item = unk.create_item(
        source="whatsapp",
        payload={"text": "orphan message"},
        db=db_session,
        source_event_id="evt_orphan_1",
    )
    with pytest.raises(UnknownContextError):
        unk.assign_to_project(
            item.id,
            "proj_secret",
            db=db_session,
            actor_id="usr_test",
            authorized_project_ids=["proj_alpha"],
        )


# Resolutions are audited -----------------------------------------------------
def test_resolution_is_recorded(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    svc = ContextIntelligenceService(llm_client=FakeSemanticClient([]))
    svc.resolve(source="whatsapp", payload={"text": "proj_alpha update"}, db=db_session)
    rows = db_session.query(ContextResolution).all()
    assert len(rows) >= 1
    assert rows[-1].decision in (ContextDecision.RESOLVED.value, ContextDecision.UNKNOWN.value)


# Unknown Context item lifecycle ---------------------------------------------
def test_unknown_item_lifecycle_assign(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    unk = UnknownContextService(context_service=ContextIntelligenceService(llm_client=FakeSemanticClient([])))

    item = unk.create_item(
        source="whatsapp",
        payload={"text": "orphan message about alpha"},
        db=db_session,
        source_event_id="evt_orphan_2",
    )
    assert item.status == UnknownItemStatus.PENDING.value
    assert item.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID

    # idempotent create
    again = unk.create_item(
        source="whatsapp",
        payload={"text": "orphan message about alpha"},
        db=db_session,
        source_event_id="evt_orphan_2",
    )
    assert again.id == item.id

    assigned = unk.assign_to_project(item.id, "proj_alpha", db=db_session, actor_id="usr_test")
    assert assigned.status == UnknownItemStatus.ASSIGNED.value
    assert assigned.assigned_project_id == "proj_alpha"


# 8. WhatsApp and Meet use the same ContextIntelligenceService ----------------
def test_whatsapp_and_meet_share_same_context_service(db_session: Session):
    from app.services.meet_event_worker import MeetEventWorker
    from app.services.whatsapp_service import WhatsAppIntelligenceService
    from app.services.source_intelligence_pipeline import SourceIntelligencePipeline

    wa = WhatsAppIntelligenceService()
    worker = MeetEventWorker()
    pipeline = SourceIntelligencePipeline()

    assert isinstance(wa.pipeline.context_service, ContextIntelligenceService)
    assert isinstance(worker.context_service, ContextIntelligenceService)
    assert isinstance(pipeline.context_service, ContextIntelligenceService)


# 9. One Meet can contain segments assigned to different projects -------------
def test_single_meet_multi_project_segments(db_session: Session, test_user):
    from app.models.meeting import Meeting, Transcript, TranscriptEntry
    from app.services.meet_event_worker import MeetEventWorker

    _project(db_session, "proj_synora", "Synora Architecture")
    _project(db_session, "proj_claims", "Healthcare Claims Engine")

    meeting = Meeting(
        id="meet_multi_turn",
        user_id=test_user.id,
        provider_conference_id="conf_multi_turn",
        project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        title="Strategy Sync",
    )
    db_session.add(meeting)
    transcript = Transcript(
        id="tr_multi_turn",
        meeting_id=meeting.id,
        provider_transcript_id="ptr_multi_turn",
    )
    db_session.add(transcript)

    from datetime import datetime, timezone, timedelta
    t0 = datetime.now(timezone.utc)
    e1 = TranscriptEntry(
        id="te_1", transcript_id=transcript.id, provider_entry_id="pe_1",
        start_time=t0,
        text="For [synora] we must implement Redis caching and vector features"
    )
    e2 = TranscriptEntry(
        id="te_2", transcript_id=transcript.id, provider_entry_id="pe_2",
        start_time=t0 + timedelta(minutes=10),
        text="For [claims] we need Digilocker KYC API claimant identity verification"
    )
    e3 = TranscriptEntry(
        id="te_3", transcript_id=transcript.id, provider_entry_id="pe_3",
        start_time=t0 + timedelta(minutes=20),
        text="Does anyone want pizza for lunch today after the call?"
    )
    db_session.add_all([e1, e2, e3])
    db_session.commit()

    worker = MeetEventWorker(context_service=ContextIntelligenceService(llm_client=FakeSemanticClient([])))
    result = worker._route_transcript_segments(
        meeting=meeting, transcript=transcript, trusted_project_id=None, db=db_session
    )
    assert result["segments"] >= 2
    # Check that events were created across distinct target projects
    from app.models.evidence import Evidence
    ev_synora = db_session.query(Evidence).filter(Evidence.project_id == "proj_synora").first()
    ev_claims = db_session.query(Evidence).filter(Evidence.project_id == "proj_claims").first()
    assert ev_synora is not None
    assert ev_claims is not None


# 10. Excalidraw visual evidence participates in context resolution ------------
def test_excalidraw_visual_evidence_resolution(db_session: Session):
    from app.schemas.excalidraw import ExcalidrawIngestRequest
    from app.services.excalidraw_service import ExcalidrawService

    _project(db_session, "proj_alpha", "Alpha Platform")
    client = FakeSemanticClient([
        ContextCandidateItem(project_id="proj_alpha", confidence=0.92, reasons=["diagram visual elements match Alpha"]),
    ])
    ctx = ContextIntelligenceService(llm_client=client)
    from app.services.source_intelligence_pipeline import SourceIntelligencePipeline
    pipeline = SourceIntelligencePipeline(context_service=ctx)
    excal_svc = ExcalidrawService()
    excal_svc.pipeline = pipeline

    req = ExcalidrawIngestRequest(
        name="Architecture Diagram",
        elements=[
            {"id": "el_1", "type": "text", "text": "Alpha Gateway"},
            {"id": "el_2", "type": "text", "text": "Alpha Microservice"},
        ],
        app_state={},
    )
    res = excal_svc.ingest_unassociated_diagram(req, db=db_session)
    assert res["status"] == "resolved"
    assert res["project_id"] == "proj_alpha"
    assert res["proposal_id"] is not None


# 11. Unauthorized project candidate -> deterministic rejection ----------------
def test_unauthorized_project_candidate_rejected(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")
    _project(db_session, "proj_secret", "Secret Platform")

    client = FakeSemanticClient([
        ContextCandidateItem(project_id="proj_secret", confidence=0.95, reasons=["high semantic similarity"]),
    ])
    ctx = ContextIntelligenceService(llm_client=client)

    result = ctx.resolve(
        source="whatsapp",
        payload={"text": "discussing secret features"},
        db=db_session,
        authorized_project_ids=["proj_alpha"],  # caller is NOT authorized for proj_secret
    )
    # The deterministic authorization gate must reject proj_secret
    assert result.decision == ContextDecision.UNKNOWN.value
    assert result.project_id is None
    assert all(c.project_id != "proj_secret" for c in result.candidate_projects)


# 12. Duplicate SourceEvent -> idempotent processing --------------------------
def test_duplicate_source_event_idempotency(db_session: Session):
    from app.services.source_intelligence_pipeline import SourceIntelligencePipeline, RoutingOutcome

    _project(db_session, "proj_alpha", "Alpha Platform")
    pipeline = SourceIntelligencePipeline(context_service=ContextIntelligenceService(llm_client=FakeSemanticClient([])))

    payload = {"text": "[alpha] ship the new button update"}
    res1 = pipeline.process(source="whatsapp", payload=payload, db=db_session, source_event_id="evt_idem_101")
    assert res1.outcome == RoutingOutcome.RESOLVED.value

    # Second call with the same source_event_id
    res2 = pipeline.process(source="whatsapp", payload=payload, db=db_session, source_event_id="evt_idem_101")
    assert res2.outcome == RoutingOutcome.DUPLICATE.value
    assert res2.project_id == "proj_alpha"


# 14. AI output with invalid project ID -> deterministic rejection ------------
def test_ai_output_invalid_project_id_rejected(db_session: Session):
    _project(db_session, "proj_alpha", "Alpha Platform")

    # Semantic AI hallucinates a non-existent project ID
    client = FakeSemanticClient([
        ContextCandidateItem(project_id="proj_ghost_404", confidence=0.99, reasons=["hallucinated"]),
    ])
    ctx = ContextIntelligenceService(llm_client=client)

    result = ctx.resolve(source="whatsapp", payload={"text": "random text"}, db=db_session)
    assert result.decision == ContextDecision.UNKNOWN.value
    assert result.project_id is None
    assert all(c.project_id != "proj_ghost_404" for c in result.candidate_projects)


# 15. AI confidence cannot bypass authorization -------------------------------
def test_ai_confidence_cannot_bypass_authorization(db_session: Session):
    _project(db_session, "proj_allowed", "Allowed Project")
    _project(db_session, "proj_restricted", "Restricted Project")

    # AI gives perfect 1.0 confidence to the restricted project
    client = FakeSemanticClient([
        ContextCandidateItem(project_id="proj_restricted", confidence=1.0, reasons=["perfect score"]),
    ])
    ctx = ContextIntelligenceService(llm_client=client)

    result = ctx.resolve(
        source="whatsapp",
        payload={"text": "classified text"},
        db=db_session,
        authorized_project_ids=["proj_allowed"],  # restricted project is NOT authorized
    )
    assert result.project_id != "proj_restricted"
    assert result.decision == ContextDecision.UNKNOWN.value

