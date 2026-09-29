import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.visual_revision import VisualOperation, VisualRevision, VisualWorkspace
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class VisualRevisionError(SynesisException):
    """Raised for invalid visual revision operations."""


class VisualRevisionService:
    """Immutable visual revision history for a project's living workspace.

    The latest revision IS the current visual workspace. Historical revisions
    are never mutated: restore branches forward by creating a NEW revision.
    Every revision is traceable to a Project State version and evidence.
    """

    def __init__(self, audit_service: Optional[AuditService] = None):
        self.audit_service = audit_service or AuditService()

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------
    def get_or_create_workspace(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        name: str = "Living Visual Workspace",
    ) -> VisualWorkspace:
        workspace = (
            db.query(VisualWorkspace).filter(VisualWorkspace.project_id == project_id).first()
        )
        if not workspace:
            workspace = VisualWorkspace(
                project_id=project_id,
                tenant_id=tenant_id,
                name=name,
            )
            db.add(workspace)
            db.commit()
            db.refresh(workspace)
            logger.info("visual_workspace_created: project=%s workspace=%s", project_id, workspace.id)
        return workspace

    # ------------------------------------------------------------------
    # Revisions
    # ------------------------------------------------------------------
    def current_revision(self, project_id: str, db: Session) -> Optional[VisualRevision]:
        workspace = (
            db.query(VisualWorkspace).filter(VisualWorkspace.project_id == project_id).first()
        )
        if not workspace or not workspace.current_revision_id:
            return None
        return (
            db.query(VisualRevision)
            .filter(VisualRevision.id == workspace.current_revision_id)
            .first()
        )

    def list_revisions(
        self, project_id: str, db: Session, limit: int = 50
    ) -> List[VisualRevision]:
        return (
            db.query(VisualRevision)
            .filter(VisualRevision.project_id == project_id)
            .order_by(VisualRevision.revision_number.desc())
            .limit(limit)
            .all()
        )

    def get_revision(
        self, project_id: str, revision_number: int, db: Session
    ) -> VisualRevision:
        revision = (
            db.query(VisualRevision)
            .filter(
                VisualRevision.project_id == project_id,
                VisualRevision.revision_number == revision_number,
            )
            .first()
        )
        if not revision:
            raise VisualRevisionError(
                f"Revision {revision_number} not found for project '{project_id}'."
            )
        return revision

    def commit_revision(
        self,
        project_id: str,
        scene: List[Dict[str, Any]],
        db: Session,
        tenant_id: str = "default_tenant",
        app_state: Optional[Dict[str, Any]] = None,
        operations: Optional[List[Dict[str, Any]]] = None,
        evidence_ids: Optional[List[str]] = None,
        derived_from_project_state_version: Optional[int] = None,
        proposal_id: Optional[str] = None,
        actor_id: str = "system",
        reason: str = "",
        workspace_name: str = "Living Visual Workspace",
    ) -> VisualRevision:
        """Append a new immutable revision and make it current."""
        workspace = self.get_or_create_workspace(
            project_id, db, tenant_id=tenant_id, name=workspace_name
        )
        latest = (
            db.query(VisualRevision)
            .filter(VisualRevision.workspace_id == workspace.id)
            .order_by(VisualRevision.revision_number.desc())
            .first()
        )
        next_number = (latest.revision_number + 1) if latest else 1

        if latest:
            latest.is_current = 0

        revision = VisualRevision(
            workspace_id=workspace.id,
            project_id=project_id,
            revision_number=next_number,
            parent_revision_id=latest.id if latest else None,
            derived_from_project_state_version=derived_from_project_state_version,
            scene_json=json.dumps(scene or []),
            app_state_json=json.dumps(app_state or {}),
            operations_json=json.dumps(operations or []),
            evidence_ids_json=json.dumps(evidence_ids or []),
            proposal_id=proposal_id,
            actor_id=actor_id,
            reason=reason,
            is_current=1,
        )
        db.add(revision)
        db.flush()

        for op in operations or []:
            db.add(
                VisualOperation(
                    revision_id=revision.id,
                    op_type=op.get("op_type", "update"),
                    target_element_id=op.get("target_element_id"),
                    payload_json=json.dumps(op.get("payload", {})),
                    source_evidence_ids_json=json.dumps(op.get("source_evidence_ids", [])),
                )
            )

        workspace.current_revision_id = revision.id
        workspace.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(revision)
        logger.info(
            "visual_revision_committed: project=%s revision=%s number=%d parent=%s "
            "state_version=%s evidence=%d actor=%s",
            project_id,
            revision.id,
            next_number,
            revision.parent_revision_id,
            derived_from_project_state_version,
            len(evidence_ids or []),
            actor_id,
        )
        return revision

    def restore_as_new_revision(
        self,
        project_id: str,
        target_revision_number: int,
        db: Session,
        actor_id: str,
        tenant_id: str = "default_tenant",
        reason: Optional[str] = None,
    ) -> VisualRevision:
        """Branch forward from a historical revision. Never destructive."""
        target = self.get_revision(project_id, target_revision_number, db)
        scene = self._json_list(target.scene_json)
        app_state = self._json_dict(target.app_state_json)
        restored = self.commit_revision(
            project_id=project_id,
            scene=scene,
            db=db,
            tenant_id=tenant_id,
            app_state=app_state,
            operations=[
                {
                    "op_type": "reorder",
                    "payload": {"restored_from_revision": target.revision_number},
                }
            ],
            derived_from_project_state_version=target.derived_from_project_state_version,
            evidence_ids=self._json_list(target.evidence_ids_json),
            actor_id=actor_id,
            reason=reason
            or f"Restored visual workspace from revision {target.revision_number}",
        )
        self.audit_service.record_event(
            action="visual_revision_restored",
            actor_id=actor_id,
            resource_type="visual_revision",
            resource_id=restored.id,
            db=db,
            tenant_id=tenant_id,
            after_state={
                "restored_from": target.revision_number,
                "new_revision": restored.revision_number,
            },
        )
        return restored

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------
    def compare(
        self,
        project_id: str,
        from_revision_number: int,
        to_revision_number: int,
        db: Session,
    ) -> Dict[str, Any]:
        """Structured, explainable diff between two revisions.

        Besides added/removed/changed labels, returns ``overlay_elements``:
        the target scene annotated so a canvas can render compare mode
        directly - removed elements re-appear as ghost/dashed nodes and
        added/changed elements carry highlight styling.
        """
        a = self.get_revision(project_id, from_revision_number, db)
        b = self.get_revision(project_id, to_revision_number, db)
        elements_a = {self._element_key(e): e for e in self._json_list(a.scene_json) if isinstance(e, dict)}
        elements_b = {self._element_key(e): e for e in self._json_list(b.scene_json) if isinstance(e, dict)}

        added = [k for k in elements_b if k not in elements_a]
        removed = [k for k in elements_a if k not in elements_b]
        changed = [
            k
            for k in elements_b
            if k in elements_a and self._element_signature(elements_a[k]) != self._element_signature(elements_b[k])
        ]

        overlay = self.build_compare_overlay(
            scene_from=self._json_list(a.scene_json),
            scene_to=self._json_list(b.scene_json),
        )

        return {
            "project_id": project_id,
            "from_revision": a.revision_number,
            "to_revision": b.revision_number,
            "added": [self._element_label(elements_b[k]) for k in added],
            "removed": [self._element_label(elements_a[k]) for k in removed],
            "changed": [
                {"before": self._element_label(elements_a[k]), "after": self._element_label(elements_b[k])}
                for k in changed
            ],
            "relationships_before": self._relationships(elements_a.values()),
            "relationships_after": self._relationships(elements_b.values()),
            "state_version_from": a.derived_from_project_state_version,
            "state_version_to": b.derived_from_project_state_version,
            "overlay_elements": overlay,
        }

    @staticmethod
    def build_compare_overlay(
        scene_from: List[Dict[str, Any]], scene_to: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Annotate the target scene for compare-mode rendering.

        - removed (ghost): element existed in ``from`` but not ``to``;
          re-inserted as dashed, translucent, non-editable so the canvas can
          show where old content used to be.
        - added: element only in ``to``; highlighted with a green tint.
        - changed: element in both with a different signature; flagged so
          the canvas can outline it.
        - unchanged: passed through untouched.

        The annotation lives in ``customData.compare`` plus standard
        Excalidraw style keys, so any renderer can apply it directly.
        """
        def key(el: Dict[str, Any]) -> str:
            return str(el.get("id") or el.get("text") or "")

        def signature(el: Dict[str, Any]) -> str:
            return json.dumps(
                {
                    "type": el.get("type"),
                    "text": el.get("text"),
                    "startBinding": el.get("startBinding"),
                    "endBinding": el.get("endBinding"),
                },
                sort_keys=True,
                default=str,
            )

        from_map = {key(e): e for e in scene_from if isinstance(e, dict) and key(e)}
        to_map = {key(e): e for e in scene_to if isinstance(e, dict) and key(e)}

        overlay: List[Dict[str, Any]] = []
        for k, el in to_map.items():
            annotated = dict(el)
            custom = dict(annotated.get("customData") or {})
            if k not in from_map:
                annotated.update(
                    {
                        "strokeColor": "#15803d",
                        "backgroundColor": "#dcfce7",
                        "strokeStyle": "solid",
                        "strokeWidth": 2,
                    }
                )
                custom["compare"] = "added"
            elif signature(from_map[k]) != signature(el):
                annotated["strokeWidth"] = max(int(el.get("strokeWidth") or 1), 2)
                annotated["strokeColor"] = el.get("strokeColor") or "#b45309"
                annotated["backgroundColor"] = el.get("backgroundColor") or "#fef3c7"
                custom["compare"] = "changed"
            else:
                custom["compare"] = "unchanged"
            annotated["customData"] = custom
            overlay.append(annotated)

        for k, el in from_map.items():
            if k in to_map:
                continue
            ghost = dict(el)
            ghost.update(
                {
                    "strokeStyle": "dashed",
                    "strokeColor": "#9ca3af",
                    "backgroundColor": "transparent",
                    "opacity": 45,
                    "angle": el.get("angle", 0),
                    "locked": True,
                }
            )
            custom = dict(ghost.get("customData") or {})
            custom["compare"] = "removed"
            ghost["customData"] = custom
            overlay.append(ghost)
        return overlay

    def compare_revisions(
        self,
        project_id: str,
        from_revision: int,
        to_revision: int,
        db: Session,
    ) -> Any:
        raw = self.compare(project_id, from_revision, to_revision, db)

        class DiffResult:
            def __init__(self, data):
                self._data = data
                self.added = data.get("added", [])
                self.removed = data.get("removed", [])
                self.changed = data.get("changed", [])
                self.from_revision = data.get("from_revision")
                self.to_revision = data.get("to_revision")

            def __getitem__(self, key):
                return self._data[key]

            def __repr__(self):
                return f"<DiffResult added={len(self.added)} removed={len(self.removed)} changed={len(self.changed)}>"

        return DiffResult(raw)

    @staticmethod
    def _element_key(el: Dict[str, Any]) -> str:
        return str(el.get("id") or el.get("text") or id(el))

    @staticmethod
    def _element_signature(el: Dict[str, Any]) -> str:
        return json.dumps(
            {
                "type": el.get("type"),
                "text": el.get("text"),
                "startBinding": el.get("startBinding"),
                "endBinding": el.get("endBinding"),
            },
            sort_keys=True,
            default=str,
        )

    @staticmethod
    def _element_label(el: Dict[str, Any]) -> str:
        text = (el.get("text") or "").strip()
        if text:
            return text[:80]
        return f"{el.get('type', 'element')}:{el.get('id', '?')}"

    @staticmethod
    def _relationships(elements) -> List[str]:
        rels: List[str] = []
        for el in elements:
            if not isinstance(el, dict) or el.get("type") != "arrow":
                continue
            start = (el.get("startBinding") or {}).get("elementId")
            end = (el.get("endBinding") or {}).get("elementId")
            if start or end:
                rels.append(f"{start or '?'} -> {end or '?'}")
        return rels

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    def format_revision_read(self, revision: VisualRevision) -> Dict[str, Any]:
        return {
            "id": revision.id,
            "project_id": revision.project_id,
            "revision_number": revision.revision_number,
            "parent_revision_id": revision.parent_revision_id,
            "derived_from_project_state_version": revision.derived_from_project_state_version,
            "proposal_id": revision.proposal_id,
            "actor_id": revision.actor_id,
            "reason": revision.reason,
            "is_current": bool(revision.is_current),
            "evidence_ids": self._json_list(revision.evidence_ids_json),
            "operations": self._json_list(revision.operations_json),
            "elements": self._json_list(revision.scene_json),
            "created_at": revision.created_at.isoformat() if revision.created_at else None,
        }

    @staticmethod
    def _json_list(raw: Optional[str]) -> List[Any]:
        try:
            value = json.loads(raw) if raw else []
            return value if isinstance(value, list) else []
        except Exception:
            return []

    @staticmethod
    def _json_dict(raw: Optional[str]) -> Dict[str, Any]:
        try:
            value = json.loads(raw) if raw else {}
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
