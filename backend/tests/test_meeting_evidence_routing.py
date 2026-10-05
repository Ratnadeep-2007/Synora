"""
Multi-project meeting routing.

A meeting can discuss more than one project, but Evidence.project_id is
non-nullable, so routing has to happen per row. The resolver is only allowed to
move a row when one candidate clearly wins; anything ambiguous must be left
alone. Filing a requirement under the wrong project is worse than leaving it for
review, which is what these tests pin down.
"""

import pytest
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.meeting import Meeting
from app.models.project import Project
from app.services.meeting_evidence_router import MeetingEvidenceRouter


class _Result:
    def __init__(self, project_id=None, decision="ambiguous", confidence=0.0, reason=""):
        self.project_id = project_id
        self.decision = decision
        self.confidence = confidence
        self.reason = reason


class _StubResolver:
    """Returns a scripted decision per evidence text."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def resolve_context(self, content=None, **kwargs):
        self.calls.append(content)
        return self.mapping.get(content, _Result())


@pytest.fixture
def meeting(db_session: Session):
    from app.models.source_event import SourceEvent

    for pid, name in (("proj_route_a", "Payments"), ("proj_route_b", "MediClaim")):
        db_session.add(Project(id=pid, workspace_id="ws_default", name=name))
    m = Meeting(
        id="mtg_route_test",
        project_id="proj_route_a",
        user_id="usr_route",
        provider="manual_transcript",
        provider_conference_id="conf_route",
        title="Mixed projects",
    )
    db_session.add(m)
    # Evidence.source_event_id is a NOT NULL foreign key.
    db_session.add(
        SourceEvent(
            event_id="sev_route_test",
            project_id="proj_route_a",
            source="test",
            source_event_id="route-test-1",
            event_type="meeting_transcript",
            payload_json="{}",
        )
    )
    db_session.commit()

    rows = [
        ("ev_route_1", "We decided to settle UPI refunds through the Razorpay gateway"),
        ("ev_route_2", "Every claim denial must return a specific reason code"),
        ("ev_route_3", "Agreed."),
    ]
    for eid, text in rows:
        db_session.add(
            Evidence(
                id=eid,
                project_id="proj_route_a",
                source="test",
                source_event_id="sev_route_test",
                content=text,
                meeting_id="mtg_route_test",
            )
        )
    db_session.commit()
    return m


def _router(db_session, mapping):
    return MeetingEvidenceRouter(resolver=_StubResolver(mapping))


def test_routes_matching_rows_to_their_own_project(db_session: Session, meeting):
    r = _router(
        db_session,
        {
            "We decided to settle UPI refunds through the Razorpay gateway": _Result(
                "proj_route_a", "resolved", 0.91, "clear payments match"
            ),
            "Every claim denial must return a specific reason code": _Result(
                "proj_route_b", "resolved", 0.88, "clear claims match"
            ),
        },
    ).route_meeting_evidence(
        meeting_id="mtg_route_test",
        candidate_project_ids=["proj_route_a", "proj_route_b"],
        db=db_session,
        dry_run=True,
    )

    assert r["total"] == 3
    assert r["routed"] == 1  # only the claims row actually moved
    by_id = {a["evidence_id"]: a for a in r["assignments"]}
    assert by_id["ev_route_1"]["to_project_id"] == "proj_route_a"
    assert by_id["ev_route_1"]["changed"] is False
    assert by_id["ev_route_2"]["to_project_id"] == "proj_route_b"
    assert by_id["ev_route_2"]["changed"] is True


def test_ambiguous_row_is_left_alone_not_guessed(db_session: Session, meeting):
    """The core safety property: no decision means no move."""
    r = _router(db_session, {}).route_meeting_evidence(
        meeting_id="mtg_route_test",
        candidate_project_ids=["proj_route_a", "proj_route_b"],
        db=db_session,
        dry_run=True,
    )
    assert r["routed"] == 0
    assert r["unresolved"] == 3
    for a in r["assignments"]:
        assert a["to_project_id"] is None
        assert a["changed"] is False


def test_dry_run_does_not_write(db_session: Session, meeting):
    _router(
        db_session,
        {
            "Every claim denial must return a specific reason code": _Result(
                "proj_route_b", "resolved", 0.95, "strong"
            )
        },
    ).route_meeting_evidence(
        meeting_id="mtg_route_test",
        candidate_project_ids=["proj_route_a", "proj_route_b"],
        db=db_session,
        dry_run=True,
    )
    row = db_session.query(Evidence).filter(Evidence.id == "ev_route_2").first()
    assert row.project_id == "proj_route_a", "dry_run must not persist"


def test_apply_moves_the_row_and_persists(db_session: Session, meeting):
    _router(
        db_session,
        {
            "Every claim denial must return a specific reason code": _Result(
                "proj_route_b", "resolved", 0.95, "strong"
            )
        },
    ).route_meeting_evidence(
        meeting_id="mtg_route_test",
        candidate_project_ids=["proj_route_a", "proj_route_b"],
        db=db_session,
    )
    db_session.expire_all()
    row = db_session.query(Evidence).filter(Evidence.id == "ev_route_2").first()
    assert row.project_id == "proj_route_b"
    # Rows that were not routed must be untouched.
    other = db_session.query(Evidence).filter(Evidence.id == "ev_route_1").first()
    assert other.project_id == "proj_route_a"


def test_out_of_scope_proposal_is_refused(db_session: Session, meeting):
    """The resolver considers the whole workspace, not just the candidates.

    Found in a live dry run: evidence was proposed for proj_0c0c3169 when the
    caller had scoped the meeting to two other projects. Honouring that would
    file notes under a project nobody nominated, so out-of-scope proposals are
    treated as unresolved.
    """
    r = _router(
        db_session,
        {
            "We decided to settle UPI refunds through the Razorpay gateway": _Result(
                "proj_somewhere_else", "resolved", 0.99, "strong but out of scope"
            )
        },
    ).route_meeting_evidence(
        meeting_id="mtg_route_test",
        candidate_project_ids=["proj_route_a", "proj_route_b"],
        db=db_session,
        dry_run=True,
    )
    by_id = {a["evidence_id"]: a for a in r["assignments"]}
    moved = by_id["ev_route_1"]
    assert moved["to_project_id"] is None
    assert moved["changed"] is False
    assert "out_of_scope" in str(moved["decision"])
    assert "proj_somewhere_else" in moved["reason"]
    assert r["routed"] == 0


def test_unknown_candidate_project_is_rejected(db_session: Session, meeting):
    r = _router(db_session, {})
    with pytest.raises(ValueError) as exc:
        r.route_meeting_evidence(
            meeting_id="mtg_route_test",
            candidate_project_ids=["proj_route_a", "proj_does_not_exist"],
            db=db_session,
            dry_run=True,
        )
    assert "proj_does_not_exist" in str(exc.value)


def test_empty_candidate_list_is_rejected(db_session: Session, meeting):
    with pytest.raises(ValueError):
        _router(db_session, {}).route_meeting_evidence(
            meeting_id="mtg_route_test",
            candidate_project_ids=[],
            db=db_session,
            dry_run=True,
        )


def test_resolver_failure_does_not_abort_the_batch(db_session: Session, meeting):
    class _Flaky:
        def resolve_context(self, content=None, **kwargs):
            if "denial" in (content or ""):
                raise RuntimeError("llm timeout")
            return _Result("proj_route_a", "resolved", 0.9, "ok")

    r = MeetingEvidenceRouter(resolver=_Flaky()).route_meeting_evidence(
        meeting_id="mtg_route_test",
        candidate_project_ids=["proj_route_a", "proj_route_b"],
        db=db_session,
        dry_run=True,
    )
    assert r["total"] == 3
    errs = [a for a in r["assignments"] if a["decision"] == "error"]
    assert len(errs) == 1
    assert "llm timeout" in errs[0]["reason"]