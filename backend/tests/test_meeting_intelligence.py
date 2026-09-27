"""
Unit & Integration Tests for Checkpoint 2: Meeting Intelligence (Phase 4).
"""
import json
import pytest
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.intelligence import AgentRun, CandidateKnowledge, ClassificationEnum
from app.models.meeting import Meeting
from app.models.source_event import SourceEvent
from app.models.user import User
from app.schemas.intelligence import CandidateItemDTO, ExtractionBatchResult
from app.services.llm import DeterministicRuleLLMClient
from app.services.meeting_intelligence import MeetingIntelligenceService


@pytest.fixture
def intelligence_service() -> MeetingIntelligenceService:
    return MeetingIntelligenceService(llm_client=DeterministicRuleLLMClient())


@pytest.fixture
def fixture_evidence_records(db_session: Session, test_user: User) -> list[Evidence]:
    """Generates evidence records matching the exact prompt testing dataset."""
    meeting = Meeting(
        id="mtg_intel_test",
        project_id="proj_intel",
        user_id=test_user.id,
        provider="google",
        provider_conference_id="conf_intel",
        status="ENDED",
    )
    db_session.add(meeting)
    db_session.commit()

    source_event = SourceEvent(
        event_id="evt_root_intel",
        tenant_id="tenant_1",
        project_id="proj_intel",
        source="google_meet",
        source_event_id="upstream_intel_batch",
        event_type="transcript_batch",
        payload_json=json.dumps({"info": "batch"}),
        status="processed",
    )
    db_session.add(source_event)
    db_session.commit()

    test_utterances = [
        ("ev_1", "Alice", "Maybe we should add onboarding."),
        ("ev_2", "Bob", "I think we need onboarding."),
        ("ev_3", "Alice", "Let's discuss onboarding tomorrow."),
        ("ev_4", "Charlie", "I'm not agreeing yet."),
        ("ev_5", "Bob", "Okay, let's do it."),
        ("ev_6", "Alice", "We decided to use onboarding."),
        ("ev_7", "Dave", "Let's reverse yesterday's decision."),
        ("ev_8", "Alice", "One requirement is that the user provides business context."),
        ("ev_9", "Bob", "We could add a general onboarding agent."),
    ]

    records = []
    for ev_id, speaker, text in test_utterances:
        ev = Evidence(
            id=ev_id,
            project_id="proj_intel",
            source="google_meet",
            source_event_id=source_event.event_id,
            meeting_id=meeting.id,
            actor_id=speaker,
            content=text,
        )
        db_session.add(ev)
        records.append(ev)

    db_session.commit()
    return records


def test_proposal_vs_decision_distinction(intelligence_service: MeetingIntelligenceService, fixture_evidence_records: list[Evidence]):
    """
    Conservative extraction:
    - 'We could add a general onboarding agent.' MUST be Proposal, NOT Decision.
    - 'We decided to use onboarding.' MUST be DecisionCandidate.
    """
    ev_proposal = [e for e in fixture_evidence_records if "could add a general" in e.content]
    ev_decision = [e for e in fixture_evidence_records if "decided to use onboarding" in e.content]

    proposals = intelligence_service.extract_proposals(ev_proposal)
    assert len(proposals) == 1
    assert proposals[0].category == "proposal"
    assert proposals[0].classification == ClassificationEnum.PROPOSAL

    decisions = intelligence_service.extract_decisions(ev_decision)
    assert len(decisions) == 1
    assert decisions[0].category == "decision_candidate"
    assert decisions[0].classification == ClassificationEnum.DECISION


def test_requirement_extraction(intelligence_service: MeetingIntelligenceService, fixture_evidence_records: list[Evidence]):
    """'One requirement is that the user provides business context.' -> Requirement."""
    ev_req = [e for e in fixture_evidence_records if "requirement is that" in e.content]
    reqs = intelligence_service.extract_requirements(ev_req)

    assert len(reqs) == 1
    assert reqs[0].category == "requirement_candidate"
    assert reqs[0].classification == ClassificationEnum.REQUIREMENT
    assert reqs[0].evidence_ids == ["ev_8"]


def test_question_and_reversal_extraction(intelligence_service: MeetingIntelligenceService, fixture_evidence_records: list[Evidence]):
    """
    - 'Let's discuss onboarding tomorrow.' -> Question
    - 'Let's reverse yesterday's decision.' -> Superseded Decision
    """
    ev_q = [e for e in fixture_evidence_records if "discuss onboarding tomorrow" in e.content]
    questions = intelligence_service.extract_questions(ev_q)
    assert len(questions) == 1
    assert questions[0].classification == ClassificationEnum.QUESTION

    ev_rev = [e for e in fixture_evidence_records if "reverse yesterday" in e.content]
    reversals = intelligence_service.extract_decisions(ev_rev)
    assert len(reversals) == 1
    assert reversals[0].classification == ClassificationEnum.SUPERSEDED


def test_full_meeting_intelligence_analysis(
    intelligence_service: MeetingIntelligenceService,
    fixture_evidence_records: list[Evidence],
    db_session: Session,
):
    """
    Analyze entire meeting evidence set:
    - Extracts candidates
    - Records AgentRun with latency and inputs
    - Verifies all candidates reference valid evidence IDs
    """
    meeting_id = fixture_evidence_records[0].meeting_id
    project_id = fixture_evidence_records[0].project_id

    candidates = intelligence_service.analyze_meeting_evidence(meeting_id, project_id, db_session)
    assert len(candidates) >= 5

    for cand in candidates:
        assert cand.id.startswith("cand_")
        assert cand.status == "candidate"
        ev_ids = json.loads(cand.evidence_ids_json)
        assert len(ev_ids) > 0, f"Candidate {cand.title} has no evidence reference!"
        assert cand.agent_run_id is not None

    # Check AgentRun
    agent_run = db_session.query(AgentRun).filter_by(meeting_id=meeting_id).first()
    assert agent_run is not None
    assert agent_run.status == "completed"
    assert agent_run.latency_ms >= 0


def test_missing_evidence_rejection(db_session: Session):
    """Candidates without evidence or with non-existent evidence IDs must be deterministically rejected."""
    class FakeLLMWithBadEvidence(DeterministicRuleLLMClient):
        def generate_structured(self, prompt, schema):
            return ExtractionBatchResult(
                items=[
                    CandidateItemDTO(
                        category="proposal",
                        classification=ClassificationEnum.PROPOSAL,
                        title="Invalid candidate with no evidence",
                        content="Content without evidence",
                        evidence_ids=["ev_non_existent_fake_id"],
                    )
                ]
            )

    svc = MeetingIntelligenceService(llm_client=FakeLLMWithBadEvidence())
    
    # Run analysis on a meeting that has real evidence
    ev = Evidence(
        id="ev_real_100",
        project_id="proj_val",
        source="google_meet",
        source_event_id="evt_root_intel",
        meeting_id="mtg_intel_test",
        content="Real speech",
    )
    db_session.add(ev)
    db_session.commit()

    candidates = svc.analyze_meeting_evidence("mtg_intel_test", "proj_val", db_session)
    # The candidate referencing "ev_non_existent_fake_id" must be rejected!
    assert len(candidates) == 0
