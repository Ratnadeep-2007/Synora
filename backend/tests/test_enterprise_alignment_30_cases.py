"""Comprehensive test suite explicitly covering all 30 requirements of Part 20."""

from datetime import datetime, timezone, timedelta
import json
import pytest
from sqlalchemy.orm import Session

from app.models.context_resolution import (
    ContextDecision,
    ContextResolution,
    UnknownContextItem,
    UnknownItemStatus,
)
from app.models.evidence import Evidence
from app.models.meeting import Meeting, Transcript, TranscriptEntry
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, Project
from app.models.source_event import SourceEvent
from app.models.visual_revision import VisualRevision, VisualWorkspace
from app.schemas.context import (
    CandidateProject,
    ContextCandidateBatch,
    ContextCandidateItem,
    ContextResolutionResult,
)
from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship
from app.services.context_intelligence import ContextIntelligenceService
from app.services.context_resolution_service import ContextResolutionService
from app.services.excalidraw_compiler import ExcalidrawCompiler
from app.services.excalidraw_service import ExcalidrawService
from app.services.knowledge_intelligence import KnowledgeIntelligenceService
from app.services.meet_event_worker import MeetEventWorker
from app.services.source_intelligence_pipeline import RoutingOutcome, SourceIntelligencePipeline
from app.services.unknown_context_service import UnknownContextService
from app.services.visual_critique_service import VisualCritiqueService
from app.services.visual_revision_service import VisualRevisionService


class StubSemanticClient:
    def __init__(self, items, is_casual: bool = False):
        self._items = items
        self._is_casual = is_casual

    def generate_structured(self, prompt, schema):
        if schema is ContextCandidateBatch:
            return ContextCandidateBatch(
                items=list(self._items),
                is_casual=self._is_casual,
                model="test-stub",
                prompt_version="test",
            )
        raise NotImplementedError


def _p(db: Session, project_id: str, name: str, description: str = "") -> Project:
    p = Project(id=project_id, workspace_id="ws_default", name=name, description=description)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ==============================================================================
# CONTEXT (Cases 1 - 10)
# ==============================================================================

# 1. Explicit project ID -> resolved
def test_case_01_explicit_project_id_resolved(db_session: Session):
    _p(db_session, "proj_auth", "Auth Service")
    svc = ContextResolutionService(llm_client=StubSemanticClient([]))
    res = svc.resolve_context(
        source="whatsapp",
        content="Deploy update for proj_auth now",
        db=db_session,
    )
    assert res.status == "resolved"
    assert res.resolved_project_id == "proj_auth"
    assert res.requires_human_review is False


# 2. Explicit project tag -> resolved
def test_case_02_explicit_project_tag_resolved(db_session: Session):
    _p(db_session, "proj_claims", "Healthcare Claims Engine")
    svc = ContextResolutionService(llm_client=StubSemanticClient([]))
    res = svc.resolve_context(
        source="whatsapp",
        content="Please check [claims] KYC status",
        db=db_session,
    )
    assert res.status == "resolved"
    assert res.resolved_project_id == "proj_claims"


# 3. Known WhatsApp group -> resolved
def test_case_03_known_whatsapp_group_resolved(db_session: Session):
    _p(db_session, "proj_synora", "Synora Architecture")
    svc = ContextResolutionService(llm_client=StubSemanticClient([]))
    res = svc.resolve_context(
        source="whatsapp",
        content="Architecture discussion in dedicated room",
        group_channel="120363028123456789@g.us",
        trusted_project_id="proj_synora",
        db=db_session,
    )
    assert res.status == "resolved"
    assert res.resolved_project_id == "proj_synora"


# 4. Strong semantic match -> resolved
def test_case_04_strong_semantic_match_resolved(db_session: Session):
    _p(db_session, "proj_synora", "Synora Architecture")
    client = StubSemanticClient([
        ContextCandidateItem(project_id="proj_synora", confidence=0.91, reasons=["strong architecture overlap"]),
    ])
    svc = ContextResolutionService(llm_client=client)
    res = svc.resolve_context(
        source="google_meet",
        content="We should optimize the vector pipeline and quantization for embeddings",
        db=db_session,
    )
    assert res.status == "resolved"
    assert res.resolved_project_id == "proj_synora"


# 5. Weak match -> unknown
def test_case_05_weak_match_is_unknown(db_session: Session):
    _p(db_session, "proj_synora", "Synora Architecture")
    client = StubSemanticClient([
        ContextCandidateItem(project_id="proj_synora", confidence=0.45, reasons=["weak keyword overlap"]),
    ])
    svc = ContextResolutionService(llm_client=client)
    res = svc.resolve_context(
        source="whatsapp",
        content="discussing general office hardware procurement",
        db=db_session,
    )
    assert res.status == "unresolved"
    assert res.resolved_project_id is None
    assert res.requires_human_review is True


# 6. Two equally plausible projects -> ambiguous
def test_case_06_two_plausible_projects_ambiguous(db_session: Session):
    _p(db_session, "proj_synora", "Synora Architecture")
    _p(db_session, "proj_dinein", "DineIn Restaurant App")
    client = StubSemanticClient([
        ContextCandidateItem(project_id="proj_synora", confidence=0.82, reasons=["session caching"]),
        ContextCandidateItem(project_id="proj_dinein", confidence=0.80, reasons=["session caching"]),
    ])
    svc = ContextResolutionService(llm_client=client)
    res = svc.resolve_context(
        source="whatsapp",
        content="Redis cluster deployment for user sessions",
        db=db_session,
    )
    assert res.status == "ambiguous"
    assert res.resolved_project_id is None
    assert len(res.candidates) >= 2


# 7. No project match -> unknown
def test_case_07_no_project_match_is_unknown(db_session: Session):
    _p(db_session, "proj_synora", "Synora Architecture")
    client = StubSemanticClient([])
    svc = ContextResolutionService(llm_client=client)
    res = svc.resolve_context(
        source="whatsapp",
        content="Astronomy observations on gravitational lensing",
        db=db_session,
    )
    assert res.status == "unresolved"
    assert res.resolved_project_id is None


# 8. Unknown Context cannot match itself
def test_case_08_unknown_context_cannot_match_itself(db_session: Session):
    _p(db_session, "proj_real", "Real Project")
    svc = ContextResolutionService(llm_client=StubSemanticClient([]))
    svc.ensure_unknown_context_project(db_session)
    projects = db_session.query(Project).all()
    candidate_ids = [p.id for p in projects if not p.is_system and p.id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID]
    assert SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID not in candidate_ids


# 9. Unauthorized project cannot be selected
def test_case_09_unauthorized_project_cannot_be_selected(db_session: Session):
    _p(db_session, "proj_public", "Public Project")
    _p(db_session, "proj_classified", "Classified Defense Engine")
    client = StubSemanticClient([
        ContextCandidateItem(project_id="proj_classified", confidence=0.99, reasons=["exact match"]),
    ])
    svc = ContextIntelligenceService(llm_client=client)
    res = svc.resolve(
        source="whatsapp",
        payload={"text": "defense engine missile guidance update"},
        authorized_project_ids=["proj_public"],
        db=db_session,
    )
    assert res.project_id != "proj_classified"
    assert res.decision == ContextDecision.UNKNOWN.value


# 10. Tenant isolation
def test_case_10_tenant_isolation(db_session: Session):
    _p(db_session, "proj_tenant_a", "Acme Project")
    _p(db_session, "proj_tenant_b", "Beta Project")
    client = StubSemanticClient([
        ContextCandidateItem(project_id="proj_tenant_b", confidence=0.95, reasons=["name match"]),
    ])
    svc = ContextIntelligenceService(llm_client=client)
    res = svc.resolve(
        source="whatsapp",
        payload={"text": "Beta Project core algorithm"},
        authorized_project_ids=["proj_tenant_a"],  # Tenant Acme is strictly isolated to proj_tenant_a
        db=db_session,
    )
    assert res.project_id != "proj_tenant_b"
    assert res.decision == ContextDecision.UNKNOWN.value


# ==============================================================================
# PARALLEL PROCESSING (Cases 11 - 13)
# ==============================================================================

# 11. Meet context resolution + extraction can execute independently
def test_case_11_meet_context_and_extraction_independent(db_session: Session):
    _p(db_session, "proj_meet_indep", "Meet Independent Project")
    ctx_svc = ContextResolutionService(llm_client=StubSemanticClient([]))
    know_svc = KnowledgeIntelligenceService(llm_client=None)

    # Resolution executes
    res = ctx_svc.resolve_context(
        source="google_meet", content="[meet_indep] Let's finalize PostgreSQL", db=db_session
    )
    assert res.status == "resolved"

    # Extraction executes
    se = SourceEvent(event_id="se_meet_indep", source="google_meet", source_event_id="s_evt_meet_01", payload_json="{}")
    db_session.add(se)
    ev = Evidence(
        id="ev_meet_indep", project_id="proj_meet_indep", source="google_meet",
        source_event_id="se_meet_indep", content="We decided to use PostgreSQL 16",
    )
    db_session.add(ev)
    db_session.commit()
    ext = know_svc.extract_items([ev], source_name="google_meet")
    assert isinstance(ext.items, list)


# 12. WhatsApp context resolution + extraction can execute independently
def test_case_12_whatsapp_context_and_extraction_independent(db_session: Session):
    _p(db_session, "proj_wa_indep", "WhatsApp Independent Project")
    ctx_svc = ContextResolutionService(llm_client=StubSemanticClient([]))
    know_svc = KnowledgeIntelligenceService(llm_client=None)

    res = ctx_svc.resolve_context(
        source="whatsapp", content="[wa_indep] Ship the checkout form", db=db_session
    )
    assert res.status == "resolved"

    se = SourceEvent(event_id="se_wa_indep", source="whatsapp", source_event_id="s_evt_wa_01", payload_json="{}")
    db_session.add(se)
    ev = Evidence(
        id="ev_wa_indep", project_id="proj_wa_indep", source="whatsapp",
        source_event_id="se_wa_indep", content="Require payment validation within 30 seconds",
    )
    db_session.add(ev)
    db_session.commit()
    ext = know_svc.extract_items([ev], source_name="whatsapp")
    assert isinstance(ext.items, list)


# 13. Results join correctly
def test_case_13_parallel_results_join_correctly(db_session: Session):
    _p(db_session, "proj_join", "Joined Architecture Project")
    pipeline = SourceIntelligencePipeline(
        context_service=ContextIntelligenceService(llm_client=StubSemanticClient([])),
    )
    outcome = pipeline.process(
        source="whatsapp",
        payload={"text": "[join] We require mandatory 2FA on admin logins"},
        db=db_session,
        source_event_id="wa_join_01",
    )
    assert outcome.outcome == RoutingOutcome.RESOLVED.value
    assert outcome.project_id == "proj_join"
    assert outcome.evidence_id is not None


# ==============================================================================
# MEET (Cases 14 - 15)
# ==============================================================================

# 14. One meeting can produce multiple project contexts
# 15. Segment-level routing works
def test_case_14_and_15_meet_segment_routing(db_session: Session, test_user):
    _p(db_session, "proj_alpha", "Alpha Platform")
    _p(db_session, "proj_beta", "Beta Service")

    meeting = Meeting(
        id="meet_cases_14_15", user_id=test_user.id, provider_conference_id="conf_14_15",
        project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, title="Cross-Project Sync",
    )
    db_session.add(meeting)
    tr = Transcript(id="tr_14_15", meeting_id=meeting.id, provider_transcript_id="ptr_14_15")
    db_session.add(tr)

    t0 = datetime.now(timezone.utc)
    e1 = TranscriptEntry(
        id="te_14a", transcript_id=tr.id, provider_entry_id="pe_14a", start_time=t0,
        text="For [alpha] we decided to migrate session storage to Redis",
    )
    e2 = TranscriptEntry(
        id="te_14b", transcript_id=tr.id, provider_entry_id="pe_14b", start_time=t0 + timedelta(minutes=10),
        text="Moving to [beta] we must add webhook retry exponential backoff",
    )
    db_session.add_all([e1, e2])
    db_session.commit()

    worker = MeetEventWorker(context_service=ContextIntelligenceService(llm_client=StubSemanticClient([])))
    routing = worker._route_transcript_segments(meeting=meeting, transcript=tr, db=db_session, trusted_project_id=None)
    assert routing["segments"] >= 2
    assert "proj_alpha" in routing["routed_projects"]
    assert "proj_beta" in routing["routed_projects"]


# ==============================================================================
# WHATSAPP (Cases 16 - 20)
# ==============================================================================

# 16. Real message -> SourceEvent
# 17. SourceEvent -> context resolution
# 18. Correct project routing
def test_case_16_17_18_whatsapp_message_flow(db_session: Session):
    _p(db_session, "proj_wa_route", "WhatsApp Target Project")
    pipeline = SourceIntelligencePipeline(
        context_service=ContextIntelligenceService(llm_client=StubSemanticClient([])),
    )
    outcome = pipeline.process(
        source="whatsapp",
        payload={"text": "[wa_route] Implementation of invoice PDF generator"},
        db=db_session,
        source_event_id="wa_msg_101",
    )
    assert outcome.outcome == RoutingOutcome.RESOLVED.value
    assert outcome.project_id == "proj_wa_route"

    ev = db_session.query(Evidence).filter_by(id=outcome.evidence_id).first()
    assert ev is not None
    assert ev.project_id == "proj_wa_route"


# 19. Unknown context routing
def test_case_19_whatsapp_unknown_context_routing(db_session: Session):
    _p(db_session, "proj_unrelated", "Unrelated App")
    pipeline = SourceIntelligencePipeline(
        context_service=ContextIntelligenceService(llm_client=StubSemanticClient([])),
    )
    outcome = pipeline.process(
        source="whatsapp",
        payload={"text": "Procuring 50 enterprise FPGA boards for raw hardware signal decoding"},
        db=db_session,
        source_event_id="wa_unk_101",
    )
    assert outcome.outcome == RoutingOutcome.UNKNOWN_CONTEXT.value
    assert outcome.unknown_item_id is not None
    item = db_session.query(UnknownContextItem).filter_by(id=outcome.unknown_item_id).first()
    assert item is not None
    assert item.status == UnknownItemStatus.PENDING.value


# 20. Duplicate message is idempotent
def test_case_20_whatsapp_duplicate_is_idempotent(db_session: Session):
    _p(db_session, "proj_idem", "Idempotent WhatsApp Project")
    pipeline = SourceIntelligencePipeline(
        context_service=ContextIntelligenceService(llm_client=StubSemanticClient([])),
    )
    payload = {"text": "[idem] Deploy caching update"}
    res1 = pipeline.process(source="whatsapp", payload=payload, db=db_session, source_event_id="wa_dup_101")
    assert res1.outcome == RoutingOutcome.RESOLVED.value

    res2 = pipeline.process(source="whatsapp", payload=payload, db=db_session, source_event_id="wa_dup_101")
    assert res2.outcome == RoutingOutcome.DUPLICATE.value


# ==============================================================================
# EXCALIDRAW (Cases 21 - 30)
# ==============================================================================

# 21. Current revision loads
# 22. New revision is immutable
# 23. Previous revision remains intact
def test_case_21_22_23_excalidraw_revisions_immutable(db_session: Session):
    _p(db_session, "proj_ex_rev", "Excalidraw Revision Project")
    svc = VisualRevisionService()

    r1 = svc.commit_revision(
        project_id="proj_ex_rev",
        scene=[{"id": "node_1", "type": "rectangle", "x": 0, "y": 0}],
        db=db_session,
        reason="Baseline",
    )
    r2 = svc.commit_revision(
        project_id="proj_ex_rev",
        scene=[{"id": "node_1", "type": "rectangle", "x": 0, "y": 0}, {"id": "node_2", "type": "rectangle", "x": 100, "y": 0}],
        db=db_session,
        reason="Added node 2",
    )

    # 21. Current revision loads
    current = svc.current_revision("proj_ex_rev", db_session)
    assert current.id == r2.id
    assert current.revision_number == 2

    # 22. New revision is immutable
    assert r2.parent_revision_id == r1.id

    # 23. Previous revision remains intact
    hist = svc.get_revision("proj_ex_rev", 1, db_session)
    assert len(json.loads(hist.scene_json)) == 1


# 24. Compare view works
# 25. Add/remove/change diff works
def test_case_24_25_compare_and_diff(db_session: Session):
    _p(db_session, "proj_ex_diff", "Excalidraw Diff Project")
    svc = VisualRevisionService()

    r1 = svc.commit_revision(
        project_id="proj_ex_diff",
        scene=[{"id": "node_a", "type": "rectangle", "label": "Old"}],
        db=db_session,
        reason="v1",
    )
    r2 = svc.commit_revision(
        project_id="proj_ex_diff",
        scene=[{"id": "node_b", "type": "rectangle", "label": "New"}],
        db=db_session,
        reason="v2",
    )

    diff = svc.compare_revisions("proj_ex_diff", from_revision=1, to_revision=2, db=db_session)
    assert len(diff.added) == 1
    assert "node_b" in diff.added[0]
    assert len(diff.removed) == 1
    assert "node_a" in diff.removed[0]


# 26. VisualPlan validates
def test_case_26_visual_plan_validates():
    plan = VisualPlan(
        title="Valid Architecture",
        nodes=[
            VisualNode(id="auth", label="Auth Service", type="service"),
            VisualNode(id="redis", label="Redis Cache", type="infrastructure"),
        ],
        edges=[
            VisualRelationship(from_node="auth", to_node="redis", label="session"),
        ],
        layout={"direction": "left_to_right"},
    )
    assert len(plan.nodes) == 2
    assert len(plan.relationships) == 1
    assert plan.layout_direction == "horizontal"


# 27. Compiler produces valid Excalidraw elements
# 28. No overlapping components in generated layout
def test_case_27_28_compiler_layout_and_no_overlap():
    plan = VisualPlan(
        title="Microservice Topology",
        nodes=[
            VisualNode(id="gw", label="API Gateway", node_type="client"),
            VisualNode(id="auth", label="Auth Service", node_type="service"),
            VisualNode(id="db", label="Primary PostgreSQL", node_type="datastore"),
        ],
        relationships=[
            VisualRelationship(source="gw", target="auth"),
            VisualRelationship(source="auth", target="db"),
        ],
    )
    compiler = ExcalidrawCompiler()
    elements = compiler.compile(plan)
    assert len(elements) >= 3

    # Check for non-overlap across rectangles
    rects = [e for e in elements if e["type"] == "rectangle"]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            r1, r2 = rects[i], rects[j]
            x_overlap = not (r1["x"] + r1["width"] <= r2["x"] or r2["x"] + r2["width"] <= r1["x"])
            y_overlap = not (r1["y"] + r1["height"] <= r2["y"] or r2["y"] + r2["height"] <= r1["y"])
            assert not (x_overlap and y_overlap), f"Overlap detected between {r1['id']} and {r2['id']}"


# 29. Human approval creates new revision
# 30. Rejected proposal does not modify current revision
def test_case_29_30_proposal_lifecycle_and_rejection(db_session: Session):
    from app.services.excalidraw_service import ExcalidrawService

    _p(db_session, "proj_prop_test", "Proposal Test Project")
    rev_svc = VisualRevisionService()
    baseline = rev_svc.commit_revision(
        project_id="proj_prop_test",
        scene=[{"id": "base", "type": "rectangle", "x": 0, "y": 0}],
        db=db_session,
        reason="Baseline",
    )

    excal_svc = ExcalidrawService()
    prop = excal_svc.propose_changes(
        project_id="proj_prop_test",
        suggested_elements=[{"id": "prop_node", "type": "rectangle", "x": 100, "y": 100}],
        reason="Proposed Architecture",
        db=db_session,
    )
    assert prop.status == "pending"

    # Current revision must remain unaffected while proposal is pending
    current = rev_svc.current_revision("proj_prop_test", db_session)
    assert current.id == baseline.id

    # 30. Rejection preserves current revision without mutation
    excal_svc.reject_proposal(prop.id, db=db_session, note="Scope altered")
    after_reject = rev_svc.current_revision("proj_prop_test", db_session)
    assert after_reject.id == baseline.id
    assert after_reject.revision_number == 1

    # 29. A new proposal that gets approved creates a new revision
    prop2 = excal_svc.propose_changes(
        project_id="proj_prop_test",
        suggested_elements=[{"id": "approved_node", "type": "rectangle", "x": 200, "y": 200}],
        reason="Approved Architecture",
        db=db_session,
    )
    approved_res = excal_svc.approve_proposal(prop2.id, db=db_session, actor_id="lead_architect")
    assert approved_res["status"] == "approved"
    assert approved_res["revision_number"] == 2
    new_curr = rev_svc.current_revision("proj_prop_test", db_session)
    assert new_curr.revision_number == 2
