"""GAP 1: meeting evidence that stays in Unknown Context must be filed as
UnknownContextItem rows, or it never reaches the Context Inbox, the Unknown
board, or the Atlas Unknown column (all of which read inbox items only).
"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.context_resolution import UnknownContextItem, UnknownItemStatus
from app.models.evidence import Evidence
from app.models.excalidraw import ExcalidrawArtifact
from app.models.meeting import Meeting
from app.models.project import Project, SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.services.pipeline_coordinator import PipelineCoordinator


def _evidence(evidence_id: str, project_id: str, content: str, meeting_id: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        project_id=project_id,
        source="google_meet",
        source_event_id=f"sev_{evidence_id}",
        meeting_id=meeting_id,
        actor_id="SPEAKER_00",
        occurred_at=datetime.now(timezone.utc),
        content=content,
    )


def test_unresolved_meeting_evidence_is_filed_to_unknown_inbox(db_session: Session):
    project = Project(id="proj_filing_target", name="Filing Target", workspace_id="ws_default", is_system=False)
    meeting = Meeting(
        id="mtg_filing_1",
        user_id="usr_filing",
        project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        provider="google",
        provider_conference_id="conf_filing_1",
        title="Filing meeting",
        start_time=datetime.now(timezone.utc),
    )
    db_session.add_all([project, meeting])
    db_session.add_all([
        _evidence("ev_filing_unknown_1", SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, "SolarRickshaw fleet dashboard discussion.", meeting.id),
        _evidence("ev_filing_unknown_2", SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, "PaaniMeter sensor alert discussion.", meeting.id),
        _evidence("ev_filing_resolved", project.id, "Filing Target release checklist discussion.", meeting.id),
    ])
    db_session.commit()

    result = PipelineCoordinator().process_meeting_with_context(
        meeting_id=meeting.id,
        project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        db=db_session,
        actor_id="test",
        tenant_id="default_tenant",
    )
    assert result.success is True

    items = db_session.query(UnknownContextItem).filter(UnknownContextItem.meeting_id == meeting.id).all()
    assert {item.evidence_id for item in items} == {"ev_filing_unknown_1", "ev_filing_unknown_2"}
    assert all(item.status == UnknownItemStatus.PENDING.value for item in items)
    assert all(item.meeting_id == meeting.id for item in items)

    # The Unknown board (free notes) now shows the filed meeting content.
    artifact = db_session.query(ExcalidrawArtifact).filter(
        ExcalidrawArtifact.project_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    ).first()
    assert artifact is not None
    texts = " ".join(el.get("text", "") for el in json.loads(artifact.elements_json))
    assert "SolarRickshaw" in texts and "PaaniMeter" in texts

    # Re-running the pipeline must not duplicate inbox items.
    PipelineCoordinator().process_meeting_with_context(
        meeting_id=meeting.id,
        project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        db=db_session,
        actor_id="test",
        tenant_id="default_tenant",
    )
    assert db_session.query(UnknownContextItem).filter(UnknownContextItem.meeting_id == meeting.id).count() == 2
