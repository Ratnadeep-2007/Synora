import json
import logging
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.context_resolution import ContextDecision
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, Project
from app.models.source_event import SourceEvent
from app.schemas.context import ContextResolutionResult
from app.schemas.source_event import SourceEventCreate
from app.services.context_intelligence import ContextIntelligenceService
from app.services.ingestion_service import IngestionService
from app.services.knowledge_intelligence import KnowledgeExtraction, KnowledgeIntelligenceService
from app.services.metrics import metrics
from app.services.unknown_context_service import UnknownContextService

logger = logging.getLogger(__name__)


class RoutingOutcome(str, Enum):
    RESOLVED = "resolved"
    UNKNOWN_CONTEXT = "unknown_context"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


class SourceEventOutcome(BaseModel):
    outcome: str
    source: str
    source_event_id: Optional[str] = None
    project_id: Optional[str] = None
    evidence_id: Optional[str] = None
    meeting_id: Optional[str] = None
    unknown_item_id: Optional[str] = None
    candidates_created: int = 0
    ai_status: str = "ai_unavailable"
    reason: str = ""


class SourceIntelligencePipeline:
    """Shared source-event pipeline for every connector.

    Google Meet, WhatsApp, Slack and Excalidraw input all flow through here:

        casual-chat gate (drop, never persisted, never shown)
            |
        SourceEvent
            |
            +--> Context Intelligence   (which project?)
            +--> Knowledge Intelligence (what does it mean?)
            |
        Join -> Routing Gate -> Project evidence  OR  Unknown Context

    Exhaustive rule: project-related content is tried deterministically,
    then semantically with full context, then once more at the model's
    extreme. Only if all attempts still fail does it go to Unknown Context.

    The two intelligence branches run concurrently on a shared read-only
    snapshot. The branches are pure (no database access) so they are safe to
    run on worker threads; all persistence happens on the caller's session.
    """

    def __init__(
        self,
        context_service: Optional[ContextIntelligenceService] = None,
        knowledge_service: Optional[KnowledgeIntelligenceService] = None,
        unknown_service: Optional[UnknownContextService] = None,
        ingestion_service: Optional[IngestionService] = None,
    ):
        self.context_service = context_service or ContextIntelligenceService()
        self.knowledge_service = knowledge_service or KnowledgeIntelligenceService()
        self.unknown_service = unknown_service or UnknownContextService(
            context_service=self.context_service
        )
        self.ingestion = ingestion_service or IngestionService()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def process(
        self,
        source: str,
        payload: Dict[str, Any],
        db: Session,
        tenant_id: str = "default_tenant",
        actor_id: Optional[str] = None,
        project_id: Optional[str] = None,
        meeting_id: Optional[str] = None,
        source_event_id: Optional[str] = None,
        event_type: str = "message",
        occurred_at=None,
        continuity_context: Optional[str] = None,
        visual_context: Optional[str] = None,
        authorized_project_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SourceEventOutcome:
        text = self.context_service.extract_text(source, payload)

        # 0. Casual-chat gate: pure banter never touches the DB and never
        # appears in the platform (no SourceEvent, Evidence, or Unknown item).
        if ContextIntelligenceService.is_casual_chatter(text):
            metrics.increment("ingestion_events_total", labels={"source": source, "status": "ignored_casual"})
            logger.info("source_routing_ignored_casual: source=%s", source)
            return SourceEventOutcome(
                outcome=RoutingOutcome.IGNORED.value,
                source=source,
                source_event_id=source_event_id,
                reason="Casual conversation / non-project chit-chat (leave it)",
            )

        # 1. Idempotency: never process the same provider event twice.
        if source_event_id:
            existing = (
                db.query(SourceEvent)
                .filter(
                    SourceEvent.source == source,
                    SourceEvent.source_event_id == source_event_id,
                )
                .first()
            )
            if existing:
                metrics.increment("ingestion_events_total", labels={"source": source, "status": "duplicate"})
                return SourceEventOutcome(
                    outcome=RoutingOutcome.DUPLICATE.value,
                    source=source,
                    source_event_id=source_event_id,
                    project_id=existing.project_id,
                    reason="Event already processed (idempotent replay)",
                )

        # 2. Deterministic context signals (fast path, no model call).
        self.context_service.ensure_unknown_context_project(db)
        authorized = self.context_service._authorized_projects(
            db, tenant_id, authorized_project_ids
        )
        det_signals = self.context_service._deterministic_signals(text, authorized, project_id)
        det_project_id = self.context_service._apply_deterministic(
            det_signals, text, authorized, project_id
        )

        provisional_project_id = det_project_id or SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID

        # 3. Persist the raw event + evidence (provenance always preserved).
        event_in = SourceEventCreate(
            tenant_id=tenant_id,
            project_id=provisional_project_id,
            source=source,
            source_event_id=source_event_id or self._synthetic_event_id(source, text),
            event_type=event_type,
            actor_id=actor_id,
            occurred_at=occurred_at,
            payload=payload,
            status="received",
        )
        source_event = self.ingestion.ingest_event(event_in, db, commit=False)
        db.flush()  # populate the generated event_id before linking evidence
        evidence = self.ingestion.create_evidence_from_event(
            event=source_event,
            db=db,
            meeting_id=meeting_id,
            content=text or None,
            metadata=metadata or {},
            commit=False,
        )
        db.commit()
        db.refresh(source_event)
        db.refresh(evidence)
        metrics.increment("ingestion_events_total", labels={"source": source})

        # 4. Parallel intelligence: Context || Knowledge on a shared snapshot.
        corpus = (
            self.context_service._build_corpus(authorized, db) if not det_project_id else []
        )
        evidence_snapshot = [evidence]

        with ThreadPoolExecutor(max_workers=2) as pool:
            if det_project_id:
                context_result = ContextResolutionResult(
                    decision=ContextDecision.RESOLVED.value,
                    project_id=det_project_id,
                    confidence=1.0,
                    margin=1.0,
                    signals=det_signals,
                    reason=(det_signals[0].detail if det_signals else "Deterministic match"),
                    requires_human_review=False,
                )
                knowledge_future = pool.submit(
                    self.knowledge_service.extract_items, evidence_snapshot, source
                )
                extraction: KnowledgeExtraction = knowledge_future.result()
            else:
                context_future = pool.submit(
                    self.context_service.resolve_with_corpus,
                    text,
                    corpus,
                    det_signals,
                    continuity_context,
                    visual_context,
                )
                knowledge_future = pool.submit(
                    self.knowledge_service.extract_items, evidence_snapshot, source
                )
                context_result = context_future.result()
                extraction = knowledge_future.result()

                # Exhaustive extreme: if still UNKNOWN/AMBIGUOUS, retry the
                # semantic pass once more (model gets a second chance with the
                # same full context). Only if both attempts fail do we fall to
                # Unknown Context. This keeps project talk in-project to the
                # model's limit.
                if (
                    not getattr(context_result, "is_casual", False)
                    and context_result.decision != ContextDecision.CASUAL_IGNORED.value
                    and context_result.decision != ContextDecision.RESOLVED.value
                ):
                    retry = self.context_service.resolve_with_corpus(
                        text,
                        corpus,
                        det_signals,
                        continuity_context,
                        visual_context,
                    )
                    if retry.decision == ContextDecision.RESOLVED.value:
                        logger.info(
                            "source_routing_resolved_on_retry: source=%s project_id=%s",
                            source,
                            retry.project_id,
                        )
                        context_result = retry
                    else:
                        logger.info(
                            "source_routing_exhausted: source=%s decision=%s reason=%s",
                            source,
                            context_result.decision,
                            context_result.reason,
                        )

        # Casual conversation gate: purge completely to prevent platform pollution.
        # Drops banter whether caught by semantic AI intelligence or deterministic regex.
        if (
            getattr(context_result, "is_casual", False)
            or context_result.decision == ContextDecision.CASUAL_IGNORED.value
            or ContextIntelligenceService.is_casual_chatter(text)
        ):
            logger.info(
                "source_event_casual_detected: source=%s dropping event to prevent platform pollution",
                source,
            )
            db.delete(evidence)
            db.delete(source_event)
            db.commit()
            return SourceEventOutcome(
                outcome=RoutingOutcome.IGNORED.value,
                source=source,
                source_event_id=source_event.source_event_id,
                project_id=None,
                reason="Casual non-project conversation detected; ignored to preserve workspace purity",
            )

        # 5. Routing gate.
        resolved_project_id = self._route(context_result, authorized, authorized_project_ids)

        if resolved_project_id:
            # Re-home from the provisional (unknown) project to the resolved project.
            if source_event.project_id != resolved_project_id:
                source_event.project_id = resolved_project_id
                evidence.project_id = resolved_project_id
                db.commit()
            candidates = self.knowledge_service.persist_candidates(
                extraction, project_id=resolved_project_id, db=db, meeting_id=meeting_id
            )
            logger.info(
                "source_routing_resolved: source=%s project_id=%s candidates=%d ai_status=%s",
                source,
                resolved_project_id,
                len(candidates),
                extraction.ai_status,
            )
            return SourceEventOutcome(
                outcome=RoutingOutcome.RESOLVED.value,
                source=source,
                source_event_id=source_event.source_event_id,
                project_id=resolved_project_id,
                evidence_id=evidence.id,
                meeting_id=meeting_id,
                candidates_created=len(candidates),
                ai_status=extraction.ai_status,
                reason=context_result.reason,
            )

        # Unknown Context: evidence preserved, candidates NOT made authoritative.
        item = self.unknown_service.create_item(
            source=source,
            payload=payload,
            db=db,
            tenant_id=tenant_id,
            source_event_id=source_event.source_event_id,
            evidence_id=evidence.id,
            meeting_id=meeting_id,
            actor_id=actor_id,
            content=text,
            occurred_at=occurred_at,
            context_resolution_id=None,
        )
        suggestions = self.context_service.resolve_with_corpus(
            text, corpus, det_signals, continuity_context, visual_context
        )
        self._persist_suggestions(item.id, suggestions, db)
        logger.info(
            "source_routing_unknown_context: source=%s item=%s decision=%s",
            source,
            item.id,
            context_result.decision,
        )
        return SourceEventOutcome(
            outcome=RoutingOutcome.UNKNOWN_CONTEXT.value,
            source=source,
            source_event_id=source_event.source_event_id,
            project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
            evidence_id=evidence.id,
            meeting_id=meeting_id,
            unknown_item_id=item.id,
            candidates_created=0,
            ai_status=extraction.ai_status,
            reason=context_result.reason,
        )

    # ------------------------------------------------------------------
    # Routing gate
    # ------------------------------------------------------------------
    def _route(
        self,
        context_result: ContextResolutionResult,
        authorized: List[Project],
        authorized_project_ids: Optional[List[str]],
    ) -> Optional[str]:
        """Deterministic authorization of a semantic decision.

        Semantic similarity can suggest a project, but only an authorized,
        non-system project may be auto-resolved.
        """
        if context_result.decision != ContextDecision.RESOLVED.value:
            return None
        candidate_id = context_result.project_id
        if not candidate_id or candidate_id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID:
            return None
        project = next((p for p in authorized if p.id == candidate_id), None)
        if not project or not self.context_service._is_authorized(project, authorized_project_ids):
            logger.warning(
                "source_routing_rejected_unauthorized: project_id=%s", candidate_id
            )
            return None
        return project.id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _synthetic_event_id(source: str, text: str) -> str:
        import hashlib

        digest = hashlib.sha256(f"{source}:{text}".encode("utf-8")).hexdigest()[:24]
        return f"{source}_{digest}"

    def _persist_suggestions(
        self, item_id: str, resolution: ContextResolutionResult, db: Session
    ) -> None:
        from app.models.context_resolution import PossibleProjectMatch

        db.query(PossibleProjectMatch).filter(
            PossibleProjectMatch.unknown_item_id == item_id
        ).delete()
        for candidate in resolution.candidate_projects:
            db.add(
                PossibleProjectMatch(
                    unknown_item_id=item_id,
                    candidate_project_id=candidate.project_id,
                    similarity_reason_json=json.dumps(candidate.reasons),
                    supporting_evidence_ids_json=json.dumps(candidate.supporting_evidence_ids),
                    supporting_state_sections_json=json.dumps(candidate.supporting_state_sections),
                    conflicts_json=json.dumps(candidate.conflicts),
                    recommendation="review",
                )
            )
        db.commit()
