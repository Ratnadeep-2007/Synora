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
from app.services.project_memory_service import ProjectMemoryService
from app.services.meeting_session_intelligence import MeetingSessionIntelligenceService
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
    authoritative_version_after: int
    candidates: List[Dict[str, Any]] = []
    proposals: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    meeting_intelligence: Optional[Dict[str, Any]] = None


class PipelineCoordinator:
    """
    Coordinates the end-to-end knowledge pipeline:
    Google Meet -> Source Events -> Evidence -> Meeting Intelligence ->
    Candidate Knowledge -> Conflict Detection -> Project Memory -> Visual Atlas.

    Routine evidence-backed memory updates are automatic. Only unresolved
    project routing remains in Unknown Context.
    """

    def __init__(
        self,
        ingestion_service: Optional[IngestionService] = None,
        intelligence_service: Optional[MeetingIntelligenceService] = None,
        state_service: Optional[ProjectStateService] = None,
        conflict_service: Optional[ConflictService] = None,
        memory_service: Optional[ProjectMemoryService] = None,
    ):
        self.ingestion_service = ingestion_service or IngestionService()
        self.intelligence_service = intelligence_service or MeetingIntelligenceService()
        self.state_service = state_service or ProjectStateService()
        self.conflict_service = conflict_service or ConflictService(self.state_service)
        self.memory_service = memory_service or ProjectMemoryService(self.state_service)
        self.meeting_session_service = MeetingSessionIntelligenceService()

    def process_meeting(
        self,
        meeting_id: str,
        project_id: str,
        db: Session,
        actor_id: str = "pipeline_worker",
    ) -> PipelineExecutionResult:
        """
        Executes the full pipeline for a meeting.
        Processes a completed meeting through the shared Evidence, Intelligence,
        Project Memory, and Visual Atlas pipeline. Meet-specific session intelligence
        is persisted only as a meeting projection; Project Memory remains shared.
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
        """Process a completed meeting transcript into shared project memory.

        A meeting is an input source, not a separate memory system. The complete
        transcript is already persisted as Evidence by the Meet event worker.
        Evidence is grouped by the project assigned to each transcript segment,
        then the same memory engine used by WhatsApp promotes the extracted
        knowledge automatically. Only project-routing uncertainty remains in
        Unknown Context.
        """
        logger.info(
            f"meet_transcript_processing_started: meeting_id={meeting_id} "
            f"project_id={project_id} workspace_id={workspace_id} "
            f"correlation_id={correlation_id}"
        )

        # Backwards-compatible manual trigger: populate Evidence when this
        # endpoint is called before the event worker has normalized the meeting.
        evidence_records = (
            db.query(Evidence)
            .filter(Evidence.meeting_id == meeting_id)
            .order_by(Evidence.occurred_at.asc())
            .all()
        )
        if not evidence_records:
            evidence_records = self.ingestion_service.normalize_meeting_to_evidence(
                meeting_id=meeting_id,
                project_id=project_id,
                db=db,
            )

        # Group evidence by its already-resolved project. Unknown Context is
        # intentionally excluded from the memory write path.
        grouped: Dict[str, List[Evidence]] = {}
        for evidence in evidence_records:
            target_project = evidence.project_id
            if not target_project:
                continue
            from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
            if target_project == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID:
                continue
            grouped.setdefault(target_project, []).append(evidence)

        candidates_by_project: Dict[str, List[CandidateKnowledge]] = {}
        proposals_created: List[StateChange] = []
        conflicts_created: List[Conflict] = []
        memory_results: Dict[str, Dict[str, Any]] = {}

        for target_project_id, project_evidence in grouped.items():
            candidates = self.intelligence_service.analyze_evidence_records(
                evidence_records=project_evidence,
                project_id=target_project_id,
                db=db,
                meeting_id=meeting_id,
                source_name="google_meet",
            )
            candidates_by_project[target_project_id] = candidates

            cand_conflicts = set()
            for cand in candidates:
                conflict = self.conflict_service.detect_conflicts_for_candidate(
                    candidate=cand,
                    db=db,
                    tenant_id=tenant_id,
                )
                if conflict:
                    conflicts_created.append(conflict)
                    cand_conflicts.add(cand.id)

                if cand.category in ("proposal", "decision_candidate", "requirement_candidate"):
                    change = self.state_service.propose_change_from_candidate(
                        candidate=cand,
                        db=db,
                        actor_id=actor_id,
                    )
                    proposals_created.append(change)

            routine_candidates = [
                cand for cand in candidates
                if cand.category not in ("proposal", "decision_candidate", "requirement_candidate")
                and cand.id not in cand_conflicts
            ]
            if routine_candidates:
                memory_results[target_project_id] = self.memory_service.apply_candidates(
                    project_id=target_project_id,
                    candidates=routine_candidates,
                    db=db,
                    source="google_meet",
                    actor_id=actor_id,
                )
            else:
                target_st = self.state_service.get_or_create_state(target_project_id, db)
                memory_results[target_project_id] = {
                    "project_id": target_project_id,
                    "state_version_before": target_st.current_version,
                    "state_version_after": target_st.current_version,
                    "applied": 0,
                    "skipped": len(candidates),
                    "candidate_ids": [],
                }

        all_candidates = [c for items in candidates_by_project.values() for c in items]

        # The canvas is a projection of per-project evidence. The WhatsApp
        # path applies visual updates automatically after ingestion; the
        # meeting path must do the same, or the canvas silently stops
        # reflecting new knowledge while memory moves on. The same
        # evidence-volume gate applies: below it the content still becomes
        # evidence and knowledge, only the canvas update is withheld.
        #
        # This uses the evidence-linked patch path (generate + apply), not
        # the raw text-to-diagram path: the planner behind the text path is
        # never given real evidence IDs, so its nodes come back ungrounded
        # and the compiler refuses the whole plan. The patch path records
        # the actual evidence IDs and only auto-applies patches whose
        # operations are add-only (SAFE_AUTO_APPLY).
        visual_results: Dict[str, Dict[str, Any]] = {}
        try:
            from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID as _Unknown
            from app.services.visual_patch_service import (
                PatchSafetyClassification,
                VisualPatchService,
            )

            patch_service = VisualPatchService()
            for target_project_id, project_evidence in grouped.items():
                if target_project_id == _Unknown:
                    continue
                total_evidence = (
                    db.query(Evidence)
                    .filter(Evidence.project_id == target_project_id)
                    .count()
                )
                if total_evidence < 2:
                    logger.info(
                        "meet_visual_deferred: project=%s evidence=%d required=2",
                        target_project_id,
                        total_evidence,
                    )
                    visual_results[target_project_id] = {
                        "applied": False,
                        "reason": "deferred_below_evidence_gate",
                    }
                    continue
                visual_text = "\n".join(
                    e.content for e in project_evidence if e.content and e.content.strip()
                )
                if not visual_text.strip():
                    continue
                try:
                    evidence_ids = [e.id for e in project_evidence]
                    patch = patch_service.generate_patch_from_evidence(
                        project_id=target_project_id,
                        text=visual_text,
                        db=db,
                        evidence_ids=evidence_ids,
                        tenant_id=tenant_id,
                    )
                    if patch.safety_classification == PatchSafetyClassification.SAFE_AUTO_APPLY:
                        patch_service.apply_patch(
                            project_id=target_project_id,
                            patch=patch,
                            db=db,
                            actor_id=actor_id,
                            tenant_id=tenant_id,
                        )
                        applied = True
                        reason = "auto_applied_safe_patch"
                    else:
                        applied = False
                        reason = (
                            f"held_for_review:{patch.safety_classification.value}"
                        )
                        logger.info(
                            "meet_visual_held_for_review: project=%s safety=%s",
                            target_project_id,
                            patch.safety_classification.value,
                        )
                    visual_results[target_project_id] = {
                        "applied": applied,
                        "reason": reason,
                        "patch_id": patch.patch_id,
                    }
                    logger.info(
                        "meet_visual_updated: project=%s applied=%s",
                        target_project_id,
                        applied,
                    )
                except Exception as exc:
                    logger.warning(
                        "meet_visual_failed: project=%s error=%s",
                        target_project_id,
                        exc,
                    )
                    visual_results[target_project_id] = {
                        "applied": False,
                        "reason": str(exc)[:500],
                    }
        except Exception as exc:
            logger.warning(
                "meet_visual_skipped: meeting_id=%s error=%s",
                meeting_id,
                exc,
            )

        # Meet has additional session-level structure (speakers, timestamps,
        # segments, action-item owner hints and memory deltas). This is a
        # source-specific projection over the SAME shared Evidence/Candidate/
        # Memory records; it is not a second memory store.
        meeting_intelligence = None
        try:
            meeting_intelligence = self.meeting_session_service.get_or_build(
                meeting_id=meeting_id,
                db=db,
                candidates=all_candidates,
                memory_results=memory_results,
                persist=True,
            )
        except Exception as exc:
            logger.warning(
                "meet_session_intelligence_deferred: meeting_id=%s error=%s",
                meeting_id,
                exc,
            )

        # The visual workspace is a projection of memory. Rebuild once after
        # the complete meeting has been processed across all project segments.
        try:
            from app.services.workspace_atlas_service import WorkspaceAtlasService

            WorkspaceAtlasService().get_or_sync(
                db=db,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                force=False,
            )
        except Exception as exc:
            logger.warning(
                "meet_atlas_sync_deferred: meeting_id=%s error=%s",
                meeting_id,
                exc,
            )

        target_state = self.state_service.get_or_create_state(project_id, db)
        v_after = target_state.current_version
        v_before = min(
            [int(r.get("state_version_before", v_after)) for r in memory_results.values()]
            or [v_after]
        )

        logger.info(
            f"meet_transcript_processing_completed: meeting_id={meeting_id} "
            f"projects={len(grouped)} evidence={len(evidence_records)} "
            f"candidates={len(all_candidates)} conflicts={len(conflicts_created)} "
            f"memory_auto_applied={sum(int(r.get('applied', 0)) for r in memory_results.values())}"
        )

        return PipelineExecutionResult(
            success=True,
            message="Completed meeting transcript processed into shared project memory and visual notes automatically.",
            project_id=project_id,
            meeting_id=meeting_id,
            events_ingested=len(evidence_records),
            evidence_created=len(evidence_records),
            candidates_extracted=len(all_candidates),
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
                for c in all_candidates
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
            meeting_intelligence=meeting_intelligence,
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
        Executes the source-independent path into shared Project Memory.
        Routine evidence-backed updates are applied automatically; unresolved
        project routing is handled by the source intelligence layer.
        """
        logger.info(f"Starting Knowledge Pipeline for {len(events)} events from source '{source_name}' in project '{project_id}'")

        # 0. Ensure Project State exists (baseline v1)
        state = self.state_service.get_or_create_state(project_id, db)
        v_before = state.current_version

        # 1. Ingestion & Evidence Normalization
        ingested_source_events = self.ingestion_service.ingest_events(events, db)
        evidence_records = self.ingestion_service.normalize_events_to_evidence(ingested_source_events, db)

        # 2. Intelligence -> shared Project Memory
        candidates = self.intelligence_service.analyze_evidence_records(
            evidence_records=evidence_records,
            project_id=project_id,
            db=db,
            source_name=source_name,
        )

        conflicts_created: List[Conflict] = []
        for cand in candidates:
            conflict = self.conflict_service.detect_conflicts_for_candidate(
                candidate=cand,
                db=db,
                tenant_id=tenant_id,
            )
            if conflict:
                conflicts_created.append(conflict)

        memory_result = self.memory_service.apply_candidates(
            project_id=project_id,
            candidates=candidates,
            db=db,
            source=source_name,
            actor_id=actor_id,
        )

        try:
            from app.services.workspace_atlas_service import WorkspaceAtlasService
            WorkspaceAtlasService().get_or_sync(
                db=db,
                tenant_id=tenant_id,
                workspace_id="ws_default",
                force=False,
            )
        except Exception as exc:
            logger.warning(
                "source_memory_visual_sync_deferred: source=%s project=%s error=%s",
                source_name,
                project_id,
                exc,
            )

        db.refresh(state)
        v_after = state.current_version
        logger.info(
            f"Multi-source pipeline completed for source '{source_name}': "
            f"events={len(ingested_source_events)}, evidence={len(evidence_records)}, "
            f"candidates={len(candidates)}, memory_applied={memory_result.get('applied', 0)}, "
            f"conflicts={len(conflicts_created)}, state=v_before->{v_after}."
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
            proposals_created=0,
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
            proposals=[],
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

