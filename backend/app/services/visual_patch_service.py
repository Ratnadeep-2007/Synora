from datetime import datetime, timezone
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.project_state import ProjectState
from app.models.visual_patch import VisualPatchModel
from app.models.visual_revision import VisualRevision
from app.schemas.visual_patch import (
    PatchSafetyClassification,
    VisualNoteCategory,
    VisualPatch,
    VisualPatchOpType,
    VisualPatchOperation,
    make_stable_semantic_id,
)
from app.services.llm import LLMClient, get_default_llm_client
from app.services.visual_merge_service import VisualMergeService
from app.services.visual_revision_service import VisualRevisionService

logger = logging.getLogger(__name__)


class VisualPatchService:
    """Enterprise semantic visual patch synthesizer and applier.

    Translates incoming evidence into high-level semantic patch intent (ADD_NODE,
    ADD_EDGE, ADD_NOTE) and applies them through the Three-Way Visual Merge engine.
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        merge_service: Optional[VisualMergeService] = None,
        revision_service: Optional[VisualRevisionService] = None,
    ):
        self.llm_client = llm_client or get_default_llm_client()
        self.merge_service = merge_service or VisualMergeService()
        self.revision_service = revision_service or VisualRevisionService()

    def generate_patch_from_evidence(
        self,
        project_id: str,
        text: str,
        db: Session,
        evidence_ids: Optional[List[str]] = None,
        tenant_id: str = "default_tenant",
    ) -> VisualPatch:
        """Synthesize a semantic VisualPatch from evidence dialogue."""
        patch_id = f"vpatch_{uuid.uuid4().hex[:10]}"
        current_rev = self.revision_service.current_revision(project_id, db)
        base_rev_num = current_rev.revision_number if current_rev else 0

        # Extract project state context for domain consistency
        state_row = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        state_summary = {}
        if state_row and state_row.state_json:
            try:
                state_summary = json.loads(state_row.state_json)
            except Exception:
                pass

        # Call reasoning engine to generate patch operations
        operations, safety, reason = self._synthesize_operations(project_id, text, state_summary, current_rev)

        patch = VisualPatch(
            patch_id=patch_id,
            project_id=project_id,
            base_revision_number=base_rev_num,
            operations=operations,
            safety_classification=safety,
            reason=reason or f"Semantic update from evidence: {text[:60]}",
            evidence_ids=evidence_ids or [],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # Record persistent audit row
        patch_model = VisualPatchModel(
            id=patch_id,
            project_id=project_id,
            tenant_id=tenant_id,
            base_revision_id=current_rev.id if current_rev else None,
            operations_json=json.dumps([op.model_dump() for op in operations]),
            status="proposed",
            safety_classification=safety.value,
            reason=patch.reason,
            source_evidence_ids_json=json.dumps(evidence_ids or []),
            created_at=datetime.now(timezone.utc),
        )
        db.add(patch_model)
        db.commit()

        logger.info(
            "visual_patch_synthesized: patch=%s project=%s ops=%d safety=%s",
            patch_id,
            project_id,
            len(operations),
            safety.value,
        )
        return patch

    def _synthesize_operations(
        self,
        project_id: str,
        text: str,
        state: Dict[str, Any],
        current_rev: Optional[VisualRevision],
    ) -> Tuple[List[VisualPatchOperation], PatchSafetyClassification, str]:
        """Create semantic visual updates while preserving the authored canvas.

        Deliberately domain-neutral: operations are derived from the incoming
        evidence text itself, never from hardcoded per-domain templates.
        Domain templates once drew a restaurant ordering flow ("Table QR
        Ordering", "POS Integration") onto an unrelated hospital project,
        because the evidence mentioned a QR code and the words "live
        position" contain the substring "pos". Verified live 2026-10-08.
        The LLM planner path remains the route for rich domain modelling;
        this deterministic path records what was said, nothing more.
        """
        ops: List[VisualPatchOperation] = []

        def add_note(note_key: str, category: VisualNoteCategory, content: str) -> None:
            ops.append(
                VisualPatchOperation(
                    op_type=VisualPatchOpType.ADD_NOTE,
                    target_id=make_stable_semantic_id("note", note_key),
                    category=category,
                    content=content[:180],
                )
            )

        sentences = [
            s.strip()
            for s in re.split(r"[.!?]+", text or "")
            if len(s.strip()) >= 15
        ]
        for sentence in sentences[:3]:
            clean_title = " ".join(sentence.split())[:42].strip()
            node_id = make_stable_semantic_id("node", clean_title or "Context Update")
            ops.append(
                VisualPatchOperation(
                    op_type=VisualPatchOpType.ADD_NODE,
                    target_id=node_id,
                    label=clean_title or "Context Update",
                    node_type="service",
                    emphasis="normal",
                )
            )

        if not ops:
            clean_title = " ".join((text or "").split())[:42].strip()
            node_id = make_stable_semantic_id("node", clean_title or "Context Update")
            ops.append(
                VisualPatchOperation(
                    op_type=VisualPatchOpType.ADD_NODE,
                    target_id=node_id,
                    label=clean_title or "Context Update",
                    node_type="service",
                    emphasis="normal",
                )
            )
        add_note(
            "evidence_context",
            VisualNoteCategory.ACTION,
            f"Incoming project evidence: {(text or '')[:150]}",
        )

        has_remove = any(
            op.op_type in (VisualPatchOpType.REMOVE_NODE, VisualPatchOpType.REMOVE_GROUP)
            for op in ops
        )
        safety = (
            PatchSafetyClassification.REVIEW_REQUIRED
            if has_remove
            else PatchSafetyClassification.SAFE_AUTO_APPLY
        )
        reason = f"Derived {len(ops)} semantic visual operations from evidence."
        return ops, safety, reason

    def apply_patch(
        self,
        project_id: str,
        patch: VisualPatch,
        db: Session,
        actor_id: str = "system",
        tenant_id: str = "default_tenant",
        user_scene_override: Optional[List[Dict[str, Any]]] = None,
    ) -> VisualRevision:
        """Apply patch to the current visual scene and commit a new immutable VisualRevision."""
        current_rev = self.revision_service.current_revision(project_id, db)
        base_elements = []
        if current_rev and current_rev.scene_json:
            try:
                base_elements = json.loads(current_rev.scene_json)
            except Exception:
                pass

        user_elements = user_scene_override if user_scene_override is not None else base_elements
        merged_scene, applied_ops, conflicts = self.merge_service.merge(
            base_elements=base_elements,
            user_elements=user_elements,
            patch=patch,
        )

        app_state = {}
        if current_rev and current_rev.app_state_json:
            try:
                app_state = json.loads(current_rev.app_state_json)
            except Exception:
                pass

        # Commit new immutable revision
        new_rev = self.revision_service.commit_revision(
            project_id=project_id,
            scene=merged_scene,
            db=db,
            tenant_id=tenant_id,
            app_state=app_state,
            operations=applied_ops,
            evidence_ids=patch.evidence_ids,
            actor_id=actor_id,
            reason=patch.reason or f"Applied visual patch {patch.patch_id}",
        )

        # Update patch model status
        patch_model = db.query(VisualPatchModel).filter(VisualPatchModel.id == patch.patch_id).first()
        if patch_model:
            patch_model.status = "applied"
            patch_model.target_revision_id = new_rev.id
            db.commit()

        logger.info(
            "visual_patch_applied: patch=%s project=%s new_rev=%d elements=%d",
            patch.patch_id,
            project_id,
            new_rev.revision_number,
            len(merged_scene),
        )
        return new_rev
