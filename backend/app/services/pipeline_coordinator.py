from datetime import datetime
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.models.project_state import ProjectState, StateChange
from app.models.conflict import Conflict
from app.services.ingestion_service import IngestionService
from app.services.meeting_intelligence import MeetingIntelligenceService
from app.services.project_state_service import ProjectStateService
from app.services.conflict_service import ConflictService

logger = logging.getLogger(__name__)


class PipelineExecutionResult(BaseModel):
    success: bool = True
    message: str
    project_id: str
    meeting_id: Optional[str] = None
    source: str = "google_meet"
    events_ingested: int
    evidence_created: int
    candidates_extracted: int
    proposals_created: int
    conflicts_detected: int = 0
    authoritative_version_before: int
    authoritative_version_after: int  # Must match before! (Proposals do NOT mutate state)
    candidates: List[Dict[str, Any]] = []
    proposals: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []


class PipelineCoordinator:
    """
    Coordinates the end-to-end knowledge pipeline:
    Google Meet -> Source Events -> Evidence -> Meeting Intelligence ->
    Candidate Knowledge -> Conflict Detection -> Project State Proposals.
    
    IMPORTANT:
    The pipeline STOPS before mutating Authoritative Project State.
    Proposals and conflicts remain in 'proposed' / 'open' status awaiting explicit human approval.
    """

    def __init__(
        self,
        ingestion_service: Optional[IngestionService] = None,
        intelligence_service: Optional[MeetingIntelligenceService] = None,
        state_service: Optional[ProjectStateService] = None,
        conflict_service: Optional[ConflictService] = None,
    ):
        self.ingestion_service = ingestion_service or IngestionService()
        self.intelligence_service = intelligence_service or MeetingIntelligenceService()
        self.state_service = state_service or ProjectStateService()
        self.conflict_service = conflict_service or ConflictService(self.state_service)

    def process_meeting(
        self,
        meeting_id: str,
        project_id: str,
        db: Session,
        actor_id: str = "pipeline_worker",
    ) -> PipelineExecutionResult:
        """
        Executes the full pipeline for a meeting.
        Guarantees that Authoritative Project State is NOT modified.
        High-impact candidates become proposals awaiting human approval.
        """
        return self.process_meeting_with_context(
            meeting_id=meeting_id,
            project_id=project_id,
            db=db,
            actor_id=actor_id,
            workspace_id="ws_default",
            tenant_id="default_tenant",
            correlation_id=None,
        )

    def process_meeting_with_context(
        self,
        meeting_id: str,
        project_id: str,
        db: Session,
        actor_id: str = "pipeline_worker",
        workspace_id: str = "ws_default",
        tenant_id: str = "default_tenant",
        correlation_id: Optional[str] = None,
    ) -> PipelineExecutionResult:
        logger.info(
            f"meet_transcript_processing_started: meeting_id={meeting_id} "
            f"project_id={project_id} workspace_id={workspace_id} "
            f"correlation_id={correlation_id}"
        )

        # 0. Ensure Project State exists (baseline v1)
        state = self.state_service.get_or_create_state(project_id, db)
        v_before = state.current_version

        # 1. Normalization & Evidence Creation (Phase 3)
        evidence_records = self.ingestion_service.normalize_meeting_to_evidence(
            meeting_id=meeting_id,
            project_id=project_id,
            db=db,
        )

        # 2. Meeting Intelligence (Phase 4)
        candidates = self.intelligence_service.analyze_meeting_evidence(
            meeting_id=meeting_id,
            project_id=project_id,
            db=db,
        )

        # 3. Validation, Conflict Detection & State Proposals (Phases 5 & 6)
        proposals_created: List[StateChange] = []
        conflicts_created: List[Conflict] = []

        for cand in candidates:
            # Check for semantic / architectural / workflow conflicts
            conflict = self.conflict_service.detect_conflicts_for_candidate(
                candidate=cand,
                db=db,
                tenant_id=tenant_id,
            )
            if conflict:
                conflicts_created.append(conflict)

            # For high-impact items (proposals, decisions, requirements), create proposed StateChange records
            if cand.category in ("proposal", "decision_candidate", "requirement_candidate"):
                change = self.state_service.propose_change_from_candidate(
                    candidate=cand,
                    db=db,
                    actor_id=actor_id,
                )
                proposals_created.append(change)

        # 4. Verify Project State version is UNCHANGED!
        db.refresh(state)
        v_after = state.current_version
        assert v_before == v_after, "PIPELINE VIOLATION: Authoritative Project State was silently mutated!"

        logger.info(
            f"meet_transcript_processing_completed: meeting_id={meeting_id} "
            f"project_id={project_id} workspace_id={workspace_id} "
            f"correlation_id={correlation_id} evidence={len(evidence_records)} "
            f"candidates={len(candidates)} conflicts={len(conflicts_created)} "
            f"proposals={len(proposals_created)}. "
            f"Authoritative Project State remained at v{v_after} (awaiting review)."
        )

        # Sync the project's living Excalidraw workspace from validated state
        # (visual sync only; no silent state mutation, no raw transcript dump).
        try:
            from app.services.project_agent_service import ProjectAgentService

            ProjectAgentService().sync_living_excalidraw_workspace(
                project_id=project_id, db=db, tenant_id=tenant_id
            )
        except Exception as exc:
            logger.warning(
                f"meet_excalidraw_sync_deferred: meeting_id={meeting_id} "
                f"project_id={project_id} error={exc}"
            )

        return PipelineExecutionResult(
            success=True,
            message="Knowledge pipeline executed successfully. Proposals and conflicts ready for review.",
            project_id=project_id,
            meeting_id=meeting_id,
            events_ingested=len(evidence_records),
            evidence_created=len(evidence_records),
            candidates_extracted=len(candidates),
            proposals_created=len(proposals_created),
            conflicts_detected=len(conflicts_created),
            authoritative_version_before=v_before,
            authoritative_version_after=v_after,
            candidates=[
                {
                    "id": c.id,
                    "category": c.category,
                    "classification": c.classification,
                    "title": c.title,
                    "content": c.content,
                }
                for c in candidates
            ],
            proposals=[
                {
                    "id": p.id,
                    "target_section": p.target_section,
                    "operation": p.operation,
                    "status": p.approval_status,
                    "reason": p.reason,
                }
                for p in proposals_created
            ],
            conflicts=[
                {
                    "id": conf.id,
                    "type": conf.type,
                    "severity": conf.severity,
                    "title": conf.title,
                    "status": conf.status,
                }
                for conf in conflicts_created
            ],
        )

    def process_source_events(
        self,
        events: List[Any],
        project_id: str,
        db: Session,
        actor_id: str = "pipeline_worker",
        tenant_id: str = "default_tenant",
        source_name: str = "generic_source",
    ) -> PipelineExecutionResult:
        """
        Executes the common knowledge pipeline for ANY external source (Google Meet, Slack, etc.).
        1. Ingests normalized SourceEvents idempotently
        2. Converts SourceEvents into Evidence records
        3. Runs Intelligence Engine on Evidence
        4. Detects Conflicts with existing Project State
        5. Creates StateChange Proposals
        6. Guarantees Project State remains unchanged until human review.
        """
        logger.info(f"Starting Knowledge Pipeline for {len(events)} events from source '{source_name}' in project '{project_id}'")

        # 0. Ensure Project State exists (baseline v1)
        state = self.state_service.get_or_create_state(project_id, db)
        v_before = state.current_version

        # 1. Ingestion & Evidence Normalization
        ingested_source_events = self.ingestion_service.ingest_events(events, db)
        evidence_records = self.ingestion_service.normalize_events_to_evidence(ingested_source_events, db)

        # 2. Intelligence on Evidence
        candidates = self.intelligence_service.analyze_evidence_records(
            evidence_records=evidence_records,
            project_id=project_id,
            db=db,
            source_name=source_name,
        )

        # 3. Validation, Conflict Detection & State Proposals
        proposals_created: List[StateChange] = []
        conflicts_created: List[Conflict] = []

        for cand in candidates:
            conflict = self.conflict_service.detect_conflicts_for_candidate(
                candidate=cand,
                db=db,
                tenant_id=tenant_id,
            )
            if conflict:
                conflicts_created.append(conflict)

            if cand.category in ("proposal", "decision_candidate", "requirement_candidate"):
                change = self.state_service.propose_change_from_candidate(
                    candidate=cand,
                    db=db,
                    actor_id=actor_id,
                )
                proposals_created.append(change)

        # 4. Verify Project State version is UNCHANGED!
        db.refresh(state)
        v_after = state.current_version
        assert v_before == v_after, "PIPELINE VIOLATION: Authoritative Project State was silently mutated!"

        logger.info(
            f"Multi-source pipeline completed for source '{source_name}': "
            f"events={len(ingested_source_events)}, evidence={len(evidence_records)}, "
            f"candidates={len(candidates)}, conflicts={len(conflicts_created)}, proposals={len(proposals_created)}. "
            f"Authoritative Project State remained at v{v_after} (awaiting review)."
        )

        return PipelineExecutionResult(
            success=True,
            message=f"Knowledge pipeline executed successfully for source '{source_name}'.",
            project_id=project_id,
            meeting_id=None,
            source=source_name,
            events_ingested=len(ingested_source_events),
            evidence_created=len(evidence_records),
            candidates_extracted=len(candidates),
            proposals_created=len(proposals_created),
            conflicts_detected=len(conflicts_created),
            authoritative_version_before=v_before,
            authoritative_version_after=v_after,
            candidates=[
                {
                    "id": c.id,
                    "category": c.category,
                    "classification": c.classification,
                    "title": c.title,
                    "content": c.content,
                }
                for c in candidates
            ],
            proposals=[
                {
                    "id": p.id,
                    "target_section": p.target_section,
                    "operation": p.operation,
                    "status": p.approval_status,
                    "reason": p.reason,
                }
                for p in proposals_created
            ],
            conflicts=[
                {
                    "id": conf.id,
                    "type": conf.type,
                    "severity": conf.severity,
                    "title": conf.title,
                    "status": conf.status,
                }
                for conf in conflicts_created
            ],
        )

