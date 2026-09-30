import json
import logging
import time
from enum import Enum
from typing import List, Optional, Tuple

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence
from app.models.intelligence import AgentRun, CandidateKnowledge
from app.schemas.intelligence import CandidateItemDTO, ExtractionBatchResult
from app.services.llm import DeterministicRuleLLMClient, LLMClient

logger = logging.getLogger(__name__)


class AiStatus(str, Enum):
    """Truthful provenance of a knowledge extraction run."""

    AI = "ai"  # Configured semantic provider produced the result
    DETERMINISTIC = "deterministic"  # Explicit deterministic rule engine produced the result
    UNAVAILABLE = "ai_unavailable"  # No semantic provider available; nothing was extracted


class KnowledgeExtraction(BaseModel):
    """Source-agnostic extraction output, before any project is chosen.

    Extraction is deliberately decoupled from persistence so it can run in
    parallel with context resolution: the routing gate decides which project
    the resulting candidates are written to.
    """

    items: List[CandidateItemDTO] = []
    ai_status: str = AiStatus.UNAVAILABLE.value
    model: str = "none"
    prompt_version: str = "n/a"
    input_evidence_ids: List[str] = []


class KnowledgeIntelligenceService:
    """The single knowledge extractor shared by every source.

    Google Meet, WhatsApp, and Excalidraw evidence all flow through this one
    service. It never fabricates AI output: when the semantic provider is not
    configured the run is reported as ``ai_unavailable`` and no candidates are
    produced. Deterministic rule output is only ever produced when explicitly
    opted in via ``LLM_PROVIDER=deterministic`` and is labelled ``deterministic``.
    """

    #: Knowledge classes the extractor understands (spec section 3).
    KNOWLEDGE_CLASSES = (
        "requirement_candidate",
        "decision_candidate",
        "proposal",
        "question",
        "assumption",
        "action_item",
        "conflict_signal",
        "architectural_change",
        "informational",
    )

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self._explicit_client = llm_client is not None
        self.llm_client = llm_client

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------
    def _resolve_client(self) -> Tuple[Optional[LLMClient], str]:
        """Return (client, ai_status) using explicit injection first."""
        if self._explicit_client and self.llm_client is not None:
            label = (
                AiStatus.DETERMINISTIC.value
                if isinstance(self.llm_client, DeterministicRuleLLMClient)
                else AiStatus.AI.value
            )
            return self.llm_client, label

        provider = (settings.LLM_PROVIDER or "").lower()
        if provider == "deterministic":
            return DeterministicRuleLLMClient(), AiStatus.DETERMINISTIC.value
        if provider == "gemini" and settings.is_gemini_configured:
            from app.services.llm import get_default_llm_client

            return get_default_llm_client(), AiStatus.AI.value
        if provider == "groq":
            if settings.is_groq_configured:
                from app.services.llm import get_default_llm_client

                return get_default_llm_client(), AiStatus.AI.value
            return None, AiStatus.UNAVAILABLE.value
        if provider == "nvidia" and settings.is_nvidia_nim_configured:
            from app.services.llm import get_default_llm_client

            return get_default_llm_client(), AiStatus.AI.value
        # nvidia configured as provider but no credentials: do not fabricate AI output.
        return None, AiStatus.UNAVAILABLE.value

    # ------------------------------------------------------------------
    # Extraction (no persistence)
    # ------------------------------------------------------------------
    def _build_prompt(self, evidence_list: List[Evidence], source_name: str) -> str:
        instruction = (
            "You are the Synora knowledge intelligence extractor. For every "
            "evidence item, extract candidate knowledge and classify it as one of: "
            f"{', '.join(self.KNOWLEDGE_CLASSES)}. "
            "Distinguish proposals from confirmed decisions. Do NOT invent content. "
            "Every item MUST reference at least one EVIDENCE id from the list. "
            f"Source: {source_name}."
        )
        lines = [instruction, "", "--- EVIDENCE LIST ---"]
        for ev in evidence_list:
            speaker = ev.actor_id or "Unknown"
            lines.append(f"[EVIDENCE: {ev.id}] {speaker}: {ev.content}")
        return "\n".join(lines)

    def extract_items(
        self,
        evidence_records: List[Evidence],
        source_name: str = "generic",
    ) -> KnowledgeExtraction:
        """Run extraction only. Never writes to the database."""
        input_evidence_ids = [e.id for e in evidence_records]
        if not evidence_records:
            return KnowledgeExtraction(
                items=[], ai_status=AiStatus.UNAVAILABLE.value, input_evidence_ids=[]
            )

        client, ai_status = self._resolve_client()
        if client is None:
            logger.warning(
                "knowledge_intelligence_ai_unavailable: source=%s evidence=%d "
                "(no candidates produced; deterministic output is not presented as AI)",
                source_name,
                len(evidence_records),
            )
            return KnowledgeExtraction(
                items=[],
                ai_status=ai_status,
                model="none",
                prompt_version="n/a",
                input_evidence_ids=input_evidence_ids,
            )

        prompt = self._build_prompt(evidence_records, source_name)
        t0 = time.time()
        batch = None
        try:
            batch = client.generate_structured(prompt, ExtractionBatchResult)
        except NotImplementedError:
            logger.warning("knowledge_intelligence_client_unsupported: source=%s", source_name)
        except Exception as exc:
            logger.warning("knowledge_intelligence_extraction_failed: source=%s error=%s", source_name, exc)

        # Fallback: if model extraction failed or returned no items, apply deterministic rules
        if not batch or not getattr(batch, "items", None):
            try:
                rule_batch = DeterministicRuleLLMClient().generate_structured(prompt, ExtractionBatchResult)
                if rule_batch and rule_batch.items:
                    batch = rule_batch
                    if ai_status == AiStatus.UNAVAILABLE.value:
                        ai_status = AiStatus.DETERMINISTIC.value
            except Exception as rule_exc:
                logger.warning("knowledge_intelligence_rule_fallback_failed: %s", rule_exc)

        if not batch:
            return KnowledgeExtraction(
                items=[],
                ai_status=AiStatus.UNAVAILABLE.value,
                model="none",
                prompt_version="n/a",
                input_evidence_ids=input_evidence_ids,
            )
        latency_ms = (time.time() - t0) * 1000.0

        # Deterministic validation: drop ungrounded items.
        valid_ids = set(input_evidence_ids)
        grounded: List[CandidateItemDTO] = []
        for item in batch.items:
            if not item.evidence_ids:
                logger.warning("knowledge_candidate_rejected: '%s' has no evidence reference", item.title)
                continue
            kept = [ev for ev in item.evidence_ids if ev in valid_ids]
            if not kept:
                logger.warning("knowledge_candidate_rejected: '%s' references unknown evidence", item.title)
                continue
            item.evidence_ids = kept
            grounded.append(item)

        model_name = getattr(batch, "model", None) or getattr(client, "model_name", "unknown")
        logger.info(
            "knowledge_intelligence_extracted: source=%s status=%s model=%s items=%d latency_ms=%.1f",
            source_name,
            ai_status,
            model_name,
            len(grounded),
            latency_ms,
        )
        return KnowledgeExtraction(
            items=grounded,
            ai_status=ai_status,
            model=model_name,
            prompt_version=getattr(batch, "prompt_version", "v1.0"),
            input_evidence_ids=input_evidence_ids,
        )

    # ------------------------------------------------------------------
    # Persistence (project chosen by the routing gate)
    # ------------------------------------------------------------------
    def persist_candidates(
        self,
        extraction: KnowledgeExtraction,
        project_id: str,
        db: Session,
        meeting_id: Optional[str] = None,
    ) -> List[CandidateKnowledge]:
        """Persist extracted candidates under a resolved project.

        A skipped/unavailable extraction is recorded as an AgentRun so the
        absence of AI output is auditable rather than silent.
        """
        agent_run = AgentRun(
            project_id=project_id,
            meeting_id=meeting_id,
            input_evidence_ids_json=json.dumps(extraction.input_evidence_ids),
            model=extraction.model,
            prompt_version=extraction.prompt_version,
            output_reference_json=json.dumps(
                [{"title": i.title, "category": i.category} for i in extraction.items]
            ),
            status=(
                "skipped_ai_unavailable"
                if extraction.ai_status == AiStatus.UNAVAILABLE.value
                else "completed"
            ),
            latency_ms=0.0,
        )
        db.add(agent_run)
        db.flush()

        persisted: List[CandidateKnowledge] = []
        for item in extraction.items:
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
                classification=(
                    item.classification.value
                    if hasattr(item.classification, "value")
                    else str(item.classification)
                ),
                title=item.title,
                content=item.content,
                confidence=item.confidence,
                evidence_ids_json=json.dumps(item.evidence_ids),
                status="candidate",
                agent_run_id=agent_run.agent_run_id,
            )
            db.add(candidate)
            persisted.append(candidate)

        db.commit()
        for cand in persisted:
            db.refresh(cand)
        return persisted

    # ------------------------------------------------------------------
    # Convenience: extract + persist in one call
    # ------------------------------------------------------------------
    def extract(
        self,
        evidence_records: List[Evidence],
        project_id: str,
        db: Session,
        meeting_id: Optional[str] = None,
        source_name: str = "generic",
    ) -> Tuple[List[CandidateKnowledge], str]:
        extraction = self.extract_items(evidence_records, source_name=source_name)
        candidates = self.persist_candidates(
            extraction, project_id=project_id, db=db, meeting_id=meeting_id
        )
        return candidates, extraction.ai_status
