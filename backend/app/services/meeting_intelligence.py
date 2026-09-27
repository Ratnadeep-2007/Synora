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
from app.services.llm import LLMClient, get_default_llm_client
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

            window_id = f"{meeting_id}:window:{start // max(1, window_size) + 1}"
            for entry in window:
                partitions.setdefault(project.id, []).append(entry)

            resolutions.append({
                "context_window_id": window_id,
                "entry_ids": [entry.id for entry in window],
                "project_id": project.id,
                "project_name": project.name,
                "context_status": result.status,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
                "model": result.model,
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


    def process_meeting_with_auto_context(
        self,
        meeting_id: str,
        db: Session,
        workspace_id: str = "ws_default",
        tenant_id: str = "default_tenant",
        window_size: int = 6,
    ) -> Dict[str, Any]:
        """
        End-to-end Meet processing with context-first routing per transcript window.
        Knowledge extraction is independent from routing, while deterministic
        validation prevents unsafe project assignment.
        """
        partitioned = self.resolve_and_partition_meeting_evidence(
            meeting_id=meeting_id,
            db=db,
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            window_size=window_size,
        )

        from app.services.ingestion_service import IngestionService
        ingestion = IngestionService()
        from app.models.meeting import Meeting
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            raise IntelligenceError(f"Meeting '{meeting_id}' not found.")

        project_results: List[Dict[str, Any]] = []
        for project_id, entries in partitioned["partitions"].items():
            evidence_records: List[Evidence] = []
            for entry in entries:
                event_in = __import__("app.schemas.source_event", fromlist=["SourceEventCreate"]).SourceEventCreate(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source="google_meet",
                    source_event_id=entry.provider_entry_id,
                    event_type="transcript_entry",
                    actor_id=entry.participant.display_name if entry.participant else "Unknown Speaker",
                    occurred_at=entry.start_time,
                    payload={
                        "text": entry.text,
                        "meeting_id": meeting_id,
                        "meeting_title": meeting.title,
                        "conference_id": meeting.provider_conference_id,
                        "participant_id": entry.participant_id,
                    },
                )
                source_event = ingestion.ingest_event(event_in, db)
                evidence_records.append(
                    ingestion.create_evidence_from_event(
                        source_event,
                        db,
                        meeting_id=meeting_id,
                        transcript_entry_id=entry.id,
                        content=entry.text,
                        metadata={
                            "meeting_title": meeting.title,
                            "context_partition_project_id": project_id,
                            "context_partition_source": "shared_context_resolver",
                        },
                    )
                )

            resolution = next(
                (
                    r for r in partitioned["resolutions"]
                    if r["project_id"] == project_id
                    and any(entry.id in r["entry_ids"] for entry in entries)
                ),
                {},
            )
            candidates = self.analyze_evidence_records(
                evidence_records=evidence_records,
                project_id=project_id,
                db=db,
                meeting_id=meeting_id,
                source_name="google_meet",
                context_status=resolution.get("context_status", "unknown"),
                context_confidence=float(resolution.get("confidence", 0.0)),
                context_model=resolution.get("model"),
            )
            project_results.append({
                "project_id": project_id,
                "evidence_created": len(evidence_records),
                "candidates_extracted": len(candidates),
            })

        return {
            "meeting_id": meeting_id,
            "resolutions": partitioned["resolutions"],
            "projects_processed": project_results,
            "unknown_context_project_id": UNKNOWN_CONTEXT_ID,
        }

    def analyze_evidence_records(
        self,
        evidence_records: List[Evidence],
        project_id: str,
        db: Session,
        meeting_id: Optional[str] = None,
        source_name: str = "generic",
        context_status: str = "resolved",
        context_confidence: float = 1.0,
        context_model: Optional[str] = None,
    ) -> List[CandidateKnowledge]:
        """
        Shared semantic classification for Meet, WhatsApp, and other sources.
        Context resolution is independent and recorded as provenance.
        """
        if not evidence_records:
            return []

        input_evidence_ids = [e.id for e in evidence_records]
        t0 = time.time()
        prompt = self._build_evidence_prompt(
            evidence_records,
            f"Extract all candidate proposals, decisions, requirements, questions, and action items with evidence IDs from {source_name} source. Preserve uncertainty and do not invent facts.",
        )
        batch_result = self.llm_client.generate_structured(prompt, ExtractionBatchResult)
        latency_ms = (time.time() - t0) * 1000.0

        agent_run = AgentRun(
            project_id=project_id,
            meeting_id=meeting_id,
            input_evidence_ids_json=json.dumps(input_evidence_ids),
            model=batch_result.model or self.llm_client.__class__.__name__,
            prompt_version=batch_result.prompt_version or "unknown",
            output_reference_json=json.dumps([{"title": i.title, "category": i.category} for i in batch_result.items]),
            status="completed",
            latency_ms=latency_ms,
            source=source_name,
            context_status=context_status,
        )
        db.add(agent_run)
        db.flush()

        persisted: List[CandidateKnowledge] = []
        for item in batch_result.items:
            valid_ids = [eid for eid in item.evidence_ids if eid in input_evidence_ids]
            if not valid_ids:
                logger.warning("Rejected candidate '%s': invalid evidence references.", item.title)
                continue

            existing = (
                db.query(CandidateKnowledge)
                .filter(
                    CandidateKnowledge.project_id == project_id,
                    CandidateKnowledge.category == item.category,
                    CandidateKnowledge.title == item.title,
                )
                .first()
            )
            if existing:
                persisted.append(existing)
                continue

            candidate = CandidateKnowledge(
                project_id=project_id,
                meeting_id=meeting_id,
                category=item.category,
                classification=item.classification.value if hasattr(item.classification, "value") else str(item.classification),
                title=item.title,
                content=item.content,
                confidence=item.confidence,
                evidence_ids_json=json.dumps(valid_ids),
                status="candidate",
                agent_run_id=agent_run.agent_run_id,
                context_status=context_status,
                context_confidence=context_confidence,
                context_model=context_model,
            )
            db.add(candidate)
            persisted.append(candidate)

        db.commit()
        for candidate in persisted:
            db.refresh(candidate)

        logger.info(
            "Evidence intelligence completed for project '%s' (%s): %s candidates in %.1fms; context=%s confidence=%.2f",
            project_id, source_name, len(persisted), latency_ms, context_status, context_confidence,
        )
        return persisted
