"""Periodic project-memory to Excalidraw reconciliation.

Every cycle rebuilds the project's *desired* canvas from authoritative project
memory plus recent evidence, then compares it with the current revision.
The agent decides whether content belongs in readable notes, a lightweight
visualization, or a genuine diagram. The compiler owns layout and geometry.

User-authored Excalidraw elements are preserved. Agent-owned elements are
reconciled from scratch, which lets stale diagrams/notes disappear when memory
changes instead of accumulating duplicate cards.

The worker is intentionally stateless: restarting it simply reconstructs the
same answer from persisted memory and the current canvas.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)


def _scene_fingerprint(elements: List[Dict[str, Any]]) -> str:
    normalized = json.dumps(elements or [], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _is_agent_managed(element: Dict[str, Any]) -> bool:
    custom = element.get("customData") or {}
    if isinstance(custom, dict):
        if isinstance(custom.get("visual"), dict) and bool(custom.get("visual")):
            return True
        # The atlas service tags with customData.atlas instead of .visual.
        if isinstance(custom.get("atlas"), dict) and bool(custom.get("atlas")):
            return True
    # Fallback for scenes written before the provenance markers existed:
    # every compiler/atlas id scheme below is machine-generated, while
    # human-drawn elements get random ids. Without this, stale pre-fix
    # elements are mistaken for user drawings and carried forward forever.
    eid = str(element.get("id") or "")
    return eid.startswith((
        "node_", "label_", "annotation_", "edge_", "edge_label_",
        "group_backdrop_", "group_label_", "conn_",
        "notes_", "note_", "note_block_", "note_section_",
        "sticky_text_", "lbl_notes", "legacy_", "legacy_block_",
        "visual_", "atlas_",
    ))


def _canvas_summary(scene: List[Dict[str, Any]]) -> List[str]:
    summary: List[str] = []
    for element in scene[:100]:
        visual = ((element.get("customData") or {}).get("visual") or {})
        if not isinstance(visual, dict):
            visual = {}
        semantic_id = visual.get("semantic_id")
        if semantic_id:
            text_value = element.get("text")
            label = f"{semantic_id}"
            if text_value:
                label += f": {str(text_value)[:90]}"
            summary.append(label)
        elif visual.get("type"):
            summary.append(str(visual.get("type")))
    return summary[:50]


def _state_summary(project: Any, state_row: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if state_row and state_row.state_json:
        try:
            result = json.loads(state_row.state_json)
        except Exception:
            result = {}
    result = dict(result)
    result.setdefault("title", getattr(project, "name", None) or "Project")
    description = getattr(project, "description", None)
    if description and not result.get("description"):
        result["description"] = description
    return result


class VisualSyncService:
    """Reconcile a project's full visual notebook with current memory."""

    def sync_project(
        self,
        project_id: str,
        db: Session,
        actor_id: str = "visual_sync_loop",
        tenant_id: str = "default_tenant",
    ) -> Dict[str, Any]:
        from app.models.evidence import Evidence
        from app.models.project import Project
        from app.services.project_state_service import ProjectStateService
        from app.services.visual_plan_service import VisualPlanService
        from app.services.visual_revision_service import VisualRevisionService
        from app.services.excalidraw_compiler import ExcalidrawCompiler, ExcalidrawCompileError

        project = db.query(Project).filter(Project.id == project_id).first()
        if not project or getattr(project, "is_system", False):
            return {"project_id": project_id, "synced": False, "reason": "unknown_or_system"}

        state_row = ProjectStateService().get_or_create_state(project_id, db)
        state_summary = _state_summary(project, state_row)

        revision_service = VisualRevisionService()
        current_rev = revision_service.current_revision(project_id, db)
        base_scene: List[Dict[str, Any]] = []
        if current_rev and current_rev.scene_json:
            try:
                base_scene = json.loads(current_rev.scene_json)
            except Exception:
                base_scene = []

        evidence_rows = (
            db.query(Evidence)
            .filter(Evidence.project_id == project_id)
            .order_by(Evidence.occurred_at.desc())
            .limit(16)
            .all()
        )
        evidence_snippets = [
            {"id": row.id, "content": row.content, "source": getattr(row, "source", None)}
            for row in reversed(evidence_rows)
            if row.content and row.content.strip()
        ]

        current_canvas = _canvas_summary(base_scene)
        # The agent chooses the project's note structure and visual form.
        # There is no fixed notebook layout, diagram taxonomy, or note format.
        # Project scoping is the only product-level boundary: this canvas belongs
        # to one project, while the compiler owns only geometry and persistence.
        constraints = None

        try:
            plan, ai_status = VisualPlanService().build_plan(
                state_summary=state_summary,
                current_nodes=current_canvas,
                evidence_snippets=evidence_snippets,
                focus_prompt=None,
                constraints=constraints,
            )
        except Exception as exc:
            logger.warning("visual_sync_plan_failed: project=%s error=%s", project_id, exc)
            return {"project_id": project_id, "synced": False, "reason": f"plan_failed: {exc}"[:300]}

        # Do not second-guess the agent's visual decision here. A diagram,
        # sketch, single-node model, timeline, matrix, or another composition
        # may be useful in context. The only hard layout rule is that geometry
        # is assigned by the compiler.
        visual_content_exists = bool(plan.nodes or plan.relationships or getattr(plan, "visualizations", []))
        proper_diagram = bool(plan.nodes or plan.relationships)
        if visual_content_exists and plan.canvas_strategy == "text":
            plan.canvas_strategy = "mixed"

        compiler = ExcalidrawCompiler()
        try:
            compiled_agent_scene = compiler.compile(
                plan,
                enforce_grounding=not settings.visual_design_free,
            )
        except ExcalidrawCompileError as exc:
            logger.warning("visual_sync_compile_failed: project=%s error=%s", project_id, exc)
            return {"project_id": project_id, "synced": False, "reason": f"compile_failed: {exc}"[:300]}

        # Keep anything the human drew/added that is not part of Synora's
        # managed semantic layer. Rebuild only agent-managed content so removed
        # memory items disappear cleanly.
        user_scene = [element for element in base_scene if not _is_agent_managed(element)]
        merged_scene = user_scene + compiled_agent_scene

        if _scene_fingerprint(merged_scene) == _scene_fingerprint(base_scene):
            return {
                "project_id": project_id,
                "synced": False,
                "reason": "no_change",
                "state_version": getattr(state_row, "current_version", None),
                "ai_status": ai_status,
                "diagram": proper_diagram,
            }

        plan_dump = plan.model_dump(mode="json")
        plan_fingerprint = hashlib.sha256(
            json.dumps(plan_dump, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        # Post-render verification (warn-first, never blocking): diff the
        # compiled scene against memory + evidence so ungrounded sentences
        # are flagged, badged, and logged — never silently rendered.
        from app.services.note_verification_service import verify_scene

        verification = verify_scene(
            merged_scene,
            [json.dumps(state_summary, default=str, ensure_ascii=False)]
            + [str(snippet.get("content") or "") for snippet in evidence_snippets],
        )

        revision = revision_service.commit_revision(
            project_id=project_id,
            scene=merged_scene,
            db=db,
            tenant_id=tenant_id,
            app_state={
                "living_canvas": {
                    "ai_status": ai_status,
                    "representation": plan.canvas_strategy,
                    "diagram_created": proper_diagram,
                    "plan_fingerprint": plan_fingerprint,
                    "memory_version": getattr(state_row, "current_version", None),
                    "evidence_ids": [row.id for row in evidence_rows],
                    "notes_sections": len(getattr(plan, "notes_sections", []) or []),
                    "visualizations": len(getattr(plan, "visualizations", []) or []),
                    "verification": verification,
                }
            },
            operations=[
                {
                    "op_type": "reconcile",
                    "target_element_id": "project_canvas",
                    "payload": {
                        "mode": "living_notebook",
                        "representation": plan.canvas_strategy,
                        "diagram_created": proper_diagram,
                        "agent_status": ai_status,
                    },
                    "source_evidence_ids": [row.id for row in evidence_rows],
                }
            ],
            evidence_ids=[row.id for row in evidence_rows],
            derived_from_project_state_version=getattr(state_row, "current_version", None),
            actor_id=actor_id,
            reason="30-second project-memory canvas reconciliation",
            workspace_name="Living Project Notebook",
        )

        logger.info(
            "visual_sync_reconciled: project=%s revision=%s number=%s representation=%s diagram=%s",
            project_id,
            revision.id,
            revision.revision_number,
            plan.canvas_strategy,
            proper_diagram,
        )
        if verification.get("unverified_total"):
            logger.warning(
                "visual_sync_unverified_items: project=%s unverified=%d checked=%d",
                project_id,
                verification.get("unverified_total"),
                verification.get("checked"),
            )
        return {
            "project_id": project_id,
            "synced": True,
            "reason": "reconciled",
            "revision_id": revision.id,
            "revision_number": revision.revision_number,
            "ai_status": ai_status,
            "representation": plan.canvas_strategy,
            "diagram": proper_diagram,
            "state_version": getattr(state_row, "current_version", None),
            "verification": verification,
        }

    def sync_all(
        self,
        db: Session,
        actor_id: str = "visual_sync_loop",
        tenant_id: str = "default_tenant",
        project_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Reconcile every eligible project."""
        from app.models.project import Project

        if project_ids is None:
            project_ids = [
                row[0]
                for row in db.query(Project.id).filter(Project.is_system.is_(False)).all()
            ]

        results: Dict[str, Any] = {}
        for pid in project_ids:
            try:
                results[pid] = self.sync_project(
                    pid, db, actor_id=actor_id, tenant_id=tenant_id
                )
            except Exception as exc:
                logger.warning("visual_sync_failed: project=%s error=%s", pid, exc)
                results[pid] = {
                    "project_id": pid,
                    "synced": False,
                    "reason": f"error: {exc}"[:300],
                }

        applied = sum(1 for result in results.values() if result.get("synced"))
        logger.info("visual_sync_cycle: projects=%d applied=%d", len(results), applied)
        return {"projects": len(results), "applied": applied, "results": results}
