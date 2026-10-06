"""Periodic memory-to-canvas reconciliation.

Project memory (ProjectState + approved StateChanges) advances through many
paths: meetings, WhatsApp, manual approvals. The canvas (VisualRevision per
project) only moves when something explicitly draws it. This service closes
that gap on a timer: when approved memory exists that no canvas revision
reflects yet, it draws the delta through the same evidence-linked,
safety-gated patch path the ingestion pipelines use.

Safety properties, all deliberate:

- Only APPROVED state changes drive the loop. Proposed-but-unreviewed items
  never reach the canvas from here.
- Only add-only patches auto-apply (SAFE_AUTO_APPLY). Anything destructive is
  recorded as held_for_review and left alone.
- The evidence-volume gate applies: a project with fewer than two evidence
  rows keeps its canvas untouched.
- No-op detection: if the merged scene is fingerprint-identical to the
  current scene, no revision is committed. The loop is therefore safe to run
  every 30 seconds without spamming revision history.
- Everything is derived from persisted rows. There is no cursor to corrupt,
  no lock to leak, and a restart simply re-derives the same answer.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MIN_EVIDENCE_FOR_VISUAL = 2


def _scene_fingerprint(elements: List[Dict[str, Any]]) -> str:
    normalized = json.dumps(elements or [], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class VisualSyncService:
    """Reconcile each project's canvas with its approved memory."""

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
        from app.services.visual_merge_service import VisualMergeService
        from app.services.visual_patch_service import (
            PatchSafetyClassification,
            VisualPatchService,
        )
        from app.services.visual_revision_service import VisualRevisionService

        project = db.query(Project).filter(Project.id == project_id).first()
        if not project or getattr(project, "is_system", False):
            return {"project_id": project_id, "synced": False, "reason": "unknown_or_system"}

        state = ProjectStateService().get_or_create_state(project_id, db)
        revision_service = VisualRevisionService()
        current_rev = revision_service.current_revision(project_id, db)
        rev_time = (
            current_rev.created_at.isoformat()
            if current_rev and current_rev.created_at
            else ""
        )

        # Approved memory newer than the canvas = unsynced delta. The
        # StateChange rows carry their own evidence IDs, so the patch draws
        # exactly what changed, not the whole project history.
        from app.models.project_state import StateChange

        pending = (
            db.query(StateChange)
            .filter(
                StateChange.project_id == project_id,
                StateChange.approval_status == "approved",
            )
            .order_by(StateChange.created_at.asc())
            .all()
        )
        if current_rev is not None:
            pending = [
                ch for ch in pending
                if (ch.created_at.isoformat() if ch.created_at else "") > rev_time
            ]
        if not pending:
            return {
                "project_id": project_id,
                "synced": False,
                "reason": "up_to_date",
                "state_version": state.current_version,
            }

        total_evidence = (
            db.query(Evidence).filter(Evidence.project_id == project_id).count()
        )
        if total_evidence < MIN_EVIDENCE_FOR_VISUAL:
            logger.info(
                "visual_sync_deferred: project=%s evidence=%d required=%d",
                project_id,
                total_evidence,
                MIN_EVIDENCE_FOR_VISUAL,
            )
            return {
                "project_id": project_id,
                "synced": False,
                "reason": "deferred_below_evidence_gate",
            }

        wanted_ids: List[str] = []
        for ch in pending:
            try:
                ids = json.loads(ch.evidence_ids_json or "[]")
            except Exception:
                ids = []
            for ev_id in ids:
                if ev_id and ev_id not in wanted_ids:
                    wanted_ids.append(ev_id)
        rows = (
            db.query(Evidence).filter(Evidence.id.in_(wanted_ids)).all()
            if wanted_ids
            else []
        )
        # Fall back to recent project evidence when a change carries no IDs;
        # the gate above already ensured the project is non-trivial.
        if not rows:
            rows = (
                db.query(Evidence)
                .filter(Evidence.project_id == project_id)
                .order_by(Evidence.occurred_at.desc())
                .limit(10)
                .all()
            )
        text = "\n".join(r.content for r in rows if r.content and r.content.strip())
        if not text.strip():
            return {"project_id": project_id, "synced": False, "reason": "empty_text"}

        patch_service = VisualPatchService()
        try:
            patch = patch_service.generate_patch_from_evidence(
                project_id=project_id,
                text=text,
                db=db,
                evidence_ids=[r.id for r in rows],
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.warning("visual_sync_patch_failed: project=%s error=%s", project_id, exc)
            return {"project_id": project_id, "synced": False, "reason": f"patch_failed: {exc}"[:300]}

        if patch.safety_classification != PatchSafetyClassification.SAFE_AUTO_APPLY:
            logger.info(
                "visual_sync_held_for_review: project=%s safety=%s patch=%s",
                project_id,
                patch.safety_classification.value,
                patch.patch_id,
            )
            return {
                "project_id": project_id,
                "synced": False,
                "reason": f"held_for_review:{patch.safety_classification.value}",
                "patch_id": patch.patch_id,
            }

        # No-op detection: same scene, no new revision. Stable semantic node
        # IDs make re-application converge, so this comparison is meaningful.
        base_elements: List[Dict[str, Any]] = []
        if current_rev and current_rev.scene_json:
            try:
                base_elements = json.loads(current_rev.scene_json)
            except Exception:
                base_elements = []
        merged, _, _ = VisualMergeService().merge(
            base_elements=base_elements,
            user_elements=base_elements,
            patch=patch,
        )
        if _scene_fingerprint(merged) == _scene_fingerprint(base_elements):
            logger.info("visual_sync_no_change: project=%s patch=%s", project_id, patch.patch_id)
            return {
                "project_id": project_id,
                "synced": False,
                "reason": "no_change",
                "patch_id": patch.patch_id,
            }

        new_rev = patch_service.apply_patch(
            project_id=project_id,
            patch=patch,
            db=db,
            actor_id=actor_id,
            tenant_id=tenant_id,
        )
        logger.info(
            "visual_sync_applied: project=%s revision=%s changes=%d",
            project_id,
            new_rev.id,
            len(pending),
        )
        return {
            "project_id": project_id,
            "synced": True,
            "reason": "applied",
            "revision_id": new_rev.id,
            "revision_number": new_rev.revision_number,
            "patch_id": patch.patch_id,
            "changes": len(pending),
        }

    def sync_all(
        self,
        db: Session,
        actor_id: str = "visual_sync_loop",
        tenant_id: str = "default_tenant",
        project_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Reconcile every eligible project. One project's failure never
        blocks the others; the summary records each outcome."""
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
                results[pid] = {"project_id": pid, "synced": False, "reason": f"error: {exc}"[:300]}
        applied = sum(1 for r in results.values() if r.get("synced"))
        logger.info("visual_sync_cycle: projects=%d applied=%d", len(results), applied)
        return {"projects": len(results), "applied": applied, "results": results}
