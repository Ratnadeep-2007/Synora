from datetime import datetime, timezone
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
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


class VisualPatchIntent(BaseModel):
    """LLM-generated semantic intent; contains no raw Excalidraw geometry."""
    operations: List[VisualPatchOperation] = Field(default_factory=list)
    context_notes: List[str] = Field(
        default_factory=list,
        description="0-5 concise synthesized project-context cards; never a transcript.",
    )
    safety_classification: PatchSafetyClassification = PatchSafetyClassification.REVIEW_REQUIRED
    reason: str = ""


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

        # Preserve each incoming conversation as its own immutable visual note.
        # Use evidence identity when available so replaying the same evidence is idempotent.
        conversation_key = (evidence_ids or [text])[-1]
        conversation_note_id = make_stable_semantic_id(
            "conversation_note",
            str(conversation_key),
        )
        conversation_note = VisualPatchOperation(
            op_type=VisualPatchOpType.ADD_NOTE,
            target_id=conversation_note_id,
            category=VisualNoteCategory.PROJECT_CONTEXT,
            content=f"PROJECT CONTEXT\n{text[:650].strip()}",
            evidence_ids=list(evidence_ids or []),
        )
        operations = [conversation_note] + operations

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
    ) -> Tuple[List[VisualPatchOperation], List[str], PatchSafetyClassification, str]:
        """Generate semantic operations with the configured reasoning model."""
        existing_elements: List[Dict[str, Any]] = []
        if current_rev and current_rev.scene_json:
            try:
                raw = json.loads(current_rev.scene_json)
                existing_elements = raw if isinstance(raw, list) else raw.get("elements", [])
            except Exception:
                existing_elements = []

        existing_nodes: List[Dict[str, Any]] = []
        existing_notes: List[Dict[str, Any]] = []
        existing_edges: List[Dict[str, Any]] = []

        for el in existing_elements:
            if not isinstance(el, dict):
                continue
            if el.get("type") == "rectangle" and (
                str(el.get("id", "")).startswith("node_")
                or el.get("semantic_type") == "node"
            ):
                existing_nodes.append({
                    "id": el.get("semantic_id") or el.get("id"),
                    "label": el.get("text") or el.get("boundText") or "",
                })
            elif el.get("semantic_type") == "note" or str(el.get("id", "")).startswith("note_"):
                existing_notes.append({
                    "id": el.get("semantic_id") or el.get("id"),
                    "content": el.get("text") or "",
                })
            elif el.get("type") == "arrow":
                existing_edges.append({
                    "id": el.get("semantic_id") or el.get("id"),
                    "source": (el.get("startBinding") or {}).get("elementId"),
                    "target": (el.get("endBinding") or {}).get("elementId"),
                })

        prompt = "\n".join([
            "You are Synora's semantic visual architecture planner.",
            "Return ONLY structured data matching the VisualPatchIntent schema.",
            "Decide WHAT should change. Never return coordinates, dimensions, raw Excalidraw JSON, authorization decisions, or revision metadata.",
            "",
            f"PROJECT_ID: {project_id}",
            "PROJECT STATE:",
            json.dumps(state or {}, default=str)[:5000],
            "",
            "CURRENT VISUAL NODES:",
            json.dumps(existing_nodes, default=str)[:5000],
            "",
            "CURRENT VISUAL NOTES:",
            json.dumps(existing_notes, default=str)[:3000],
            "",
            "CURRENT VISUAL EDGES:",
            json.dumps(existing_edges, default=str)[:3000],
            "",
            "PATCH RULES:",
            "1. Reuse an existing semantic node whenever it represents the same concept.",
            "2. Prefer UPDATE_NODE over ADD_NODE when the concept already exists.",
            "3. Never invent unrelated architecture.",
            "4. Only create relationships supported by the evidence.",
            "5. Notes must be concise and evidence-oriented.",
            "6. For project context, return 3-5 synthesized cards in context_notes. These must explain the project's purpose, current state, key decisions, constraints, open items, or next focus. Never copy the incoming transcript and never create one note per message.",
            "6. Use REMOVE operations only when removal is explicitly supported; otherwise use REVIEW_REQUIRED.",
            "7. Use REQUEST_LAYOUT_ADJUSTMENT only when topology genuinely requires layout work.",
            "8. Context-note identity is stable by section; the service will bind returned cards to context_purpose/context_current_state/context_key_decisions/context_constraints/context_open_items.",
            "9. Do not include x, y, width, height, points, or raw Excalidraw JSON.",
            "",
            "INCOMING EVIDENCE:",
            text[:5000],
        ])

        try:
            intent = self.llm_client.generate_structured(prompt, VisualPatchIntent)
            operations = list(intent.operations or [])

            if not operations:
                return (*self._deterministic_fallback_operations(text),)

            sanitized: List[VisualPatchOperation] = []
            for op in operations:
                if not op.target_id or not op.op_type:
                    continue
                op.evidence_ids = list(op.evidence_ids or [])

                if op.op_type == VisualPatchOpType.ADD_NODE and not op.label:
                    continue
                if (
                    op.op_type == VisualPatchOpType.ADD_EDGE
                    and (not op.source or not op.target)
                ):
                    continue

                sanitized.append(op)

            if not sanitized:
                sanitized = []

            has_destructive = any(
                op.op_type in (
                    VisualPatchOpType.REMOVE_NODE,
                    VisualPatchOpType.REMOVE_EDGE,
                    VisualPatchOpType.REMOVE_NOTE,
                    VisualPatchOpType.REMOVE_GROUP,
                )
                for op in sanitized
            )

            safety = (
                PatchSafetyClassification.REVIEW_REQUIRED
                if has_destructive
                else (
                    intent.safety_classification
                    or PatchSafetyClassification.SAFE_AUTO_APPLY
                )
            )

            return (
                sanitized,
                [str(note).strip()[:650] for note in intent.context_notes[:5] if str(note).strip()],
                safety,
                intent.reason
                or "Semantic visual intent generated by the configured reasoning model.",
            )
        except Exception as exc:
            logger.warning(
                "visual_patch_llm_generation_failed: project=%s error=%s",
                project_id,
                exc,
            )
            ops, notes, safety, fallback_reason = self._deterministic_fallback_operations(text)
            return ops, notes, safety, fallback_reason

    def _deterministic_fallback_operations(
        self, text: str
    ) -> Tuple[List[VisualPatchOperation], List[str], PatchSafetyClassification, str]:
        """Conservative offline fallback; never performs destructive operations."""
        lower_text = (text or "").lower()
        ops: List[VisualPatchOperation] = []

        if "qr" in lower_text and ("table" in lower_text or "order" in lower_text):
            node_id = make_stable_semantic_id("node", "Table QR Ordering")
            ops.append(
                VisualPatchOperation(
                    op_type=VisualPatchOpType.ADD_NODE,
                    target_id=node_id,
                    label="Table QR Ordering",
                    node_type="client",
                )
            )
            ops.append(
                VisualPatchOperation(
                    op_type=VisualPatchOpType.ADD_NOTE,
                    target_id=make_stable_semantic_id("note", "table_qr_ordering"),
                    category=VisualNoteCategory.REQUIREMENT,
                    content="Customers initiate orders through table QR scanning.",
                )
            )
        elif "kds" in lower_text or "kitchen display" in lower_text:
            node_id = make_stable_semantic_id("node", "Kitchen Display System")
            ops.append(
                VisualPatchOperation(
                    op_type=VisualPatchOpType.ADD_NODE,
                    target_id=node_id,
                    label="Kitchen Display System",
                    node_type="service",
                )
            )
            ops.append(
                VisualPatchOperation(
                    op_type=VisualPatchOpType.ADD_NOTE,
                    target_id=make_stable_semantic_id("note", "realtime_kds"),
                    category=VisualNoteCategory.REQUIREMENT,
                    content="Orders should reach the kitchen display in realtime.",
                )
            )
        else:
            return (
                [],
                [f"PROJECT CONTEXT — {text.strip()[:220]}"] if text.strip() else [],
                PatchSafetyClassification.REVIEW_REQUIRED,
                "Visual reasoning unavailable; no deterministic patch was safe to infer.",
            )

        return (
            ops,
            [f"PROJECT CONTEXT — {text.strip()[:220]}"] if text.strip() else [],
            PatchSafetyClassification.SAFE_AUTO_APPLY,
            "Deterministic fallback visual intent.",
        )

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
        if patch.project_id != project_id:
            raise ValueError("Visual patch project_id does not match target project.")

        # Idempotent retry: an already-applied patch returns its original revision.
        existing_patch = (
            db.query(VisualPatchModel)
            .filter(VisualPatchModel.id == patch.patch_id)
            .first()
        )
        if (
            existing_patch
            and existing_patch.status == "applied"
            and existing_patch.target_revision_id
        ):
            existing_revision = (
                db.query(VisualRevision)
                .filter(VisualRevision.id == existing_patch.target_revision_id)
                .first()
            )
            if existing_revision:
                return existing_revision

        current_rev = self.revision_service.current_revision(project_id, db)

        if (
            current_rev is not None
            and patch.base_revision_number is not None
            and current_rev.revision_number != patch.base_revision_number
        ):
            raise RuntimeError(
                f"Visual patch base revision {patch.base_revision_number} is stale; "
                f"current revision is {current_rev.revision_number}. Rebase/merge required."
            )

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
            parent_revision_id=current_rev.id if current_rev else None,
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
