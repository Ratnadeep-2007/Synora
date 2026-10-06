from datetime import datetime, timezone
import json
import logging
import time
from typing import List, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.evidence import Evidence
from app.models.intelligence import AgentRun, CandidateKnowledge
from app.schemas.intelligence import CandidateItemDTO, ExtractionBatchResult
from app.services.llm import DeterministicRuleLLMClient, LLMClient, get_default_llm_client

logger = logging.getLogger(__name__)


class IntelligenceError(SynesisException):
    """Raised when an error occurs during meeting intelligence extraction."""
    pass


class MeetingIntelligenceService:
    """
    Meeting Intelligence Service.
    Extracts structured candidate knowledge (Proposals, Decisions, Requirements, Questions)
    from immutable Evidence records.
    
    IMPORTANT ARCHITECTURAL RULE:
    The LLM is NOT the source of truth. It creates CandidateKnowledge with evidence IDs.
    ProjectMemoryService is the shared memory write boundary. MeetingSessionIntelligence
    is a projection over shared Evidence/CandidateKnowledge and never owns project truth.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or get_default_llm_client()

    def _build_evidence_prompt(self, evidence_list: List[Evidence], task_instruction: str) -> str:
        """Formats evidence snippets into a structured prompt with explicit evidence IDs."""
        lines = [task_instruction, "\n--- EVIDENCE LIST ---"]
        for ev in evidence_list:
            speaker = ev.actor_id or "Unknown"
            lines.append(f"[EVIDENCE: {ev.id}] {speaker}: {ev.content}")
        return "\n".join(lines)

    # Canonical category vocabulary. The extractor prompt historically asked
    # for short forms ("decision", "requirement") while every downstream
    # consumer - the pipeline coordinator's proposal branch and the memory
    # service's STATE_TARGETS - only understands the "_candidate" forms.
    # Candidates persisted under the short forms fell through both branches:
    # never proposed, never memorized. Verified live 2026-10-06: two meeting
    # candidates with category "decision" produced zero state changes.
    CATEGORY_ALIASES = {
        "decision": "decision_candidate",
        "requirement": "requirement_candidate",
    }

    @classmethod
    def normalize_category(cls, category: Optional[str]) -> str:
        """Map a produced category onto the canonical vocabulary."""
        value = str(category or "").strip().lower()
        return cls.CATEGORY_ALIASES.get(value, value)

    # The model previously labelled everything "proposal", so meetings that
    # plainly contained decisions and requirements projected as zero decisions
    # and zero requirements. The categories are spelled out because the model
    # was not inferring the boundary between them reliably.
    CATEGORY_GUIDE = """
CLASSIFY EACH ITEM INTO EXACTLY ONE CATEGORY. These boundaries matter:

- decision_candidate: the team has ALREADY settled it. Look for agreement, commitment or
  present-tense statements of fact ("we decided", "we will use", "we are going
  with", "keep it separate"). A decision is NOT a suggestion.
- requirement_candidate: the product or system must do something. Look for "must", "needs
  to", "has to", "should be able to", or an explicit capability demand.
- constraint: a rule or limit that restricts the design ("never charge before
  stock confirmation", "read only, no writes", "must not exceed").
- action_item: a named person commits to doing something, usually with a
  deadline ("I will write the contract by Friday").
- question: something unresolved or asked ("do we need", "should we").
- assumption: something taken as true without confirmation.
- proposal: ONLY an idea put forward that is not yet agreed ("what if we",
  "maybe we could", "it might be worth").

A sentence like "Let's keep the Catalogue Service separate from the Order
Service" is a DECISION, not a proposal. If nobody disagreed and it is stated as
the way things will be, it is a decision.

Return "category" as exactly one of these lowercase words:
decision_candidate | requirement_candidate | constraint | action_item | question | assumption | proposal
"""

    def extract_proposals(self, evidence_list: List[Evidence]) -> List[CandidateItemDTO]:
        """Narrow intelligence capability: Extract proposals and ideas."""
        prompt = self._build_evidence_prompt(
            evidence_list,
            "Extract any suggestions, ideas, or proposals made by participants. Do NOT extract confirmed decisions.",
        )
        batch = self.llm_client.generate_structured(prompt, ExtractionBatchResult)
        return [item for item in batch.items if item.category == "proposal"]

    def extract_decisions(self, evidence_list: List[Evidence]) -> List[CandidateItemDTO]:
        """Narrow intelligence capability: Extract decision candidates."""
        prompt = self._build_evidence_prompt(
            evidence_list,
            "Extract explicitly confirmed decisions or agreed direction. Keep supporting evidence attached.",
        )
        batch = self.llm_client.generate_structured(prompt, ExtractionBatchResult)
        return [item for item in batch.items if item.category == "decision_candidate"]

    def extract_requirements(self, evidence_list: List[Evidence]) -> List[CandidateItemDTO]:
        """Narrow intelligence capability: Extract product and technical requirements."""
        prompt = self._build_evidence_prompt(
            evidence_list,
            "Extract explicit functional or business requirements stated by participants.",
        )
        batch = self.llm_client.generate_structured(prompt, ExtractionBatchResult)
        return [item for item in batch.items if item.category == "requirement_candidate"]

    def extract_questions(self, evidence_list: List[Evidence]) -> List[CandidateItemDTO]:
        """Narrow intelligence capability: Extract open questions and unresolved discussion."""
        prompt = self._build_evidence_prompt(
            evidence_list,
            "Extract open questions, objections, or unresolved discussion topics.",
        )
        batch = self.llm_client.generate_structured(prompt, ExtractionBatchResult)
        return [item for item in batch.items if item.category == "question"]

    def analyze_meeting_evidence(
        self,
        meeting_id: str,
        project_id: str,
        db: Session,
    ) -> List[CandidateKnowledge]:
        """
        Orchestrates meeting intelligence across evidence records for a meeting.
        Validates model output deterministically, records AgentRun, and persists CandidateKnowledge.
        """
        evidence_records = (
            db.query(Evidence)
            .filter(Evidence.meeting_id == meeting_id)
            .order_by(Evidence.occurred_at.asc())
            .all()
        )

        if not evidence_records:
            logger.warning(f"No evidence found for meeting '{meeting_id}'. Intelligence extraction skipped.")
            return []

        input_evidence_ids = [e.id for e in evidence_records]
        t0 = time.time()

        # Run extraction across narrow intelligence capabilities
        prompt = self._build_evidence_prompt(
            evidence_records,
            "Extract all candidate proposals, decisions, requirements, questions, "
            "and action items with evidence IDs.\n" + self.CATEGORY_GUIDE,
        )
        batch_result = self.llm_client.generate_structured(prompt, ExtractionBatchResult)
        latency_ms = (time.time() - t0) * 1000.0

        # Persist AgentRun record (observability)
        agent_run = AgentRun(
            project_id=project_id,
            meeting_id=meeting_id,
            input_evidence_ids_json=json.dumps(input_evidence_ids),
            model="synesis-intelligence-v1",
            prompt_version="v1.0",
            output_reference_json=json.dumps([{"title": item.title, "category": item.category} for item in batch_result.items]),
            status="completed",
            latency_ms=latency_ms,
        )
        db.add(agent_run)
        db.flush()

        persisted_candidates: List[CandidateKnowledge] = []

        for item in batch_result.items:
            # Normalize onto the canonical vocabulary before anything else,
            # so dedup and persistence agree on the stored form.
            item.category = self.normalize_category(item.category)
            # Deterministic Validation Rule 1: Must have non-empty evidence IDs
            if not item.evidence_ids or len(item.evidence_ids) == 0:
                logger.warning(f"Rejected candidate '{item.title}' without evidence reference.")
                continue

            # Deterministic Validation Rule 2: Evidence IDs must actually exist in the input set
            valid_evidence_ids = [ev_id for ev_id in item.evidence_ids if ev_id in input_evidence_ids]
            if not valid_evidence_ids:
                logger.warning(f"Rejected candidate '{item.title}': Referenced evidence IDs not found in meeting evidence.")
                continue

            # Check if this exact candidate content already exists for this meeting
            existing_candidate = (
                db.query(CandidateKnowledge)
                .filter(
                    CandidateKnowledge.project_id == project_id,
                    CandidateKnowledge.meeting_id == meeting_id,
                    CandidateKnowledge.category == item.category,
                    CandidateKnowledge.title == item.title,
                )
                .first()
            )

            if existing_candidate:
                persisted_candidates.append(existing_candidate)
                continue

            candidate = CandidateKnowledge(
                project_id=project_id,
                meeting_id=meeting_id,
                category=item.category,
                classification=item.classification.value if hasattr(item.classification, "value") else str(item.classification),
                title=item.title,
                content=item.content,
                confidence=item.confidence,
                evidence_ids_json=json.dumps(valid_evidence_ids),
                status="candidate",
                agent_run_id=agent_run.agent_run_id,
            )
            db.add(candidate)
            persisted_candidates.append(candidate)

        db.commit()
        for cand in persisted_candidates:
            db.refresh(cand)

        logger.info(
            f"Meeting candidate extraction completed for meeting '{meeting_id}': "
            f"{len(persisted_candidates)} candidates extracted in {latency_ms:.1f}ms."
        )
        return persisted_candidates

    def analyze_evidence_records(
        self,
        evidence_records: List[Evidence],
        project_id: str,
        db: Session,
        meeting_id: Optional[str] = None,
        source_name: str = "generic",
    ) -> List[CandidateKnowledge]:
        """
        Provider-agnostic intelligence extraction directly on Evidence records.
        Processes evidence from Google Meet, Slack, or any source identically.
        """
        if not evidence_records:
            logger.warning(f"No evidence provided for project '{project_id}'. Intelligence extraction skipped.")
            return []

        input_evidence_ids = [e.id for e in evidence_records]
        t0 = time.time()

        prompt = self._build_evidence_prompt(
            evidence_records,
            f"Extract all candidate proposals, decisions, requirements, questions, "
            f"and action items with evidence IDs from {source_name} source.\n"
            + self.CATEGORY_GUIDE,
        )
        batch_result = self.llm_client.generate_structured(prompt, ExtractionBatchResult)
        latency_ms = (time.time() - t0) * 1000.0

        agent_run = AgentRun(
            project_id=project_id,
            meeting_id=meeting_id,
            input_evidence_ids_json=json.dumps(input_evidence_ids),
            model="synesis-intelligence-v1",
            prompt_version="v1.0",
            output_reference_json=json.dumps([{"title": item.title, "category": item.category} for item in batch_result.items]),
            status="completed",
            latency_ms=latency_ms,
        )
        db.add(agent_run)
        db.flush()

        persisted_candidates: List[CandidateKnowledge] = []
        for item in batch_result.items:
            # Same canonicalization as analyze_meeting_evidence: the stored
            # category is what the coordinator and memory service match on.
            item.category = self.normalize_category(item.category)
            if not item.evidence_ids or len(item.evidence_ids) == 0:
                continue

            valid_evidence_ids = [ev_id for ev_id in item.evidence_ids if ev_id in input_evidence_ids]
            if not valid_evidence_ids:
                continue

            existing_candidate = (
                db.query(CandidateKnowledge)
                .filter(
                    CandidateKnowledge.project_id == project_id,
                    CandidateKnowledge.category == item.category,
                    CandidateKnowledge.title == item.title,
                )
                .first()
            )
            if existing_candidate:
                persisted_candidates.append(existing_candidate)
                continue

            candidate = CandidateKnowledge(
                project_id=project_id,
                meeting_id=meeting_id,
                category=item.category,
                classification=item.classification.value if hasattr(item.classification, "value") else str(item.classification),
                title=item.title,
                content=item.content,
                confidence=item.confidence,
                evidence_ids_json=json.dumps(valid_evidence_ids),
                status="candidate",
                agent_run_id=agent_run.agent_run_id,
            )
            db.add(candidate)
            persisted_candidates.append(candidate)

        db.commit()
        for cand in persisted_candidates:
            db.refresh(cand)

        logger.info(
            f"Evidence intelligence completed for project '{project_id}' ({source_name}): "
            f"{len(persisted_candidates)} candidates extracted in {latency_ms:.1f}ms."
        )
        return persisted_candidates

