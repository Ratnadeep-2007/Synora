"""Tests for the category vocabulary contract and the visual sync loop.

The contract: the extractor may produce short forms, but what is persisted and
what the coordinator and memory service match on must be canonical. A category
that falls through both the proposal branch and the memory targets produces a
candidate that is approved yet memorized nowhere - verified live 2026-10-06.
"""

import json

from app.models.evidence import Evidence
from app.models.project import Project
from app.models.source_event import SourceEvent
from app.services.meeting_intelligence import MeetingIntelligenceService
from app.services.pipeline_coordinator import PipelineCoordinator
from app.services.project_memory_service import ProjectMemoryService
from app.services.visual_sync_service import VisualSyncService


def test_normalize_category_maps_short_forms():
    svc = MeetingIntelligenceService
    assert svc.normalize_category("decision") == "decision_candidate"
    assert svc.normalize_category("requirement") == "requirement_candidate"
    assert svc.normalize_category("decision_candidate") == "decision_candidate"
    assert svc.normalize_category("proposal") == "proposal"
    assert svc.normalize_category("  Decision  ") == "decision_candidate"
    assert svc.normalize_category(None) == ""
    assert svc.normalize_category("action_item") == "action_item"


def test_state_targets_accept_short_forms():
    targets = ProjectMemoryService.STATE_TARGETS
    assert targets["decision"] == "decisions"
    assert targets["requirement"] == "requirements"
    assert targets["decision_candidate"] == "decisions"
    assert targets["requirement_candidate"] == "requirements"


def _seed_project_with_memory(db_session, test_user, project_id, name):
    project = Project(
        id=project_id,
        workspace_id="ws_default",
        name=name,
        description="",
        is_system=False,
    )
    db_session.add(project)
    db_session.commit()

    event = SourceEvent(
        tenant_id="tenant_default",
        project_id=project_id,
        source="google_meet",
        source_event_id=f"evt_{project_id}_1",
        event_type="transcript_entry",
        actor_id="SPEAKER_00",
        payload_json=json.dumps({"text": "We will use face recognition."}),
        status="received",
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        SourceEvent(
            tenant_id="tenant_default",
            project_id=project_id,
            source="google_meet",
            source_event_id=f"evt_{project_id}_2",
            event_type="transcript_entry",
            actor_id="SPEAKER_01",
            payload_json=json.dumps({"text": "Frontend first, backend after."}),
            status="received",
        )
    )
    db_session.flush()
    for idx, (ev_id, text) in enumerate(
        [
            (f"evt_{project_id}_1", "We will use face recognition."),
            (f"evt_{project_id}_2", "Frontend first, backend after."),
        ]
    ):
        ev_row = (
            db_session.query(SourceEvent)
            .filter(SourceEvent.source_event_id == ev_id)
            .first()
        )
        db_session.add(
            Evidence(
                project_id=project_id,
                source="google_meet",
                source_event_id=ev_row.event_id,
                actor_id="SPEAKER_00" if idx == 0 else "SPEAKER_01",
                content=text,
                metadata_json="{}",
            )
        )
    db_session.commit()
    return project


def test_visual_sync_draws_approved_memory(db_session, test_user):
    """Approved memory with no canvas behind it gets drawn, once."""
    from app.models.project_state import StateChange, ChangeOperation, ApprovalStatus
    from app.services.project_state_service import ProjectStateService
    from datetime import datetime, timezone

    project = _seed_project_with_memory(db_session, test_user, "proj_synctest", "SyncTest")
    state = ProjectStateService().get_or_create_state(project.id, db_session)
    state.current_version = 2
    db_session.add(
        StateChange(
            project_id=project.id,
            state_version_before=1,
            state_version_after=2,
            operation=ChangeOperation.INSERT.value,
            target_section="decisions",
            value_json=json.dumps({"title": "Use face recognition"}),
            reason="test",
            actor_id="test",
            evidence_ids_json=json.dumps([]),
            approval_status=ApprovalStatus.APPROVED.value,
            created_at=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    svc = VisualSyncService()
    first = svc.sync_project(project.id, db_session)
    assert first["synced"] is True, first
    assert first["reason"] == "reconciled"

    # Second cycle must be a no-op: memory has not moved since.
    second = svc.sync_project(project.id, db_session)
    assert second["synced"] is False
    assert second["reason"] == "no_change"


def test_visual_sync_has_no_evidence_gate(db_session, test_user):
    """No restrictions: even a project with zero evidence rows gets its
    approved memory drawn. The gate was removed per the operator's standing
    direction that the agent works on the canvas without restrictions."""
    from app.models.project_state import StateChange, ChangeOperation, ApprovalStatus
    from app.services.project_state_service import ProjectStateService
    from datetime import datetime, timezone

    project = Project(id="proj_gate", workspace_id="ws_default", name="Gate", description="", is_system=False)
    db_session.add(project)
    db_session.commit()
    state = ProjectStateService().get_or_create_state(project.id, db_session)
    state.current_version = 2
    db_session.add(
        StateChange(
            project_id=project.id,
            state_version_before=1,
            state_version_after=2,
            operation=ChangeOperation.INSERT.value,
            target_section="decisions",
            value_json=json.dumps({"title": "One thing"}),
            reason="test",
            actor_id="test",
            evidence_ids_json=json.dumps([]),
            approval_status=ApprovalStatus.APPROVED.value,
            created_at=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    out = VisualSyncService().sync_project(project.id, db_session)
    assert out["synced"] is True, out
    assert out["reason"] == "reconciled"
