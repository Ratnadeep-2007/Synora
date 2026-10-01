"""End-to-end source intelligence tests (spec section 19, cases 26-30)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.context_resolution import UnknownContextItem, UnknownItemStatus
from app.models.evidence import Evidence
from app.models.meeting import Meeting, Participant, Transcript, TranscriptEntry
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, Project
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.source_event import SourceEvent
from app.services.context_intelligence import ContextIntelligenceService
from app.services.encryption_service import EncryptionService
from app.services.knowledge_intelligence import AiStatus, KnowledgeIntelligenceService
from app.services.meet_event_worker import MeetEventWorker
from app.services.project_agent_service import ProjectAgentService
from app.services.source_intelligence_pipeline import SourceIntelligencePipeline

TENANT = "default_tenant"


def _project(db: Session, project_id: str, name: str) -> Project:
    return ProjectAgentService().get_or_create_project(
        project_id=project_id, db=db, workspace_id="ws_default", name=name
    )


# 26. WhatsApp -> Unknown Context -> human assign -> project evidence ----------
def test_unknown_context_to_assignment_flow(db_session: Session):
    _project(db_session, "proj_assign_flow", "Assign Flow Project")
    pipeline = SourceIntelligencePipeline()

    outcome = pipeline.process(
        source="whatsapp",
        payload={"text": "We need to procure 50 specialized FPGA accelerator boards for physical layer encoding"},
        db=db_session,
        tenant_id=TENANT,
        actor_id="Tester",
        source_event_id="wa_e2e_1",
    )
    assert outcome.outcome == "unknown_context"
    assert outcome.unknown_item_id

    from app.services.unknown_context_service import UnknownContextService

    unk = UnknownContextService()
    item = db_session.query(UnknownContextItem).filter_by(id=outcome.unknown_item_id).first()
    evidence = db_session.query(Evidence).filter_by(id=outcome.evidence_id).first()
    assert evidence.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID

    # Human assigns it (simulate a suggestion being present)
    ctx = ContextIntelligenceService()
    from app.schemas.context import CandidateProject, ContextResolutionResult
    with patch.object(
        unk, "suggest_matches", return_value=[]
    ):
        pass
    unk.assign_to_project(item.id, "proj_assign_flow", db=db_session, actor_id="Reviewer")

    db_session.refresh(item)
    db_session.refresh(evidence)
    assert item.status == UnknownItemStatus.ASSIGNED.value
    assert item.assigned_project_id == "proj_assign_flow"
    # Evidence re-homed with provenance preserved
    assert evidence.project_id == "proj_assign_flow"
    assert item.source_event_id == "wa_e2e_1"


def test_resolved_source_auto_syncs_shared_project_memory(db_session: Session):
    """Resolved WhatsApp evidence is promoted into ProjectState automatically."""
    _project(db_session, "proj_memory_auto", "Memory Auto Project")

    pipeline = SourceIntelligencePipeline()
    outcome = pipeline.process(
        source="whatsapp",
        payload={"text": "We decided to use Redis for session storage."},
        db=db_session,
        tenant_id=TENANT,
        actor_id="Tester",
        project_id="proj_memory_auto",
        source_event_id="wa_memory_auto_1",
    )

    assert outcome.outcome == "resolved"
    assert outcome.candidates_created >= 1

    from app.models.project_state import StateChange
    state = db_session.query(ProjectState).filter(
        ProjectState.project_id == "proj_memory_auto"
    ).first()
    assert state is not None
    decisions = __import__("json").loads(state.decisions_json)
    assert any("Redis" in str(item) for item in decisions)
    assert state.current_version >= 2

    audit = db_session.query(StateChange).filter(
        StateChange.project_id == "proj_memory_auto",
        StateChange.target_section == "memory",
        StateChange.approval_status == "approved",
    ).first()
    assert audit is not None


# 27. Meet -> project A + project B (segment routing), meeting stays one row ---
def _connection(db: Session, encryption: EncryptionService, user_id: str) -> SourceConnection:
    conn = SourceConnection(
        user_id=user_id,
        provider="google",
        provider_account_id="sub_e2e",
        provider_account_email="e2e@test.internal",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption.encrypt_dict({"access_token": "tok", "refresh_token": "ref"}),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def test_meeting_segments_route_to_multiple_projects(
    db_session: Session, test_user, encryption_service: EncryptionService
):
    _project(db_session, "proj_seg_a", "Segment Project Alpha")
    _project(db_session, "proj_seg_b", "Segment Project Beta")
    _connection(db_session, encryption_service, test_user.id)

    from app.models.meet_event_record import MeetEventRecord

    rec = MeetEventRecord(
        provider_event_id="evt_e2e_multi",
        event_type="google.workspace.meet.transcript.v2.fileGenerated",
        conference_record_id="conferenceRecords/conf_e2e_multi",
        transcript_resource="conferenceRecords/conf_e2e_multi/transcripts/t1",
        status="received",
        attempts="0",
        user_id=test_user.id,
    )
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)

    now = datetime.now(timezone.utc)
    # Two segments separated by a large time gap; each names a different project.
    entries = [
        {
            "name": "conferenceRecords/conf_e2e_multi/transcripts/t1/entries/a1",
            "text": "For proj_seg_a we decided to ship the invoice module.",
            "startTime": now.isoformat(),
        },
        {
            "name": "conferenceRecords/conf_e2e_multi/transcripts/t1/entries/b1",
            "text": "Now for proj_seg_b we agreed to use Redis for sessions.",
            "startTime": (now + timedelta(minutes=30)).isoformat(),
        },
    ]

    worker = MeetEventWorker()

    async def fake_get_transcript(**kwargs):
        return {"name": kwargs["transcript_name"], "state": "AVAILABLE"}

    with patch.object(worker.meet_service, "get_transcript", new=AsyncMock(side_effect=fake_get_transcript)), \
        patch.object(worker.meet_service, "get_conference_record", new_callable=AsyncMock) as conf_mock, \
        patch.object(worker.meet_service, "fetch_all_participants", new_callable=AsyncMock) as part_mock, \
        patch.object(worker.meet_service, "fetch_all_transcript_entries", new_callable=AsyncMock) as entries_mock:
        conf_mock.return_value = {}
        part_mock.return_value = []
        entries_mock.return_value = entries
        result = worker.process_event_record(event_record_id=rec.id, db=db_session)

    routed = result["routing"]["routed_projects"]
    assert "proj_seg_a" in routed
    assert "proj_seg_b" in routed

    # The meeting remains ONE row.
    meetings = (
        db_session.query(Meeting)
        .filter(Meeting.provider_conference_id == "conferenceRecords/conf_e2e_multi")
        .all()
    )
    assert len(meetings) == 1

    # Evidence landed under both projects.
    ev_a = db_session.query(Evidence).filter(Evidence.project_id == "proj_seg_a").all()
    ev_b = db_session.query(Evidence).filter(Evidence.project_id == "proj_seg_b").all()
    assert ev_a and ev_b


# 29. AI unavailable -> no fabricated result ----------------------------------
def test_ai_unavailable_never_fabricates(db_session: Session, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "nvidia")
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "", raising=False)
    monkeypatch.setattr(type(settings), "is_nvidia_nim_configured", property(lambda self: False))
    monkeypatch.setattr(type(settings), "is_groq_configured", property(lambda self: False))

    # A resolvable project must exist, otherwise the resolver correctly
    # short-circuits before ever reaching the semantic branch.
    _project(db_session, "proj_x", "Project X")

    evidence = Evidence(
        id="ev_ai_unavail",
        project_id="proj_x",
        source="whatsapp",
        source_event_id="evt_x",
        content="we decided to use Redis",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(evidence)
    db_session.commit()

    service = KnowledgeIntelligenceService()
    extraction = service.extract_items([evidence], source_name="whatsapp")
    assert extraction.ai_status == AiStatus.UNAVAILABLE.value
    assert extraction.items == []

    # Context Intelligence likewise returns no semantic candidates.
    ctx = ContextIntelligenceService()
    result = ctx.resolve(
        source="whatsapp",
        payload={"text": "we decided to use Redis"},
        db=db_session,
    )
    assert result.decision == "unknown"
    assert all(c.project_id != "proj_x" for c in result.candidate_projects) or result.candidate_projects == []
    assert any(s.name == "ai_unavailable" for s in result.signals)


# 30. Redelivery -> no duplicate state mutation -------------------------------
def test_pipeline_redelivery_is_idempotent(db_session: Session):
    _project(db_session, "proj_idem_e2e", "Idempotency Project")
    pipeline = SourceIntelligencePipeline()

    first = pipeline.process(
        source="whatsapp",
        payload={"text": "For proj_idem_e2e: we decided to add caching."},
        db=db_session,
        tenant_id=TENANT,
        actor_id="Tester",
        source_event_id="wa_idem_1",
    )
    assert first.outcome == "resolved"

    evidence_before = db_session.query(Evidence).count()
    events_before = db_session.query(SourceEvent).count()

    second = pipeline.process(
        source="whatsapp",
        payload={"text": "For proj_idem_e2e: we decided to add caching."},
        db=db_session,
        tenant_id=TENANT,
        actor_id="Tester",
        source_event_id="wa_idem_1",
    )
    assert second.outcome == "duplicate"
    assert db_session.query(Evidence).count() == evidence_before
    assert db_session.query(SourceEvent).count() == events_before
