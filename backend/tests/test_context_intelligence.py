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

    def __init__(self, items):
        self._items = items
        self.calls = 0

    def generate_structured(self, prompt, schema):
        self.calls += 1
        if schema is ContextCandidateBatch:
            return ContextCandidateBatch(items=list(self._items), model="fake", prompt_version="test")
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
        ContextCandidateItem(project_id="proj_alpha", confidence=0.80, reasons=["term x"]),
        ContextCandidateItem(project_id="proj_beta", confidence=0.78, reasons=["term x"]),
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
