from datetime import datetime, timezone
import json
import logging
import time
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.evidence import Evidence
from app.models.intelligence import AgentRun, CandidateKnowledge
from app.schemas.intelligence import CandidateItemDTO, ExtractionBatchResult
from app.services.llm import DeterministicRuleLLMClient, LLMClient, get_default_llm_client
from app.services.context_resolver import ContextResolverService, UNKNOWN_CONTEXT_ID

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
    The LLM is NOT the source of truth.
    The LLM creates CandidateKnowledge.
    CandidateKnowledge does NOT modify authoritative Project State.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None, context_resolver: Optional[ContextResolverService] = None):
        self.llm_client = llm_client or get_default_llm_client()
        self.context_resolver = context_resolver or ContextResolverService(llm_client=self.llm_client)

    def _build_evidence_prompt(self, evidence_list: List[Evidence], task_instruction: str) -> str:
        """Formats evidence snippets into a structured prompt with explicit evidence IDs."""
        lines = [task_instruction, "\n--- EVIDENCE LIST ---"]
        for ev in evidence_list:
            speaker = ev.actor_id or "Unknown"
            lines.append(f"[EVIDENCE: {ev.id}] {speaker}: {ev.content}")
        return "\n".join(lines)


    def resolve_and_partition_meeting_evidence(
        self,
        meeting_id: str,
        db: Session,
        workspace_id: str = "ws_default",
        tenant_id: str = "default_tenant",
        window_size: int = 6,
    ) -> Dict[str, Any]:
        """
        Resolve transcript context per small conversation window.
        This lets one Meet contain multiple project contexts without forcing
        the entire meeting into one project.
        """
        from app.models.meeting import Meeting, TranscriptEntry
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            raise IntelligenceError(f"Meeting '{meeting_id}' not found.")

        entries = (
            db.query(TranscriptEntry)
            .join(TranscriptEntry.transcript)
            .filter(TranscriptEntry.transcript.has(meeting_id=meeting_id))
            .order_by(TranscriptEntry.start_time.asc())
            .all()
        )
        partitions: Dict[str, List[Any]] = {}
        resolutions: List[Dict[str, Any]] = []

        for start in range(0, len(entries), max(1, window_size)):
            window = entries[start:start + max(1, window_size)]
            window_text = "\n".join(
                f"{entry.participant.display_name if entry.participant else 'Unknown Speaker'}: {entry.text}"
                for entry in window if entry.text and entry.text.strip()
            )
            if not window_text.strip():
                continue

            result = self.context_resolver.resolve(
                text=window_text,
                db=db,
                workspace_id=workspace_id,
                metadata={
                    "meeting_title": meeting.title,
                    "meeting_id": meeting_id,
                    "source_name": "google_meet",
                    "participants": [
                        entry.participant.display_name
                        for entry in window
                        if entry.participant and entry.participant.display_name
                    ],
                },
            )
            project, result = self.context_resolver.route_or_quarantine(
                result=result,
                db=db,
                workspace_id=workspace_id,
                tenant_id=tenant_id,
            )

            for entry in window:
                partitions.setdefault(project.id, []).append(entry)

            resolutions.append({
                "entry_ids": [entry.id for entry in window],
                "project_id": project.id,
                "project_name": project.name,
                "context_status": result.status,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
                "candidates": [candidate.model_dump() for candidate in result.candidates],
            })

        return {
            "meeting_id": meeting_id,
            "partitions": partitions,
            "resolutions": resolutions,
            "unknown_context_project_id": UNKNOWN_CONTEXT_ID,
        }

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
            "Extract all candidate proposals, decisions, requirements, questions, and action items with evidence IDs.",
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
            f"Meeting intelligence completed for meeting '{meeting_id}': "
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
            f"Extract all candidate proposals, decisions, requirements, questions, and action items with evidence IDs from {source_name} source.",
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

