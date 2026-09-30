from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.excalidraw import (
    ExcalidrawArtifact,
    ExcalidrawProposal,
    ExcalidrawProposalStatus,
)
from app.models.evidence import Evidence
from app.models.project import Project
from app.models.project_state import ProjectState, ProjectStateVersion
from app.schemas.excalidraw import (
    ExcalidrawArtifactRead,
    ExcalidrawDiffPreview,
    ExcalidrawIngestRequest,
    ExcalidrawProposalRead,
)
from app.schemas.source_event import SourceEventCreate
from app.schemas.visual_patch import VisualPatch
from app.services.audit_service import AuditService
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)


class ExcalidrawError(SynesisException):
    """Raised when an operation on an Excalidraw artifact or proposal fails."""
    pass


class ExcalidrawService:
    """
    Excalidraw Service managing visual architecture diagrams in Synesis.
    Fulfills two explicit roles:
    - Role A (Input): Ingests visual diagram scenes as evidence.
    - Role B (Output): Proposes diagram changes derived from approved Project State,
      strictly requiring human approval before mutation (Output Safety).
    """

    def __init__(
        self,
        ingestion_service: Optional[IngestionService] = None,
        audit_service: Optional[AuditService] = None,
    ):
        self.ingestion_service = ingestion_service or IngestionService()
        self.audit_service = audit_service or AuditService()

    def get_or_create_artifact(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        name: str = "System Architecture Diagram",
    ) -> ExcalidrawArtifact:
        """Retrieves existing visual artifact or initializes baseline."""
        artifact = (
            db.query(ExcalidrawArtifact)
            .filter(
                ExcalidrawArtifact.project_id == project_id,
                ExcalidrawArtifact.tenant_id == tenant_id,
            )
            .first()
        )
        if not artifact:
            # Clean baseline without predefined boilerplate:
            initial_elements = []
            baseline_nodes = []
            artifact = ExcalidrawArtifact(
                project_id=project_id,
                tenant_id=tenant_id,
                name=name,
                version=1,
                elements_json=json.dumps(initial_elements),
                app_state_json=json.dumps({"viewBackgroundColor": "#ffffff", "gridSize": 20}),
                extracted_nodes_json=json.dumps(baseline_nodes),
            )
            db.add(artifact)
            db.commit()
            db.refresh(artifact)
            logger.info(f"Initialized clean ExcalidrawArtifact v1 for project '{project_id}'")

        # Ensure the project's immutable visual revision history exists.
        self._ensure_visual_revision(artifact, db, tenant_id=tenant_id, name=name)

        # Reconcile artifact elements with current visual revision if artifact is empty or behind
        from app.services.visual_revision_service import VisualRevisionService
        current_rev = VisualRevisionService(audit_service=self.audit_service).current_revision(project_id, db)
        if current_rev and current_rev.scene_json:
            try:
                rev_elements = json.loads(current_rev.scene_json)
                art_elements = json.loads(artifact.elements_json) if artifact.elements_json else []
                if rev_elements and not art_elements:
                    artifact.elements_json = current_rev.scene_json
                    if current_rev.app_state_json:
                        artifact.app_state_json = current_rev.app_state_json
                    artifact.version = max(artifact.version, current_rev.revision_number)
                    artifact.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    db.refresh(artifact)
            except Exception as exc:
                logger.warning(f"Failed to reconcile artifact with visual revision: {exc}")

        return artifact

    def _ensure_visual_revision(
        self,
        artifact: ExcalidrawArtifact,
        db: Session,
        tenant_id: str = "default_tenant",
        name: str = "Living Visual Workspace",
    ) -> None:
        """Seed the visual workspace with revision 1 if no revisions exist yet."""
        from app.services.visual_revision_service import VisualRevisionService

        service = VisualRevisionService()
        workspace = service.get_or_create_workspace(
            artifact.project_id, db, tenant_id=tenant_id, name=name
        )
        if workspace.current_revision_id:
            return
        service.commit_revision(
            project_id=artifact.project_id,
            scene=json.loads(artifact.elements_json) if artifact.elements_json else [],
            db=db,
            tenant_id=tenant_id,
            app_state=json.loads(artifact.app_state_json) if artifact.app_state_json else {},
            operations=[{"op_type": "update", "payload": {"action": "initialize"}}],
            actor_id="system",
            reason="Initial visual workspace revision",
            workspace_name=name,
        )

    def ingest_diagram(
        self,
        project_id: str,
        req: ExcalidrawIngestRequest,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> tuple[ExcalidrawArtifact, Evidence]:
        """
        Role A (Input): Ingests an Excalidraw scene as authoritative architectural evidence.
        Emits a SourceEvent ('excalidraw', 'diagram_change') and creates an Evidence record.
        """
        extracted_nodes = self._extract_node_labels(req.elements)
        artifact = (
            db.query(ExcalidrawArtifact)
            .filter(
                ExcalidrawArtifact.project_id == project_id,
                ExcalidrawArtifact.tenant_id == tenant_id,
            )
            .first()
        )

        if not artifact:
            artifact = ExcalidrawArtifact(
                project_id=project_id,
                tenant_id=tenant_id,
                name=req.name,
                version=1,
                elements_json=json.dumps(req.elements),
                app_state_json=json.dumps(req.app_state),
                extracted_nodes_json=json.dumps(extracted_nodes),
            )
            db.add(artifact)
        else:
            artifact.name = req.name
            artifact.elements_json = json.dumps(req.elements)
            artifact.app_state_json = json.dumps(req.app_state)
            artifact.extracted_nodes_json = json.dumps(extracted_nodes)
            artifact.version += 1

        db.commit()
        db.refresh(artifact)

        # Ingest as SourceEvent + Evidence
        event_create = SourceEventCreate(
            tenant_id=tenant_id,
            project_id=project_id,
            source="excalidraw",
            source_event_id=f"excal_{artifact.id}_v{artifact.version}",
            event_type="diagram_change",
            actor_id="system_excalidraw",
            occurred_at=datetime.now(timezone.utc),
            payload={
                "artifact_id": artifact.id,
                "version": artifact.version,
                "name": artifact.name,
                "nodes": extracted_nodes,
                "element_count": len(req.elements),
                "summary": f"Excalidraw diagram '{req.name}' updated to v{artifact.version} with nodes: {', '.join(extracted_nodes)}",
            },
        )
        source_event = self.ingestion_service.ingest_event(event_create, db)
        evidence = self.ingestion_service.create_evidence_from_event(
            event=source_event,
            db=db,
            content=f"Architecture Diagram: {req.name} (v{artifact.version}). Nodes: {', '.join(extracted_nodes)}",
            metadata={"artifact_id": artifact.id, "extracted_nodes": extracted_nodes},
        )

        logger.info(f"Ingested Excalidraw diagram for project '{project_id}' as evidence '{evidence.id}'")
        return artifact, evidence

    def ingest_unassociated_diagram(
        self,
        req: ExcalidrawIngestRequest,
        db: Session,
        tenant_id: str = "default_tenant",
        actor_id: str = "system_excalidraw",
    ) -> Dict[str, Any]:
        """
        Ingests an Excalidraw diagram scene WITHOUT a trusted project binding.
        Runs it through Unified Context Intelligence to resolve project or Unknown Context.
        Never writes ambiguous information directly onto a real project's live canvas.
        """
        from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
        from app.services.source_intelligence_pipeline import SourceIntelligencePipeline

        extracted_nodes = self._extract_node_labels(req.elements)
        visual_summary = f"Excalidraw diagram '{req.name}' with components: {', '.join(extracted_nodes)}"
        pipeline = getattr(self, "pipeline", None) or SourceIntelligencePipeline()

        synthetic_event_id = f"excal_raw_{int(datetime.now().timestamp() * 1000)}"
        outcome = pipeline.process(
            source="excalidraw",
            payload={
                "name": req.name,
                "text": visual_summary,
                "extracted_nodes": extracted_nodes,
                "elements": req.elements,
                "app_state": req.app_state,
            },
            db=db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            source_event_id=synthetic_event_id,
            event_type="diagram_import",
            visual_context=visual_summary,
        )

        if outcome.outcome == "resolved" and outcome.project_id:
            resolved_proj_id = outcome.project_id
            from app.services.project_state_service import ProjectStateService
            state_svc = ProjectStateService()
            state = state_svc.get_or_create_state(resolved_proj_id, db)
            proposal = self.generate_proposal_from_state(
                project_id=resolved_proj_id,
                state_version=state.current_version,
                db=db,
                tenant_id=tenant_id,
                reason=f"Excalidraw diagram import '{req.name}'",
            )
            return {
                "status": "resolved",
                "project_id": resolved_proj_id,
                "evidence_id": outcome.evidence_id,
                "proposal_id": proposal.id if proposal else None,
                "reason": outcome.reason,
            }
        else:
            return {
                "status": "unknown_context",
                "project_id": SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
                "unknown_item_id": outcome.unknown_item_id,
                "evidence_id": outcome.evidence_id,
                "reason": outcome.reason,
            }

    def _create_semantic_visual_proposal(
        self,
        project_id: str,
        context_text: str,
        db: Session,
        tenant_id: str = "default_tenant",
        state_version: int = 1,
        reason: Optional[str] = None,
        auto_apply: bool = False,
        actor_id: str = "visual_planner",
        evidence_ids: Optional[List[str]] = None,
    ) -> tuple[ExcalidrawProposal, Optional[ExcalidrawArtifact]]:
        """Create/apply an incremental semantic visual patch.

        This is the only mutation path for project canvases. The AI emits semantic
        operations; the merge engine applies them to the existing scene. No complete
        Excalidraw scene is regenerated as an update.
        """
        from app.services.visual_patch_service import VisualPatchService
        from app.services.visual_revision_service import VisualRevisionService

        artifact = self.get_or_create_artifact(project_id, db, tenant_id=tenant_id)
        revision_service = VisualRevisionService(audit_service=self.audit_service)
        current_rev = revision_service.current_revision(project_id, db)
        current_scene = self._json_list(current_rev.scene_json) if current_rev and current_rev.scene_json else self._json_list(artifact.elements_json)

        patch_service = VisualPatchService(
            revision_service=revision_service
        )
        patch = patch_service.generate_patch_from_evidence(
            project_id=project_id,
            text=context_text,
            db=db,
            evidence_ids=evidence_ids or [],
            tenant_id=tenant_id,
        )

        merged_preview, applied_ops, conflicts = patch_service.merge_service.merge(
            base_elements=current_scene,
            user_elements=current_scene,
            patch=patch,
        )

        before_nodes = self._scene_node_labels(current_scene)
        after_nodes = self._scene_node_labels(merged_preview)
        before_ids = set(self._scene_semantic_node_ids(current_scene))
        after_ids = set(self._scene_semantic_node_ids(merged_preview))

        diff_preview = {
            "mode": "semantic_patch",
            "visual_patch": patch.model_dump(),
            "base_revision_id": current_rev.id if current_rev else None,
            "base_revision_number": current_rev.revision_number if current_rev else patch.base_revision_number,
            "merge_conflicts": conflicts,
            "applied_operations": applied_ops,
            "nodes_before": before_nodes,
            "nodes_after": after_nodes,
            "nodes_added": [x for x in after_nodes if x not in before_nodes],
            "nodes_removed": [x for x in before_nodes if x not in after_nodes],
            "semantic_nodes_added": sorted(after_ids - before_ids),
            "semantic_nodes_removed": sorted(before_ids - after_ids),
            "connections_before": self._scene_relationships(current_scene),
            "connections_after": self._scene_relationships(merged_preview),
            "safety_classification": patch.safety_classification.value,
        }

        proposal = ExcalidrawProposal(
            artifact_id=artifact.id,
            project_id=project_id,
            tenant_id=tenant_id,
            derived_from_state_version=state_version,
            status=ExcalidrawProposalStatus.PENDING.value,
            reason=reason or patch.reason or "Incremental semantic visual update",
            proposed_elements_json=json.dumps(merged_preview),
            diff_preview_json=json.dumps(diff_preview),
            evidence_ids_json=json.dumps(evidence_ids or patch.evidence_ids or []),
        )
        db.add(proposal)
        db.flush()

        should_auto_apply = (
            auto_apply
            and patch.safety_classification == PatchSafetyClassification.SAFE_AUTO_APPLY
        )
        if auto_apply and not should_auto_apply:
            proposal.reason = (
                proposal.reason
                + " [Deferred: semantic patch requires review before applying.]"
            )

        if should_auto_apply:
            revision = patch_service.apply_patch(
                project_id=project_id,
                patch=patch,
                db=db,
                actor_id=actor_id,
                tenant_id=tenant_id,
                derived_from_project_state_version=state_version,
                proposal_id=proposal.id,
            )
            proposal.status = ExcalidrawProposalStatus.APPROVED.value
            proposal.approved_at = datetime.now(timezone.utc)
            proposal.approved_by = actor_id
            proposal.proposed_elements_json = revision.scene_json
            proposal.reason = reason or patch.reason or "Incremental semantic visual update"
            db.commit()
            db.refresh(proposal)
            db.refresh(artifact)
            return proposal, artifact

        db.commit()
        db.refresh(proposal)
        return proposal, None

    def generate_proposal_from_state(
        self,
        project_id: str,
        state_version: int,
        db: Session,
        tenant_id: str = "default_tenant",
        reason: Optional[str] = None,
        auto_apply: bool = False,
        actor_id: str = "state_synchronizer",
    ) -> ExcalidrawProposal:
        """Generate an incremental semantic visual proposal from Project State."""
        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        if not state:
            raise ExcalidrawError(f"Project '{project_id}' has no ProjectState.")

        context_payload = {
            "project": state.title,
            "vision": state.vision,
            "requirements": self._json_list(state.requirements_json),
            "architecture": self._json_list(state.architecture_json),
            "decisions": self._json_list(state.decisions_json),
            "constraints": self._json_list(state.constraints_json),
            "open_questions": self._json_list(state.open_questions_json),
        }
        proposal, _artifact = self._create_semantic_visual_proposal(
            project_id=project_id,
            context_text=json.dumps(context_payload, default=str),
            db=db,
            tenant_id=tenant_id,
            state_version=state_version,
            reason=reason or f"Incrementally align visual workspace with Project State v{state_version}",
            auto_apply=auto_apply,
            actor_id=actor_id,
        )
        return proposal

    def generate_ai_visual_architecture(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        focus_prompt: Optional[str] = None,
        direct_apply: bool = True,
        actor_id: str = "visual_planner",
        visual_plan_service=None,
        context_notes: Optional[List[str]] = None,
    ) -> tuple[ExcalidrawProposal, Optional[ExcalidrawArtifact]]:
        """Generate an incremental semantic architecture update.

        The existing canvas is always the starting point. Only semantic patch
        operations produced by VisualPatchService are merged into it.
        """
        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        state_version = state.current_version if state else 1
        project_obj = db.query(Project).filter(Project.id == project_id).first()
        project_name = project_obj.name if project_obj else f"Project {project_id}"

        payload = {
            "project": project_name,
            "vision": state.vision if state else "",
            "requirements": self._json_list(state.requirements_json) if state else [],
            "architecture": self._json_list(state.architecture_json) if state else [],
            "decisions": self._json_list(state.decisions_json) if state else [],
            "constraints": self._json_list(state.constraints_json) if state else [],
            "focus": focus_prompt or "",
        }
        if context_notes:
            payload["context_notes"] = [str(x).strip() for x in context_notes if str(x).strip()][:5]

        proposal, artifact = self._create_semantic_visual_proposal(
            project_id=project_id,
            context_text=json.dumps(payload, default=str),
            db=db,
            tenant_id=tenant_id,
            state_version=state_version,
            reason=f"Incremental AI visual architecture update for {project_name}",
            auto_apply=direct_apply,
            actor_id=actor_id,
        )
        return proposal, artifact

    def generate_diagram_from_text(
        self,
        project_id: str,
        text: str,
        db: Session,
        tenant_id: str = "default_tenant",
        auto_apply: bool = True,
        actor_id: str = "synora_agent",
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Interpret text as semantic change intent and merge it incrementally."""
        if title:
            text = f"Project: {title}\n{text}"

        proposal, artifact = self._create_semantic_visual_proposal(
            project_id=project_id,
            context_text=text,
            db=db,
            tenant_id=tenant_id,
            state_version=(
                db.query(ProjectState).filter(ProjectState.project_id == project_id).first().current_version
                if db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
                else 1
            ),
            reason=f"Incremental semantic visual update from text: {text[:100]}",
            auto_apply=auto_apply,
            actor_id=actor_id,
        )
        preview = json.loads(proposal.proposed_elements_json or "[]")
        return {
            "success": True,
            "project_id": project_id,
            "artifact_version": artifact.version if artifact else None,
            "elements": preview,
            "diff_preview": json.loads(proposal.diff_preview_json or "{}"),
            "status": proposal.status,
            "auto_applied": auto_apply,
            "proposal_id": proposal.id,
            "message": "Text interpreted as a semantic patch; no full-scene regeneration was performed.",
        }

    @staticmethod
    def _scene_node_labels(scene: List[Dict[str, Any]]) -> List[str]:
        labels = []
        for el in scene:
            if not isinstance(el, dict) or el.get("semantic_type") != "node":
                continue
            sid = str(el.get("semantic_id") or el.get("id") or "")
            label_id = sid.replace("node_", "")
            labels.append(label_id.replace("_", " ").strip().title())
        return labels

    @staticmethod
    def _scene_semantic_node_ids(scene: List[Dict[str, Any]]) -> List[str]:
        ids = []
        for el in scene:
            if isinstance(el, dict) and el.get("semantic_type") == "node":
                ids.append(str(el.get("semantic_id") or el.get("id") or ""))
        return [x for x in ids if x]

    @staticmethod
    def _json_list(raw: Optional[str]) -> List[Any]:
        try:
            value = json.loads(raw) if raw else []
            return value if isinstance(value, list) else []
        except Exception:
            return []

    @staticmethod
    def _scene_relationships(scene: List[Dict[str, Any]]) -> List[str]:
        rels = []
        for el in scene:
            if isinstance(el, dict) and el.get("type") == "arrow":
                start = (el.get("startBinding") or {}).get("elementId")
                end = (el.get("endBinding") or {}).get("elementId")
                rels.append(f"{start} -> {end}")
        return rels

    def _recent_evidence_snippets(self, project_id: str, db: Session) -> List[str]:
        from app.models.evidence import Evidence

        rows = (
            db.query(Evidence)
            .filter(Evidence.project_id == project_id)
            .order_by(Evidence.created_at.desc())
            .limit(8)
            .all()
        )
        return [r.content[:200] for r in rows if r.content]

    def review_proposal(
        self,
        proposal_id: str,
        action: str,  # "approve" or "reject"
        actor_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        reason: Optional[str] = None,
    ) -> tuple[ExcalidrawProposal, Optional[ExcalidrawArtifact]]:
        """
        Human Review Gate: Approves or rejects an Excalidraw change proposal.
        Only approval commits the proposed elements to the ExcalidrawArtifact.
        """
        proposal = (
            db.query(ExcalidrawProposal)
            .filter(
                ExcalidrawProposal.id == proposal_id,
                ExcalidrawProposal.tenant_id == tenant_id,
            )
            .first()
        )
        if not proposal:
            raise ExcalidrawError(f"Proposal '{proposal_id}' not found.")

        if proposal.status != ExcalidrawProposalStatus.PENDING.value:
            raise ExcalidrawError(f"Proposal '{proposal_id}' has already been reviewed ({proposal.status}).")

        now = datetime.now(timezone.utc)
        artifact = None

        if action.lower() == "approve":
            diff_data = json.loads(proposal.diff_preview_json or "{}")
            patch_data = diff_data.get("visual_patch")
            if not patch_data:
                raise ExcalidrawError(
                    "This proposal was created by the legacy full-scene pipeline and cannot be approved. "
                    "Regenerate it through the semantic visual patch pipeline."
                )

            artifact = (
                db.query(ExcalidrawArtifact)
                .filter(ExcalidrawArtifact.id == proposal.artifact_id)
                .first()
            )
            if not artifact:
                raise ExcalidrawError(
                    f"Artifact '{proposal.artifact_id}' not found for proposal '{proposal.id}'."
                )

            from app.services.visual_patch_service import VisualPatchService
            from app.services.visual_revision_service import VisualRevisionService

            patch = VisualPatch.model_validate(patch_data)
            patch_service = VisualPatchService(
                revision_service=VisualRevisionService(audit_service=self.audit_service)
            )
            revision = patch_service.apply_patch(
                project_id=proposal.project_id,
                patch=patch,
                db=db,
                actor_id=actor_id,
                tenant_id=tenant_id,
                derived_from_project_state_version=proposal.derived_from_state_version,
                proposal_id=proposal.id,
            )

            proposal.status = ExcalidrawProposalStatus.APPROVED.value
            proposal.approved_at = now
            proposal.approved_by = actor_id
            proposal.proposed_elements_json = revision.scene_json

            self.audit_service.record_event(
                action="excalidraw_proposal_approved",
                actor_id=actor_id,
                resource_type="excalidraw_proposal",
                resource_id=proposal.id,
                db=db,
                tenant_id=tenant_id,
                after_state={
                    "status": "approved",
                    "revision_id": revision.id,
                    "revision_number": revision.revision_number,
                    "mode": "semantic_patch",
                },
            )
            logger.info(
                "Excalidraw semantic proposal '%s' approved by '%s'; revision=%d",
                proposal.id,
                actor_id,
                revision.revision_number,
            )

        elif action.lower() == "reject":
            proposal.status = ExcalidrawProposalStatus.REJECTED.value
            proposal.approved_at = now
            proposal.approved_by = actor_id
            if reason:
                proposal.reason += f" [Rejected: {reason}]"

            # Keep the semantic patch lifecycle aligned with the human review.
            try:
                from app.models.visual_patch import VisualPatchModel
                patch_data = json.loads(proposal.diff_preview_json or "{}").get("visual_patch")
                patch_id = patch_data.get("patch_id") if isinstance(patch_data, dict) else None
                if patch_id:
                    patch_model = (
                        db.query(VisualPatchModel)
                        .filter(
                            VisualPatchModel.id == patch_id,
                            VisualPatchModel.tenant_id == tenant_id,
                        )
                        .first()
                    )
                    if patch_model:
                        patch_model.status = "rejected"
            except Exception as exc:
                logger.warning("visual_patch_rejection_sync_failed: proposal=%s error=%s", proposal.id, exc)

            self.audit_service.record_event(
                action="excalidraw_proposal_rejected",
                actor_id=actor_id,
                resource_type="excalidraw_proposal",
                resource_id=proposal.id,
                db=db,
                tenant_id=tenant_id,
                after_state={"status": "rejected", "rejection_reason": reason},
            )
            logger.info(f"Excalidraw proposal '{proposal.id}' rejected by '{actor_id}'.")
        else:
            raise ExcalidrawError(f"Invalid review action '{action}'. Must be 'approve' or 'reject'.")

        db.commit()
        db.refresh(proposal)
        if artifact:
            db.refresh(artifact)

        return proposal, artifact

    def list_proposals(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        status: Optional[str] = None,
    ) -> List[ExcalidrawProposal]:
        """Lists proposals for a given project."""
        q = db.query(ExcalidrawProposal).filter(
            ExcalidrawProposal.project_id == project_id,
            ExcalidrawProposal.tenant_id == tenant_id,
        )
        if status:
            q = q.filter(ExcalidrawProposal.status == status)
        return q.order_by(ExcalidrawProposal.created_at.desc()).all()

    def propose_changes(
        self,
        project_id: str,
        suggested_elements: List[Dict[str, Any]],
        reason: str,
        db: Session,
        tenant_id: str = "default_tenant",
        evidence_ids: Optional[List[str]] = None,
        derived_from_state_version: int = 1,
    ) -> ExcalidrawProposal:
        """Reject legacy raw-scene proposals; use semantic patch generation instead."""
        raise ExcalidrawError(
            "Raw Excalidraw scene proposals are disabled. Use the semantic visual patch pipeline."
        )

    def approve_proposal(
        self,
        proposal_id: str,
        db: Session,
        actor_id: str = "reviewer",
        tenant_id: str = "default_tenant",
    ) -> Dict[str, Any]:
        proposal, artifact = self.review_proposal(
            proposal_id=proposal_id, action="approve", actor_id=actor_id, db=db, tenant_id=tenant_id
        )
        from app.services.visual_revision_service import VisualRevisionService
        rev = VisualRevisionService().current_revision(proposal.project_id, db)
        return {
            "status": "approved",
            "proposal_id": proposal.id,
            "revision_number": rev.revision_number if rev else (artifact.version if artifact else 1),
        }

    def reject_proposal(
        self,
        proposal_id: str,
        db: Session,
        actor_id: str = "reviewer",
        tenant_id: str = "default_tenant",
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        proposal, artifact = self.review_proposal(
            proposal_id=proposal_id, action="reject", actor_id=actor_id, db=db, tenant_id=tenant_id, reason=note
        )
        return {"status": "rejected", "proposal_id": proposal.id}

    def _extract_node_labels(self, elements: List[Dict[str, Any]]) -> List[str]:
        """Extracts readable node labels from Excalidraw elements."""
        labels = []
        for el in elements:
            if el.get("type") == "text":
                text = el.get("text", "").strip()
                if text and text not in labels:
                    labels.append(text)
        return labels

    def _normalize_element(self, el: Dict[str, Any], idx: int = 1) -> Dict[str, Any]:
        """Ensures an Excalidraw element contains all standard properties required by Excalidraw renderers."""
        el_type = str(el.get("type", "rectangle"))
        w = el.get("width")
        h = el.get("height")
        if el_type in ("arrow", "line"):
            width = float(w) if isinstance(w, (int, float)) else 0.0
            height = float(h) if isinstance(h, (int, float)) else 0.0
        else:
            width = float(w) if isinstance(w, (int, float)) and w > 0 else (120.0 if el_type == "text" else 160.0)
            height = float(h) if isinstance(h, (int, float)) and h > 0 else (24.0 if el_type == "text" else 70.0)

        x_val = el.get("x")
        y_val = el.get("y")
        x = float(x_val) if isinstance(x_val, (int, float)) else 0.0
        y = float(y_val) if isinstance(y_val, (int, float)) else 0.0

        defaults = {
            "type": el_type,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "seed": 100000 + idx,
            "version": 1,
            "versionNonce": 1,
            "isDeleted": False,
            "boundElements": None,
            "updated": 1,
            "link": None,
            "locked": False,
        }
        res = dict(defaults)
        res.update(el)
        res["x"] = x
        res["y"] = y
        res["width"] = width
        res["height"] = height
        r = res.get("roundness")
        if r is not None and (not isinstance(r, dict) or "type" not in r):
            res["roundness"] = None
        return res

    def _build_ai_architecture_scene(
        self,
        project_name: str,
        workflow_nodes: List[str],
        decisions: Optional[List[Dict[str, Any]]] = None,
        requirements: Optional[List[Dict[str, Any]]] = None,
        focus_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        AI Visual Architecture Scene Compiler:
        Produces a rich, multi-tier system architecture diagram for Excalidraw,
        complete with presentation tier, core AI workforce, persistence layers,
        connected directional flow arrows, and living decision/requirement sticky cards.
        """
        raw_elements: List[Dict[str, Any]] = []

        # 0. Modern Banner Header
        raw_elements.append({
            "id": "banner_ai_box",
            "type": "rectangle",
            "x": 80,
            "y": 40,
            "width": 1180,
            "height": 55,
            "backgroundColor": "#1e1b4b",
            "strokeColor": "#4338ca",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "roundness": {"type": 3},
            "roughness": 1,
        })
        title_text = f"📐 {project_name.upper()} SYSTEM ARCHITECTURE • LIVING EXCALIDRAW BLUEPRINT"
        raw_elements.append({
            "id": "banner_ai_title",
            "type": "text",
            "x": 100,
            "y": 48,
            "width": 1140,
            "height": 24,
            "text": title_text,
            "fontSize": 15,
            "fontFamily": 1,
            "strokeColor": "#ffffff",
            "textAlign": "left",
            "containerId": "banner_ai_box",
        })
        sub_text = "ONE SHARED SYNORA AGENT • DETERMINISTIC GUARDRAILS • POSTGRESQL SYSTEM OF RECORD"
        if focus_prompt:
            sub_text += f" • FOCUS: {focus_prompt.upper()}"
        raw_elements.append({
            "id": "banner_ai_sub",
            "type": "text",
            "x": 100,
            "y": 72,
            "width": 1140,
            "height": 18,
            "text": sub_text,
            "fontSize": 10,
            "fontFamily": 1,
            "strokeColor": "#c7d2fe",
            "textAlign": "left",
            "containerId": "banner_ai_box",
        })

        # 1. Tier 1: Presentation & Ingress Zone
        t1_x, t1_y, t1_w, t1_h = 80, 115, 1180, 160
        raw_elements.append({
            "id": "zone_t1_box",
            "type": "rectangle",
            "x": t1_x,
            "y": t1_y,
            "width": t1_w,
            "height": t1_h,
            "backgroundColor": "#f5f3ff",
            "strokeColor": "#818cf8",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "dashed",
            "roundness": {"type": 3},
            "roughness": 1,
        })
        raw_elements.append({
            "id": "zone_t1_title",
            "type": "text",
            "x": t1_x + 15,
            "y": t1_y + 10,
            "width": 450,
            "height": 20,
            "text": "TIER 1: PRESENTATION & MULTI-CHANNEL INGESTION",
            "fontSize": 12,
            "fontFamily": 1,
            "strokeColor": "#4f46e5",
            "textAlign": "left",
        })

        t1_components = [
            ("comp_web_app", "🖥️ Next.js 15 Web Client\nReact 19 • Canvas UI\nState & Approval Console", "#e0e7ff", "#4338ca"),
            ("comp_meet_ingest", "📹 Google Meet Ingestor\nCloud REST v2 • Pub/Sub\nTranscript Synchronization", "#fee2e2", "#dc2626"),
            ("comp_wa_gateway", "💬 WhatsApp Gateway\nBaileys WebSockets\nNatural ChatOps & Alerts", "#dcfce7", "#16a34a"),
            ("comp_slack_bot", "⚡ Slack Events Bot\nSlack Events API\nHandoff Webhooks & Context", "#fef3c7", "#d97706"),
        ]
        card_w = 265
        card_spacing = 25
        start_cx = t1_x + 25
        card_y = t1_y + 38
        card_h = 100

        for idx, (cid, ctext, bg_col, strk_col) in enumerate(t1_components):
            cx = start_cx + idx * (card_w + card_spacing)
            raw_elements.append({
                "id": cid,
                "type": "rectangle",
                "x": cx,
                "y": card_y,
                "width": card_w,
                "height": card_h,
                "backgroundColor": bg_col,
                "strokeColor": strk_col,
                "fillStyle": "solid",
                "strokeWidth": 2,
                "roundness": {"type": 3},
                "roughness": 1,
            })
            raw_elements.append({
                "id": f"{cid}_txt",
                "type": "text",
                "x": cx + 12,
                "y": card_y + 15,
                "width": card_w - 24,
                "height": card_h - 30,
                "text": ctext,
                "fontSize": 12,
                "fontFamily": 1,
                "strokeColor": "#0f172a",
                "textAlign": "left",
                "containerId": cid,
            })

        # 2. Tier 2: Synora Agent Intelligence & Deterministic Pipeline
        t2_x, t2_y, t2_w, t2_h = 80, 310, 1180, 200
        raw_elements.append({
            "id": "zone_t2_box",
            "type": "rectangle",
            "x": t2_x,
            "y": t2_y,
            "width": t2_w,
            "height": t2_h,
            "backgroundColor": "#ecfdf5",
            "strokeColor": "#10b981",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "dashed",
            "roundness": {"type": 3},
            "roughness": 1,
        })
        raw_elements.append({
            "id": "zone_t2_title",
            "type": "text",
            "x": t2_x + 15,
            "y": t2_y + 10,
            "width": 500,
            "height": 20,
            "text": "TIER 2: SYNORA AGENT INTELLIGENCE & DETERMINISTIC PIPELINE",
            "fontSize": 12,
            "fontFamily": 1,
            "strokeColor": "#059669",
            "textAlign": "left",
        })

        t2_components = [
            ("comp_fastapi_core", "⚙️ FastAPI Application Core\nPython 3.11 • REST / SSE\nProject Context & RBAC Boundary", "#d1fae5", "#059669"),
            ("comp_synora_agent", "🧠 One Shared Synora Agent\nUnified Intelligence Layer\nReasoning Across Project Context", "#e0f2fe", "#0284c7"),
            ("comp_capabilities", "⚡ Internal Capabilities\nBA • Planning • Functional\nTech Architecture • Frappe", "#fce7f3", "#db2777"),
            ("comp_guardrails", "🛡️ Deterministic Guardrails\nVerification & Synthesis\nConflict Detection & Safe Gating", "#ffedd5", "#ea580c"),
        ]
        card_y2 = t2_y + 40
        card_h2 = 135

        for idx, (cid, ctext, bg_col, strk_col) in enumerate(t2_components):
            cx = start_cx + idx * (card_w + card_spacing)
            raw_elements.append({
                "id": cid,
                "type": "rectangle",
                "x": cx,
                "y": card_y2,
                "width": card_w,
                "height": card_h2,
                "backgroundColor": bg_col,
                "strokeColor": strk_col,
                "fillStyle": "solid",
                "strokeWidth": 2,
                "roundness": {"type": 3},
                "roughness": 1,
            })
            raw_elements.append({
                "id": f"{cid}_txt",
                "type": "text",
                "x": cx + 12,
                "y": card_y2 + 15,
                "width": card_w - 24,
                "height": card_h2 - 30,
                "text": ctext,
                "fontSize": 12,
                "fontFamily": 1,
                "strokeColor": "#0f172a",
                "textAlign": "left",
                "containerId": cid,
            })

        # Connectors from Tier 1 to Tier 2
        raw_elements.append({
            "id": "arr_web_to_api",
            "type": "arrow",
            "x": start_cx + card_w / 2,
            "y": card_y + card_h,
            "width": 0,
            "height": card_y2 - (card_y + card_h),
            "points": [[0, 0], [0, card_y2 - (card_y + card_h)]],
            "endArrowhead": "arrow",
            "strokeColor": "#64748b",
            "strokeWidth": 2,
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arr_meet_to_api",
            "type": "arrow",
            "x": start_cx + card_w + card_spacing + card_w / 2,
            "y": card_y + card_h,
            "width": -(card_w + card_spacing) / 2,
            "height": card_y2 - (card_y + card_h),
            "points": [[0, 0], [-(card_w + card_spacing) / 2, card_y2 - (card_y + card_h)]],
            "endArrowhead": "arrow",
            "strokeColor": "#dc2626",
            "strokeWidth": 2,
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arr_wa_to_api",
            "type": "arrow",
            "x": start_cx + 2 * (card_w + card_spacing) + card_w / 2,
            "y": card_y + card_h,
            "width": -(card_w + card_spacing),
            "height": card_y2 - (card_y + card_h),
            "points": [[0, 0], [-(card_w + card_spacing), card_y2 - (card_y + card_h)]],
            "endArrowhead": "arrow",
            "strokeColor": "#16a34a",
            "strokeWidth": 2,
            "roughness": 1,
        })

        # Inter-Tier 2 Connectors
        raw_elements.append({
            "id": "arr_api_to_agent",
            "type": "arrow",
            "x": start_cx + card_w,
            "y": card_y2 + card_h2 / 2,
            "width": card_spacing,
            "height": 0,
            "points": [[0, 0], [card_spacing, 0]],
            "endArrowhead": "arrow",
            "strokeColor": "#0284c7",
            "strokeWidth": 2,
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arr_agent_to_caps",
            "type": "arrow",
            "x": start_cx + card_w + card_spacing + card_w,
            "y": card_y2 + card_h2 / 2,
            "width": card_spacing,
            "height": 0,
            "points": [[0, 0], [card_spacing, 0]],
            "endArrowhead": "arrow",
            "strokeColor": "#db2777",
            "strokeWidth": 2,
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arr_caps_to_guardrails",
            "type": "arrow",
            "x": start_cx + 2 * (card_w + card_spacing) + card_w,
            "y": card_y2 + card_h2 / 2,
            "width": card_spacing,
            "height": 0,
            "points": [[0, 0], [card_spacing, 0]],
            "endArrowhead": "arrow",
            "strokeColor": "#ea580c",
            "strokeWidth": 2,
            "roughness": 1,
        })

        # 3. Tier 3: Persistence & Authoritative State
        t3_x, t3_y, t3_w, t3_h = 80, 545, 1180, 160
        raw_elements.append({
            "id": "zone_t3_box",
            "type": "rectangle",
            "x": t3_x,
            "y": t3_y,
            "width": t3_w,
            "height": t3_h,
            "backgroundColor": "#fffbeb",
            "strokeColor": "#f59e0b",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "dashed",
            "roundness": {"type": 3},
            "roughness": 1,
        })
        raw_elements.append({
            "id": "zone_t3_title",
            "type": "text",
            "x": t3_x + 15,
            "y": t3_y + 10,
            "width": 550,
            "height": 20,
            "text": "TIER 3: PERSISTENCE, EVIDENCE PROVENANCE & AUDIT TRAIL",
            "fontSize": 12,
            "fontFamily": 1,
            "strokeColor": "#b45309",
            "textAlign": "left",
        })

        t3_components = [
            ("comp_db_sor", "🗄️ Database System of Record\nPostgreSQL / SQLite • SQLAlchemy\nAuthoritative State & Version History", "#fef3c7", "#d97706"),
            ("comp_evidence_store", "📜 Immutable Evidence Store\nMeeting Transcripts & Events\nVerbatim Text & Audit Lineage", "#e2e8f0", "#475569"),
            ("comp_excal_store", "🎨 Living Excalidraw Store\nOpen Schema (application/vnd.excalidraw+json)\nHuman Approval Gates & Diff History", "#ede9fe", "#7c3aed"),
        ]
        card_w3 = 360
        spacing3 = 30
        card_y3 = t3_y + 38
        card_h3 = 100

        for idx, (cid, ctext, bg_col, strk_col) in enumerate(t3_components):
            cx = start_cx + idx * (card_w3 + spacing3)
            raw_elements.append({
                "id": cid,
                "type": "rectangle",
                "x": cx,
                "y": card_y3,
                "width": card_w3,
                "height": card_h3,
                "backgroundColor": bg_col,
                "strokeColor": strk_col,
                "fillStyle": "solid",
                "strokeWidth": 2,
                "roundness": {"type": 3},
                "roughness": 1,
            })
            raw_elements.append({
                "id": f"{cid}_txt",
                "type": "text",
                "x": cx + 15,
                "y": card_y3 + 18,
                "width": card_w3 - 30,
                "height": card_h3 - 36,
                "text": ctext,
                "fontSize": 12,
                "fontFamily": 1,
                "strokeColor": "#0f172a",
                "textAlign": "left",
                "containerId": cid,
            })

        # Downward arrows from Tier 2 to Tier 3
        raw_elements.append({
            "id": "arr_api_to_db",
            "type": "arrow",
            "x": start_cx + card_w / 2,
            "y": card_y2 + card_h2,
            "width": 0,
            "height": card_y3 - (card_y2 + card_h2),
            "points": [[0, 0], [0, card_y3 - (card_y2 + card_h2)]],
            "endArrowhead": "arrow",
            "strokeColor": "#d97706",
            "strokeWidth": 2,
            "roughness": 1,
        })
        raw_elements.append({
            "id": "arr_agent_to_excal",
            "type": "arrow",
            "x": start_cx + card_w + card_spacing + card_w / 2,
            "y": card_y2 + card_h2,
            "width": 300,
            "height": card_y3 - (card_y2 + card_h2),
            "points": [[0, 0], [300, card_y3 - (card_y2 + card_h2)]],
            "endArrowhead": "arrow",
            "strokeColor": "#7c3aed",
            "strokeWidth": 2,
            "roughness": 1,
        })

        # 4. Key Decisions & Evidence Provenance Cards Section
        dec_y = 735
        raw_elements.append({
            "id": "lbl_dec_ai_hdr",
            "type": "text",
            "x": 80,
            "y": dec_y,
            "width": 550,
            "height": 26,
            "text": "KEY ARCHITECTURAL DECISIONS & EVIDENCE CITATIONS",
            "fontSize": 14,
            "fontFamily": 1,
            "strokeColor": "#15803d",
            "textAlign": "left",
        })

        dec_list = decisions or []
        if not dec_list:
            dec_list = [
                {"title": "Adopt DeepSeek on NVIDIA NIM", "source": "Architecture Review", "evidence_ref": "EV-DEC-001"},
                {"title": "One Project = One Project Agent Context", "source": "Core Principle", "evidence_ref": "EV-DEC-002"},
                {"title": "Non-Destructive Proposal Gating", "source": "Safety Standard", "evidence_ref": "EV-DEC-003"},
                {"title": "Multi-Channel Baileys WhatsApp Gateway", "source": "Integration Spec", "evidence_ref": "EV-DEC-004"},
            ]

        dec_card_w = 270
        dec_card_h = 105
        dec_spacing = 20
        for idx, d in enumerate(dec_list[:4]):
            dx = 80 + idx * (dec_card_w + dec_spacing)
            dy = dec_y + 32
            d_title = d.get("title") or d.get("decision") or d.get("text") or f"Decision #{idx+1}"
            d_source = d.get("source", "Meeting / Chat")
            ev_ref = d.get("evidence_ref") or d.get("evidence_id")
            if not ev_ref and d.get("evidence_ids"):
                ev_ids = d.get("evidence_ids")
                ev_ref = ev_ids[0] if isinstance(ev_ids, list) and ev_ids else str(ev_ids)
            ev_ref = ev_ref or f"EV-{idx+1}"

            card_id = f"ai_dec_box_{idx+1}"
            raw_elements.append({
                "id": card_id,
                "type": "rectangle",
                "x": dx,
                "y": dy,
                "width": dec_card_w,
                "height": dec_card_h,
                "backgroundColor": "#dcfce7",
                "strokeColor": "#16a34a",
                "fillStyle": "solid",
                "strokeWidth": 2,
                "roundness": {"type": 3},
                "roughness": 1,
            })
            raw_elements.append({
                "id": f"ai_dec_txt_{idx+1}",
                "type": "text",
                "x": dx + 12,
                "y": dy + 12,
                "width": dec_card_w - 24,
                "height": dec_card_h - 24,
                "text": f"DECISION\n{d_title}\n\nSource: {d_source}\nEvidence: {ev_ref}",
                "fontSize": 11,
                "fontFamily": 1,
                "strokeColor": "#14532d",
                "textAlign": "left",
                "containerId": card_id,
            })

        # 5. Active Requirements & Scope Section
        req_y = 895
        raw_elements.append({
            "id": "lbl_req_ai_hdr",
            "type": "text",
            "x": 80,
            "y": req_y,
            "width": 500,
            "height": 26,
            "text": "ACTIVE REQUIREMENTS & SCOPE BOUNDARIES",
            "fontSize": 14,
            "fontFamily": 1,
            "strokeColor": "#1d4ed8",
            "textAlign": "left",
        })

        req_list = requirements or []
        if not req_list:
            req_list = [
                {"title": "Zero LLM Hallucinations on Project State"},
                {"title": "Strict Human Approval for Diagram Mutations"},
                {"title": "Bi-directional Excalidraw JSON Sync"},
                {"title": "Sub-Second Extraction with Flash Model"},
            ]

        for idx, r in enumerate(req_list[:4]):
            rx = 80 + idx * (dec_card_w + dec_spacing)
            ry = req_y + 32
            r_title = r.get("title") or r.get("requirement") or r.get("text") or f"Requirement #{idx+1}"
            r_id = f"ai_req_box_{idx+1}"
            raw_elements.append({
                "id": r_id,
                "type": "rectangle",
                "x": rx,
                "y": ry,
                "width": dec_card_w,
                "height": 85,
                "backgroundColor": "#eff6ff",
                "strokeColor": "#3b82f6",
                "fillStyle": "solid",
                "strokeWidth": 2,
                "roundness": {"type": 3},
                "roughness": 1,
            })
            raw_elements.append({
                "id": f"ai_req_txt_{idx+1}",
                "type": "text",
                "x": rx + 12,
                "y": ry + 12,
                "width": dec_card_w - 24,
                "height": 60,
                "text": f"REQUIREMENT\n{r_title}",
                "fontSize": 11,
                "fontFamily": 1,
                "strokeColor": "#1e3a8a",
                "textAlign": "left",
                "containerId": r_id,
            })

        return [self._normalize_element(el, idx=i) for i, el in enumerate(raw_elements, 1)]

    def _build_living_workspace_elements(
        self,
        node_names: List[str],
        decisions: Optional[List[Dict[str, Any]]] = None,
        requirements: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Builds project workspace cards for decisions and requirements.
        Zero predefined template diagram - only renders actual project artifacts.
        """
        raw_elements: List[Dict[str, Any]] = []

        decisions_list = decisions or []
        card_start_y = 40
        if decisions_list:
            dec_y = card_start_y
            raw_elements.append({
                "id": "lbl_decisions_header",
                "type": "text",
                "x": 80,
                "y": dec_y,
                "width": 450,
                "height": 24,
                "text": "KEY PROJECT DECISIONS & EVIDENCE PROVENANCE",
                "fontSize": 14,
                "fontFamily": 1,
                "strokeColor": "#15803d",
                "textAlign": "left",
            })

            card_x = 80
            for idx, d in enumerate(decisions_list[:4]):  # Show up to 4 recent decisions
                d_title = d.get("title") or d.get("decision") or d.get("text") or f"Decision #{idx+1}"
                d_source = d.get("source", "Google Meet")
                evidence_val = d.get("evidence_ref") or d.get("evidence_id")
                if not evidence_val and d.get("evidence_ids"):
                    ev_ids = d.get("evidence_ids")
                    if isinstance(ev_ids, list) and len(ev_ids) > 0:
                        evidence_val = ev_ids[0]
                    elif isinstance(ev_ids, str):
                        evidence_val = ev_ids
                d_evidence = evidence_val or f"EV-MEET-{idx+1}"
                card_id = f"dec_box_{idx+1}"
                text_id = f"dec_txt_{idx+1}"

                # Decision Card Rectangle
                raw_elements.append({
                    "id": card_id,
                    "type": "rectangle",
                    "x": card_x,
                    "y": dec_y + 30,
                    "width": 225,
                    "height": 115,
                    "backgroundColor": "#dcfce7",
                    "strokeColor": "#16a34a",
                    "fillStyle": "solid",
                    "strokeWidth": 2,
                    "roundness": {"type": 3},
                    "roughness": 1,
                })

                # Card Text
                card_body = f"DECISION\n{d_title}\n\nSOURCE: {d_source}\nEVIDENCE: {d_evidence}"
                raw_elements.append({
                    "id": text_id,
                    "type": "text",
                    "x": card_x + 10,
                    "y": dec_y + 40,
                    "width": 205,
                    "height": 95,
                    "text": card_body,
                    "fontSize": 10,
                    "fontFamily": 1,
                    "strokeColor": "#14532d",
                    "textAlign": "left",
                    "containerId": card_id,
                })
                card_x += 245
            card_start_y += 180

        # Active Requirements Cards
        reqs_list = requirements or []
        if reqs_list:
            req_y = card_start_y
            raw_elements.append({
                "id": "lbl_reqs_header",
                "type": "text",
                "x": 80,
                "y": req_y,
                "width": 350,
                "height": 24,
                "text": "ACTIVE REQUIREMENTS & SCOPE",
                "fontSize": 14,
                "fontFamily": 1,
                "strokeColor": "#1d4ed8",
                "textAlign": "left",
            })

            req_x = 80
            for idx, r in enumerate(reqs_list[:4]):
                r_title = r.get("title") or r.get("requirement") or r.get("text") or f"Requirement #{idx+1}"
                r_id = f"req_box_{idx+1}"
                r_txt_id = f"req_txt_{idx+1}"

                raw_elements.append({
                    "id": r_id,
                    "type": "rectangle",
                    "x": req_x,
                    "y": req_y + 30,
                    "width": 225,
                    "height": 85,
                    "backgroundColor": "#eff6ff",
                    "strokeColor": "#3b82f6",
                    "fillStyle": "solid",
                    "strokeWidth": 2,
                    "roundness": {"type": 3},
                    "roughness": 1,
                })

                raw_elements.append({
                    "id": r_txt_id,
                    "type": "text",
                    "x": req_x + 10,
                    "y": req_y + 40,
                    "width": 205,
                    "height": 65,
                    "text": f"REQUIREMENT\n{r_title}",
                    "fontSize": 10,
                    "fontFamily": 1,
                    "strokeColor": "#1e3a8a",
                    "textAlign": "left",
                    "containerId": r_id,
                })
                req_x += 245

        # Normalize all elements with standard Excalidraw attributes
        return [self._normalize_element(el, idx=i) for i, el in enumerate(raw_elements, 1)]

    def _build_flow_elements(
        self,
        node_names: List[str],
        start_x: int = 100,
        start_y: int = 150,
    ) -> List[Dict[str, Any]]:
        """Generates standard Excalidraw elements representing a linear pipeline flow."""
        elements: List[Dict[str, Any]] = []
        node_width = 160
        node_height = 60
        spacing = 90

        colors = ["#e0e7ff", "#fef3c7", "#d1fae5", "#fce7f3", "#ede9fe", "#e0f2fe"]

        for i, name in enumerate(node_names):
            x = start_x + i * (node_width + spacing)
            y = start_y
            color = colors[i % len(colors)]
            node_id = f"node_{i+1}"
            text_id = f"text_{i+1}"

            # Box element
            elements.append({
                "id": node_id,
                "type": "rectangle",
                "x": x,
                "y": y,
                "width": node_width,
                "height": node_height,
                "backgroundColor": color,
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "solid",
                "roundness": {"type": 3},
                "roughness": 1,
            })

            # Text label element
            elements.append({
                "id": text_id,
                "type": "text",
                "x": x + 15,
                "y": y + 20,
                "width": node_width - 30,
                "height": 25,
                "text": name,
                "fontSize": 14,
                "fontFamily": 1,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": node_id,
            })

            # Arrow to next node
            if i < len(node_names) - 1:
                arrow_id = f"arrow_{i+1}_{i+2}"
                next_x = x + node_width + spacing
                elements.append({
                    "id": arrow_id,
                    "type": "arrow",
                    "x": x + node_width,
                    "y": y + (node_height / 2),
                    "width": spacing,
                    "height": 0,
                    "points": [[0, 0], [spacing, 0]],
                    "endArrowhead": "arrow",
                    "strokeWidth": 2,
                    "roughness": 1,
                })

        return elements

    def format_artifact_read(self, artifact: ExcalidrawArtifact) -> ExcalidrawArtifactRead:
        """Converts model to typed DTO."""
        elements = json.loads(artifact.elements_json) if artifact.elements_json else []
        app_state = json.loads(artifact.app_state_json) if artifact.app_state_json else {}
        nodes = json.loads(artifact.extracted_nodes_json) if artifact.extracted_nodes_json else []

        return ExcalidrawArtifactRead(
            id=artifact.id,
            project_id=artifact.project_id,
            tenant_id=artifact.tenant_id,
            name=artifact.name,
            version=artifact.version,
            elements=elements,
            app_state=app_state,
            extracted_nodes=nodes,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
        )

    def format_proposal_read(self, proposal: ExcalidrawProposal) -> ExcalidrawProposalRead:
        """Converts proposal model to typed DTO."""
        diff_data = json.loads(proposal.diff_preview_json) if proposal.diff_preview_json else {}
        proposed_elements = json.loads(proposal.proposed_elements_json) if proposal.proposed_elements_json else []
        evidence_ids = json.loads(proposal.evidence_ids_json) if proposal.evidence_ids_json else []

        return ExcalidrawProposalRead(
            id=proposal.id,
            artifact_id=proposal.artifact_id,
            project_id=proposal.project_id,
            tenant_id=proposal.tenant_id,
            derived_from_state_version=proposal.derived_from_state_version,
            status=proposal.status,
            reason=proposal.reason,
            diff_preview=ExcalidrawDiffPreview(
                nodes_before=diff_data.get("nodes_before", []),
                nodes_after=diff_data.get("nodes_after", []),
                nodes_added=diff_data.get("nodes_added", []),
                nodes_removed=diff_data.get("nodes_removed", []),
                connections_before=diff_data.get("connections_before", []),
                connections_after=diff_data.get("connections_after", []),
            ),
            proposed_elements=proposed_elements,
            evidence_ids=evidence_ids,
            created_at=proposal.created_at,
            approved_at=proposal.approved_at,
            approved_by=proposal.approved_by,
        )
