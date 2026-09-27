import json

from app.models.project import Project
from app.services.context_resolver import (
    ContextResolverService,
    UNKNOWN_CONTEXT_ID,
)


def test_unknown_context_is_created_and_candidates_are_returned(db_session):
    resolver = ContextResolverService()
    claims = Project(
        id="proj_ctx_claims",
        workspace_id="ws_default",
        name="Healthcare Claims Engine",
        description="Health insurance claims, KYC, adjudication and fraud detection",
    )
    core = Project(
        id="proj_ctx_core",
        workspace_id="ws_default",
        name="Synora Core Architecture",
        description="Authentication, JWT, Redis, PostgreSQL, FastAPI and Excalidraw",
    )
    db_session.add_all([claims, core])
    db_session.commit()

    result = resolver.resolve(
        text="We need the Redis session cache and JWT gateway in the platform.",
        db=db_session,
        workspace_id="ws_default",
        metadata={"source_name": "whatsapp", "group_name": "engineering"},
    )
    project, routed = resolver.route_or_quarantine(
        result=result,
        db=db_session,
        workspace_id="ws_default",
        tenant_id="default_tenant",
    )

    assert project.id in {core.id, UNKNOWN_CONTEXT_ID}
    if routed.status != "resolved":
        assert project.id == UNKNOWN_CONTEXT_ID
        assert routed.selected_project_id is None
        assert len(routed.candidates) >= 1


def test_unknown_context_assignment_reprocesses_evidence(db_session):
    resolver = ContextResolverService()
    unknown = resolver.ensure_unknown_context_project(db_session)
    target = Project(
        id="proj_ctx_target",
        workspace_id="ws_default",
        name="Synora",
        description="Project intelligence, Excalidraw, PostgreSQL and Redis",
    )
    db_session.add(target)
    db_session.commit()

    from app.models.source_event import SourceEvent
    from app.models.evidence import Evidence

    event = SourceEvent(
        event_id="evt_ctx_unknown_1",
        tenant_id="default_tenant",
        project_id=unknown.id,
        source="whatsapp",
        source_event_id="wa_ctx_unknown_1",
        event_type="group_message",
        actor_id="qa",
        occurred_at=None,
        payload_json=json.dumps({"context_status": "unknown"}),
        status="received",
    )
    db_session.add(event)
    db_session.flush()

    evidence = Evidence(
        project_id=unknown.id,
        source="whatsapp",
        source_event_id=event.event_id,
        meeting_id=None,
        actor_id="qa",
        occurred_at=None,
        content="For Synora, we decided to use Redis for session management.",
        metadata_json=json.dumps({
            "source": "whatsapp",
            "group_jid": "120000@g.us",
            "context_status": "unknown",
        }),
    )
    db_session.add(evidence)
    db_session.commit()

    result = resolver.move_unknown_evidence_to_project(
        evidence_id=evidence.id,
        target_project_id=target.id,
        db=db_session,
        actor_id="usr_admin",
        trigger_reprocessing=True,
    )

    assert result["status"] == "assigned"
    assert result["project_id"] == target.id
    db_session.refresh(evidence)
    assert evidence.project_id == target.id
    metadata = json.loads(evidence.metadata_json)
    assert metadata["context_status"] == "human_assigned"
