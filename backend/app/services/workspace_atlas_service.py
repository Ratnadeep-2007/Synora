from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.context_resolution import PossibleProjectMatch, UnknownContextItem, UnknownItemStatus
from app.models.excalidraw import ExcalidrawArtifact
from app.models.project import Project
from app.models.project_state import ProjectState
from app.services.excalidraw_service import ExcalidrawService
from app.services.visual_revision_service import VisualRevisionService

logger = logging.getLogger(__name__)

SYSTEM_WORKSPACE_ATLAS_PROJECT_ID = "proj_workspace_atlas"

# Logical canvas units. Excalidraw is infinite; these constants define the
# workspace's stable horizontal "columns" while allowing unlimited vertical growth.
CM = 37.7952755906  # Excalidraw logical units per CSS px-equivalent centimetre
COLUMN_WIDTH_CM = 36.0
COLUMN_GUTTER_CM = 3.0
COLUMN_WIDTH = int(round(COLUMN_WIDTH_CM * CM))
COLUMN_GUTTER = int(round(COLUMN_GUTTER_CM * CM))
ATLAS_PADDING_X = 80
ATLAS_PADDING_Y = 60

HEADER_H = 174
ARCH_X_PAD = 70
ARCH_Y = ATLAS_PADDING_Y + HEADER_H
ARCH_W = COLUMN_WIDTH - (ARCH_X_PAD * 2)
ARCH_H = 670

NOTES_Y = ARCH_Y + ARCH_H + 70
NOTE_GAP = 26
NOTE_W = int((COLUMN_WIDTH - (ARCH_X_PAD * 2) - NOTE_GAP) / 2)
NOTE_H = 252
MINI_W = NOTE_W - 36
MINI_H = 126

UNKNOWN_CARD_H = 146

STYLE = {
    "frame": {"stroke": "#d8ded6", "background": "#ffffff"},
    "header": {"stroke": "#355a3c", "background": "#eef6ee"},
    "divider": {"stroke": "#d7ddd6", "background": "transparent"},
    "decision": {"stroke": "#15803d", "background": "#ecfdf5", "text": "#14532d"},
    "requirement": {"stroke": "#4338ca", "background": "#eef2ff", "text": "#312e81"},
    "action": {"stroke": "#166534", "background": "#f0fdf4", "text": "#14532d"},
    "risk": {"stroke": "#c2410c", "background": "#fff7ed", "text": "#9a3412"},
    "question": {"stroke": "#2563eb", "background": "#eff6ff", "text": "#1e40af"},
    "unknown": {"stroke": "#b45309", "background": "#fffbeb", "text": "#78350f"},
}


class WorkspaceAtlasService:
    """Builds one DB-backed Excalidraw page for the whole workspace.

    The atlas is intentionally deterministic at layout time:
    - every project receives a stable horizontal column;
    - project content cannot cross column boundaries;
    - architecture occupies the majority of the space;
    - compact knowledge cards sit below the architecture;
    - Unknown Context is always the first column;
    - the atlas is rebuilt only when its workspace fingerprint changes.
    """

    def __init__(
        self,
        excalidraw_service: Optional[ExcalidrawService] = None,
        revision_service: Optional[VisualRevisionService] = None,
    ):
        self.excal = excalidraw_service or ExcalidrawService()
        self.revisions = revision_service or VisualRevisionService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_or_sync(
        self,
        db: Session,
        tenant_id: str = "default_tenant",
        workspace_id: str = "ws_default",
    ) -> Dict[str, Any]:
        self._ensure_system_project(db, tenant_id, workspace_id)
        artifact = self.excal.get_or_create_artifact(
            SYSTEM_WORKSPACE_ATLAS_PROJECT_ID,
            db,
            tenant_id=tenant_id,
            name="Synora Project Atlas",
        )

        projects = (
            db.query(Project)
            .filter(
                Project.workspace_id == workspace_id,
                Project.is_system.is_(False),
                Project.workspace_id == workspace_id,
            )
            .order_by(Project.created_at.asc(), Project.id.asc())
            .all()
        )

        app_state = self._json_dict(artifact.app_state_json)
        slot_map = self._assign_slots(projects, app_state.get("atlas_slots") or {})
        fingerprint = self._fingerprint(projects, db, tenant_id, slot_map)

        if app_state.get("atlas_fingerprint") != fingerprint:
            scene, metadata = self._build_scene(
                projects=projects,
                db=db,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                slot_map=slot_map,
            )
            now = datetime.now(timezone.utc)
            artifact.elements_json = json.dumps(scene)
            artifact.extracted_nodes_json = json.dumps([p.name for p in projects])
            artifact.app_state_json = json.dumps(
                {
                    **app_state,
                    "viewBackgroundColor": "#f7f8f5",
                    "gridSize": 20,
                    "theme": "light",
                    "atlas_fingerprint": fingerprint,
                    "atlas_slots": slot_map,
                    "atlas_versioned_at": now.isoformat(),
                }
            )
            artifact.version = max(int(artifact.version or 1) + 1, 2)
            artifact.updated_at = now

            self.revisions.commit_revision(
                project_id=SYSTEM_WORKSPACE_ATLAS_PROJECT_ID,
                scene=scene,
                db=db,
                tenant_id=tenant_id,
                app_state=self._json_dict(artifact.app_state_json),
                operations=[
                    {
                        "op_type": "atlas_rebuild",
                        "payload": {
                            "project_count": len(projects),
                            "unknown_count": metadata["unknown_count"],
                            "fingerprint": fingerprint,
                        },
                    }
                ],
                actor_id="synora_atlas",
                reason=f"Workspace Project Atlas synchronized ({len(projects)} projects).",
                workspace_name="Synora Project Atlas",
            )
            db.refresh(artifact)

        unknown_count = (
            db.query(UnknownContextItem)
            .filter(
                UnknownContextItem.tenant_id == tenant_id,
                UnknownContextItem.status == UnknownItemStatus.PENDING.value,
            )
            .count()
        )
        current_revision = self.revisions.current_revision(
            SYSTEM_WORKSPACE_ATLAS_PROJECT_ID, db
        )

        return {
            "artifact": self.excal.format_artifact_read(artifact).model_dump(),
            "layout": {
                "column_width": COLUMN_WIDTH,
                "column_gutter": COLUMN_GUTTER,
                "column_width_cm": COLUMN_WIDTH_CM,
                "column_gutter_cm": COLUMN_GUTTER_CM,
                "padding_x": ATLAS_PADDING_X,
                "project_columns": len(projects),
                "unknown_context_column": 0,
            },
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "state_version": self._state_version(p.id, db),
                    "diagram_version": self._diagram_version(p.id, db, tenant_id),
                    "atlas_slot": slot_map.get(p.id),
                }
                for p in projects
            ],
            "unknown_context": {
                "pending": unknown_count,
            },
            "revision": {
                "number": current_revision.revision_number if current_revision else 0,
                "updated_at": (
                    current_revision.created_at.isoformat()
                    if current_revision
                    else artifact.updated_at.isoformat() if artifact.updated_at else None
                ),
            },
        }

    # ------------------------------------------------------------------
    # Workspace system project
    # ------------------------------------------------------------------
    def _ensure_system_project(
        self,
        db: Session,
        tenant_id: str,
        workspace_id: str,
    ) -> Project:
        project = (
            db.query(Project)
            .filter(Project.id == SYSTEM_WORKSPACE_ATLAS_PROJECT_ID)
            .first()
        )
        if project:
            return project

        project = Project(
            id=SYSTEM_WORKSPACE_ATLAS_PROJECT_ID,
            workspace_id=workspace_id,
            name="Project Atlas",
            description="Reserved system project backing Synora's single infinite workspace canvas.",
            is_system=True,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        logger.info("workspace_atlas_system_project_created: %s", project.id)
        return project

    # ------------------------------------------------------------------
    # Fingerprinting / efficiency
    # ------------------------------------------------------------------
    def _assign_slots(self, projects: List[Project], existing: Dict[str, Any]) -> Dict[str, int]:
        """Assign stable horizontal slots; deleted projects keep their historical slot."""
        slots: Dict[str, int] = {}
        for pid, slot in (existing or {}).items():
            try:
                slots[str(pid)] = int(slot)
            except (TypeError, ValueError):
                continue
        next_slot = max(slots.values(), default=0) + 1
        for project in projects:
            if project.id not in slots:
                slots[project.id] = next_slot
                next_slot += 1
        return slots
    def _fingerprint(
        self,
        projects: List[Project],
        db: Session,
        tenant_id: str,
        slot_map: Dict[str, int],
    ) -> str:
        unknown = (
            db.query(UnknownContextItem)
            .filter(
                UnknownContextItem.tenant_id == tenant_id,
                UnknownContextItem.status == UnknownItemStatus.PENDING.value,
            )
            .order_by(UnknownContextItem.created_at.desc())
            .limit(50)
            .all()
        )

        payload = {
            "projects": [
                {
                    "id": p.id,
                    "name": p.name,
                    "updated": p.updated_at.isoformat() if p.updated_at else None,
                    "state_version": self._state_version(p.id, db),
                    "diagram_version": self._diagram_version(p.id, db, tenant_id),
                    "atlas_slot": slot_map.get(p.id),
                }
                for p in projects
            ],
            "unknown": [
                {
                    "id": item.id,
                    "updated": item.created_at.isoformat() if item.created_at else None,
                    "status": item.status,
                    "matches": [m.candidate_project_id for m in db.query(PossibleProjectMatch).filter(PossibleProjectMatch.unknown_item_id == item.id).order_by(PossibleProjectMatch.created_at.desc()).limit(2).all()],
                }
                for item in unknown
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _state_version(project_id: str, db: Session) -> int:
        row = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        return int(row.current_version) if row else 0

    @staticmethod
    def _diagram_version(
        project_id: str,
        db: Session,
        tenant_id: str,
    ) -> int:
        row = (
            db.query(ExcalidrawArtifact)
            .filter(
                ExcalidrawArtifact.project_id == project_id,
                ExcalidrawArtifact.tenant_id == tenant_id,
            )
            .first()
        )
        return int(row.version) if row else 0

    # ------------------------------------------------------------------
    # Scene building
    # ------------------------------------------------------------------
    def _build_scene(
        self,
        projects: List[Project],
        db: Session,
        tenant_id: str,
        workspace_id: str,
        slot_map: Optional[Dict[str, int]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        scene: List[Dict[str, Any]] = []
        if slot_map is None:
            slot_map = self._assign_slots(projects, {})

        unknown_items = (
            db.query(UnknownContextItem)
            .filter(
                UnknownContextItem.tenant_id == tenant_id,
                UnknownContextItem.status == UnknownItemStatus.PENDING.value,
            )
            .order_by(UnknownContextItem.created_at.desc())
            .limit(8)
            .all()
        )

        # Global atlas spine: keeps the whole infinite page visually anchored.
        max_slot = max(slot_map.values(), default=0)
        total_width = ATLAS_PADDING_X + (max_slot + 1) * (COLUMN_WIDTH + COLUMN_GUTTER)
        scene.extend([
            self._text(
                self._id("atlas", "title"),
                ATLAS_PADDING_X,
                12,
                max(COLUMN_WIDTH, total_width - ATLAS_PADDING_X),
                32,
                "SYNORA  •  PROJECT ATLAS",
                22,
                "#26362b",
                bold=True,
                custom_data={"atlas": {"type": "global_header"}},
            ),
            self._text(
                self._id("atlas", "subtitle"),
                ATLAS_PADDING_X,
                39,
                max(COLUMN_WIDTH, total_width - ATLAS_PADDING_X),
                18,
                "One living workspace  •  architecture first  •  evidence-backed knowledge  •  human attention only when context is unresolved",
                10,
                "#68756b",
                custom_data={"atlas": {"type": "global_header"}},
            ),
        ])

        # Column 0 is always Context Inbox.
        scene.extend(self._unknown_column(unknown_items, db, workspace_id))

        for project in projects:
            slot = slot_map.get(project.id, 1)
            x = ATLAS_PADDING_X + slot * (COLUMN_WIDTH + COLUMN_GUTTER)
            scene.extend(
                self._project_column(
                    project=project,
                    db=db,
                    tenant_id=tenant_id,
                    origin_x=x,
                )
            )

        return scene, {"unknown_count": len(unknown_items)}

    def _project_column(
        self,
        project: Project,
        db: Session,
        tenant_id: str,
        origin_x: float,
    ) -> List[Dict[str, Any]]:
        state = db.query(ProjectState).filter(ProjectState.project_id == project.id).first()
        artifact = (
            db.query(ExcalidrawArtifact)
            .filter(
                ExcalidrawArtifact.project_id == project.id,
                ExcalidrawArtifact.tenant_id == tenant_id,
            )
            .first()
        )

        scene: List[Dict[str, Any]] = []
        frame_id = self._id(project.id, "frame")
        header_id = self._id(project.id, "header")
        scene.append(
            self._rect(
                frame_id,
                origin_x,
                ATLAS_PADDING_Y,
                COLUMN_WIDTH,
                self._column_height(state),
                STYLE["frame"],
                opacity=100,
                roundness=3,
            )
        )
        scene.append(
            self._rect(
                header_id,
                origin_x + 22,
                ATLAS_PADDING_Y + 22,
                COLUMN_WIDTH - 44,
                HEADER_H - 28,
                STYLE["header"],
                opacity=100,
                roundness=3,
            )
        )
        scene.append(
            self._text(
                self._id(project.id, "title"),
                origin_x + 46,
                ATLAS_PADDING_Y + 42,
                COLUMN_WIDTH - 92,
                34,
                project.name.upper(),
                25,
                "#1f3a24",
                bold=True,
                custom_data={"atlas": {"type": "project_header", "project_id": project.id}},
            )
        )

        domain = self._project_domain(project, db, tenant_id)
        if domain:
            scene.append(
                self._text(
                    self._id(project.id, "domain"),
                    origin_x + 46,
                    ATLAS_PADDING_Y + 84,
                    COLUMN_WIDTH - 92,
                    22,
                    domain,
                    13,
                    "#506353",
                    custom_data={"atlas": {"type": "project_domain", "project_id": project.id}},
                )
            )

        state_version = state.current_version if state else 0
        reqs = self._json_list(state.requirements_json if state else "[]")
        decs = self._json_list(state.decisions_json if state else "[]")
        questions = self._json_list(state.open_questions_json if state else "[]")
        constraints = self._json_list(state.constraints_json if state else "[]")

        intent = self._project_intent(state)
        if intent:
            scene.append(
                self._text(
                    self._id(project.id, "intent"),
                    origin_x + 46,
                    ATLAS_PADDING_Y + 108,
                    COLUMN_WIDTH - 92,
                    34,
                    f"INTENT  •  {intent}",
                    10,
                    "#506353",
                    bold=False,
                    custom_data={"atlas": {"type": "project_intent", "project_id": project.id}},
                )
            )

        scene.append(
            self._text(
                self._id(project.id, "metrics"),
                origin_x + 46,
                ATLAS_PADDING_Y + 151,
                COLUMN_WIDTH - 92,
                18,
                f"STATE v{state_version}   •   {len(reqs)} requirements   •   {len(decs)} decisions   •   {len(questions)} questions   •   {len(constraints)} constraints",
                10,
                "#66736a",
                custom_data={"atlas": {"type": "project_metrics", "project_id": project.id}},
            )
        )

        architecture_elements = self._architecture_from_artifact(artifact)
        if not architecture_elements:
            architecture_elements = self._fallback_architecture(state)
        scene.extend(
            self._place_architecture(
                architecture_elements,
                origin_x + ARCH_X_PAD,
                ARCH_Y,
                ARCH_W,
                ARCH_H,
                project.id,
            )
        )

        scene.append(
            self._text(
                self._id(project.id, "notes_header"),
                origin_x + ARCH_X_PAD,
                NOTES_Y,
                COLUMN_WIDTH - (ARCH_X_PAD * 2),
                26,
                "CONTEXT & KNOWLEDGE",
                14,
                "#3b4a3f",
                bold=True,
                custom_data={"atlas": {"type": "knowledge_header", "project_id": project.id}},
            )
        )
        scene.append(
            self._line(
                self._id(project.id, "notes_divider"),
                origin_x + ARCH_X_PAD,
                NOTES_Y + 34,
                origin_x + COLUMN_WIDTH - ARCH_X_PAD,
                NOTES_Y + 34,
            )
        )

        notes = self._knowledge_cards(
            project.id,
            reqs=reqs,
            decs=decs,
            questions=questions,
            constraints=constraints,
        )
        for i, note in enumerate(notes[:8]):
            row = i // 2
            col = i % 2
            nx = origin_x + ARCH_X_PAD + col * (NOTE_W + NOTE_GAP)
            ny = NOTES_Y + 52 + row * (NOTE_H + NOTE_GAP)
            scene.extend(self._note_card(project.id, note, nx, ny))

        return scene

    def _column_height(self, state: Optional[ProjectState]) -> int:
        reqs = len(self._json_list(state.requirements_json if state else "[]"))
        decs = len(self._json_list(state.decisions_json if state else "[]"))
        questions = len(self._json_list(state.open_questions_json if state else "[]"))
        rows = max(2, (min(8, reqs + decs + questions + 1) + 1) // 2)
        return NOTES_Y + 52 + rows * (NOTE_H + NOTE_GAP) + 90

    # ------------------------------------------------------------------
    # Architecture helpers
    # ------------------------------------------------------------------
    def _architecture_from_artifact(
        self,
        artifact: Optional[ExcalidrawArtifact],
    ) -> List[Dict[str, Any]]:
        if not artifact or not artifact.elements_json:
            return []
        elements = self._json_list(artifact.elements_json)
        # Keep architecture and annotations; drop sticky-note/knowledge cards so
        # the Atlas has one consistent note style.
        filtered: List[Dict[str, Any]] = []
        for el in elements:
            if not isinstance(el, dict) or el.get("isDeleted"):
                continue
            ids = str(el.get("id", "")).lower()
            groups = [str(g).lower() for g in (el.get("groupIds") or [])]
            if ids.startswith(("sticky_note_", "label_notes", "lbl_notes_hdr", "note_")):
                continue
            if "architectural_notes" in groups or "project_knowledge" in groups:
                continue
            filtered.append(el)
        return filtered

    def _place_architecture(
        self,
        elements: List[Dict[str, Any]],
        target_x: float,
        target_y: float,
        target_w: float,
        target_h: float,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        if not elements:
            return []

        bbox = self._bbox(elements)
        min_x, min_y, max_x, max_y = bbox
        width = max(1.0, max_x - min_x)
        height = max(1.0, max_y - min_y)
        scale = min(target_w / width, target_h / height, 1.0)
        offset_x = target_x + (target_w - width * scale) / 2 - min_x * scale
        offset_y = target_y + (target_h - height * scale) / 2 - min_y * scale

        id_map = {
            str(el.get("id")): self._id(project_id, f"src_{el.get('id')}")
            for el in elements
            if el.get("id")
        }

        output: List[Dict[str, Any]] = []
        for el in elements:
            clone = json.loads(json.dumps(el))
            old_id = str(clone.get("id") or self._id(project_id, "generated"))
            clone["id"] = id_map.get(old_id, self._id(project_id, old_id))
            clone["x"] = float(clone.get("x") or 0) * scale + offset_x
            clone["y"] = float(clone.get("y") or 0) * scale + offset_y
            if "width" in clone:
                clone["width"] = max(1, float(clone.get("width") or 0) * scale)
            if "height" in clone:
                clone["height"] = max(1, float(clone.get("height") or 0) * scale)
            if clone.get("fontSize"):
                clone["fontSize"] = max(11, float(clone["fontSize"]) * scale)
            if isinstance(clone.get("points"), list):
                clone["points"] = [
                    [float(point[0]) * scale, float(point[1]) * scale]
                    for point in clone["points"]
                    if isinstance(point, list) and len(point) >= 2
                ]
            if clone.get("containerId"):
                clone["containerId"] = id_map.get(
                    str(clone["containerId"]), clone["containerId"]
                )
            if isinstance(clone.get("boundElements"), list):
                clone["boundElements"] = [
                    {**b, "id": id_map.get(str(b.get("id")), b.get("id"))}
                    for b in clone["boundElements"]
                ]
            for binding_key in ("startBinding", "endBinding"):
                binding = clone.get(binding_key)
                if isinstance(binding, dict) and binding.get("elementId"):
                    binding["elementId"] = id_map.get(
                        str(binding["elementId"]), binding["elementId"]
                    )
            if isinstance(clone.get("groupIds"), list):
                clone["groupIds"] = [
                    self._id(project_id, f"group_{g}") for g in clone["groupIds"]
                ]
            clone["customData"] = {
                **(clone.get("customData") or {}),
                "atlas": {
                    "type": "architecture_element",
                    "project_id": project_id,
                },
            }
            output.append(clone)

        return output

    def _fallback_architecture(
        self,
        state: Optional[ProjectState],
    ) -> List[Dict[str, Any]]:
        if not state:
            return []
        architecture = self._json_list(state.architecture_json)
        nodes: List[Dict[str, Any]] = []
        for idx, item in enumerate(architecture[:6]):
            if isinstance(item, dict):
                label = item.get("component") or item.get("name") or item.get("title") or "Component"
            else:
                label = str(item)
            nodes.append(
                {
                    "id": f"fallback_{idx}",
                    "type": "rectangle",
                    "x": 0,
                    "y": idx * 140,
                    "width": 300,
                    "height": 86,
                    "angle": 0,
                    "strokeColor": "#356346",
                    "backgroundColor": "#ffffff",
                    "fillStyle": "solid",
                    "strokeWidth": 2,
                    "roughness": 1,
                    "opacity": 100,
                    "roundness": {"type": 3},
                    "boundElements": [{"type": "text", "id": f"fallback_text_{idx}"}],
                    "isDeleted": False,
                    "customData": {"atlas": {"type": "fallback_architecture"}},
                }
            )
            nodes.append(
                {
                    "id": f"fallback_text_{idx}",
                    "type": "text",
                    "x": 12,
                    "y": idx * 140 + 30,
                    "width": 276,
                    "height": 24,
                    "text": str(label)[:48],
                    "originalText": str(label)[:48],
                    "fontSize": 16,
                    "fontFamily": 1,
                    "textAlign": "center",
                    "verticalAlign": "middle",
                    "baseline": 15,
                    "containerId": f"fallback_{idx}",
                    "strokeColor": "#243127",
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 1,
                    "roughness": 1,
                    "opacity": 100,
                    "groupIds": [],
                    "isDeleted": False,
                }
            )
            if idx > 0:
                nodes.append(
                    {
                        "id": f"fallback_edge_{idx}",
                        "type": "arrow",
                        "x": 150,
                        "y": (idx - 1) * 140 + 86,
                        "width": 0,
                        "height": 54,
                        "angle": 0,
                        "strokeColor": "#738177",
                        "backgroundColor": "transparent",
                        "fillStyle": "solid",
                        "strokeWidth": 1,
                        "strokeStyle": "solid",
                        "roughness": 1,
                        "opacity": 100,
                        "points": [[0, 0], [0, 54]],
                        "startBinding": {"elementId": f"fallback_{idx - 1}", "focus": 0, "gap": 4},
                        "endBinding": {"elementId": f"fallback_{idx}", "focus": 0, "gap": 4},
                        "startArrowhead": None,
                        "endArrowhead": "arrow",
                        "isDeleted": False,
                        "customData": {"atlas": {"type": "fallback_architecture"}},
                    }
                )
        return nodes

    @staticmethod
    def _bbox(elements: List[Dict[str, Any]]) -> Tuple[float, float, float, float]:
        xs: List[float] = []
        ys: List[float] = []
        rights: List[float] = []
        bottoms: List[float] = []
        for el in elements:
            x = float(el.get("x") or 0)
            y = float(el.get("y") or 0)
            w = float(el.get("width") or 0)
            h = float(el.get("height") or 0)
            xs.append(x)
            ys.append(y)
            rights.append(x + w)
            bottoms.append(y + h)
        return min(xs, default=0), min(ys, default=0), max(rights, default=1), max(bottoms, default=1)

    # ------------------------------------------------------------------
    # Knowledge cards
    # ------------------------------------------------------------------
    def _knowledge_cards(
        self,
        project_id: str,
        reqs: List[Any],
        decs: List[Any],
        questions: List[Any],
        constraints: List[Any],
    ) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []

        for item in decs[:3]:
            cards.append(self._knowledge_item("DECISION", item))
        for item in reqs[:3]:
            cards.append(self._knowledge_item("REQUIREMENT", item))
        for item in questions[:1]:
            cards.append(self._knowledge_item("OPEN QUESTION", item))
        for item in constraints[:1]:
            cards.append(self._knowledge_item("CONSTRAINT", item))
        return cards

    def _knowledge_item(self, category: str, item: Any) -> Dict[str, Any]:
        if isinstance(item, dict):
            title = item.get("title") or item.get("name") or category.title()
            content = item.get("content") or item.get("text") or item.get("detail") or title
            evidence_ids = item.get("evidence_ids") or []
        else:
            title = category.title()
            content = str(item)
            evidence_ids = []
        return {
            "category": category,
            "title": str(title)[:70],
            "content": str(content)[:120],
            "evidence_ids": evidence_ids[:4] if isinstance(evidence_ids, list) else [],
        }

    def _note_card(
        self,
        project_id: str,
        note: Dict[str, Any],
        x: float,
        y: float,
    ) -> List[Dict[str, Any]]:
        """Render a knowledge note as a human-readable visual context explainer.

        The diagram is deliberately explanatory rather than decorative:
        the middle node anchors the exact recorded title, the surrounding
        stages explain how a human should interpret the context, and the
        source content remains readable underneath.
        """
        category = str(note["category"]).upper()
        style_key = {
            "DECISION": "decision",
            "REQUIREMENT": "requirement",
            "ACTION": "action",
            "CONSTRAINT": "risk",
            "OPEN QUESTION": "question",
        }.get(category, "decision")
        style = STYLE[style_key]
        key = f"{category}:{note['title']}:{note['content']}"
        card_id = self._id(project_id, f"note:{hashlib.sha1(key.encode()).hexdigest()[:10]}")

        custom = {
            "atlas": {
                "type": "knowledge_note",
                "project_id": project_id,
                "category": category,
                "evidence_ids": note["evidence_ids"],
            }
        }

        elements: List[Dict[str, Any]] = [
            self._rect(
                card_id,
                x,
                y,
                NOTE_W,
                NOTE_H,
                style,
                opacity=100,
                roundness=3,
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:category",
                x + 18,
                y + 12,
                NOTE_W - 36,
                17,
                f"{'◆' if category == 'DECISION' else '✓' if category == 'REQUIREMENT' else '?' if category == 'OPEN QUESTION' else '⚠'}  {category}",
                10,
                style["text"],
                bold=True,
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:title",
                x + 18,
                y + 33,
                NOTE_W - 36,
                30,
                note["title"][:70],
                15,
                "#1f2937",
                bold=True,
                custom_data=custom,
            ),
        ]

        elements.extend(
            self._place_mini_visual(
                project_id=project_id,
                note_id=card_id,
                stages=self._mini_visual_stages(
                    category,
                    note["title"],
                    note["content"],
                ),
                x=x + 18,
                y=y + 65,
                width=MINI_W,
                height=MINI_H,
                custom_data=custom,
            )
        )

        elements.extend([
            self._text(
                f"{card_id}:meaning_label",
                x + 18,
                y + 199,
                68,
                14,
                "MEANING",
                8,
                style["text"],
                bold=True,
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:content",
                x + 88,
                y + 198,
                NOTE_W - 106,
                34,
                note["content"][:150],
                10,
                "#4b5563",
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:evidence",
                x + 18,
                y + 230,
                NOTE_W - 36,
                13,
                (
                    f"Evidence linked: {len(note['evidence_ids'])}"
                    if note["evidence_ids"]
                    else "Source: project state knowledge"
                ),
                8,
                "#768176",
                custom_data=custom,
            ),
        ])
        return elements

    def _mini_visual_stages(
        self,
        category: str,
        title: str,
        content: str,
    ) -> List[Dict[str, str]]:
        """Return four compact stages that make the note's meaning explicit."""
        key = category.upper()
        anchor = (title or key.title()).strip()[:16] or key.title()

        if key == "DECISION":
            return [
                {"label": "CONTEXT", "detail": "What led here"},
                {"label": "CHOICE", "detail": anchor},
                {"label": "BASIS", "detail": "Recorded rationale"},
                {"label": "IMPACT", "detail": "Shapes the system"},
            ]
        if key == "REQUIREMENT":
            return [
                {"label": "NEED", "detail": "User / business need"},
                {"label": "REQUIREMENT", "detail": anchor},
                {"label": "BEHAVIOUR", "detail": "System response"},
                {"label": "CHECK", "detail": "How we validate"},
            ]
        if key == "ACTION":
            return [
                {"label": "INPUT", "detail": "Starting signal"},
                {"label": "ACTION", "detail": anchor},
                {"label": "VERIFY", "detail": "Expected evidence"},
                {"label": "OUTCOME", "detail": "Result to capture"},
            ]
        if key == "OPEN QUESTION":
            return [
                {"label": "KNOWN", "detail": "Current evidence"},
                {"label": "GAP", "detail": anchor},
                {"label": "EVIDENCE", "detail": "What is missing"},
                {"label": "RESOLVE", "detail": "Answer / decision"},
            ]
        if key == "CONSTRAINT":
            return [
                {"label": "BOUNDARY", "detail": "What cannot move"},
                {"label": "LIMIT", "detail": anchor},
                {"label": "RESPONSE", "detail": "Design around it"},
                {"label": "IMPACT", "detail": "Affected behaviour"},
            ]
        return [
            {"label": "CONTEXT", "detail": "Recorded evidence"},
            {"label": "KNOWLEDGE", "detail": anchor},
            {"label": "INTERPRET", "detail": "Human reading"},
            {"label": "OUTCOME", "detail": "Next understanding"},
        ]

    def _place_mini_visual(
        self,
        project_id: str,
        note_id: str,
        stages: List[Dict[str, str]],
        x: float,
        y: float,
        width: float,
        height: float,
        custom_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Render a four-stage visual narrative with strong hierarchy and arrows."""
        stage_gap = 22
        box_width = max(76, int((width - stage_gap * 3) / 4))
        box_height = 86
        box_y = y + 20
        elements: List[Dict[str, Any]] = []

        for index, stage in enumerate(stages[:4]):
            bx = x + index * (box_width + stage_gap)
            stage_data = {
                **custom_data,
                "atlas": {
                    **custom_data.get("atlas", {}),
                    "type": "knowledge_mini_visual",
                    "stage": index,
                    "label": stage["label"],
                },
            }
            highlight = index == 1
            box_style = {
                "stroke": custom_data.get("atlas", {}).get("category") and "#8da095" or "#b8c6bb",
                "background": "#ffffff",
            }
            if highlight:
                box_style = {
                    "stroke": "#355a3c",
                    "background": "#f7fbf7",
                }

            elements.append(
                self._rect(
                    self._id(note_id, f"mini_box_{index}"),
                    bx,
                    box_y,
                    box_width,
                    box_height,
                    box_style,
                    opacity=100,
                    roundness=3,
                    custom_data=stage_data,
                )
            )
            elements.append(
                self._text(
                    self._id(note_id, f"mini_label_{index}"),
                    bx + 8,
                    box_y + 12,
                    box_width - 16,
                    18,
                    stage["label"],
                    8,
                    "#66736a",
                    bold=True,
                    custom_data=stage_data,
                )
            )
            elements.append(
                self._text(
                    self._id(note_id, f"mini_detail_{index}"),
                    bx + 8,
                    box_y + 34,
                    box_width - 16,
                    36,
                    stage["detail"][:28],
                    10 if highlight else 9,
                    "#1f2937" if highlight else "#475569",
                    bold=highlight,
                    custom_data=stage_data,
                )
            )

            if index < 3:
                ax = bx + box_width + 4
                ay = box_y + box_height / 2
                elements.append(
                    self._arrow(
                        self._id(note_id, f"mini_arrow_{index}"),
                        ax,
                        ay,
                        ax + stage_gap - 8,
                        ay,
                        custom_data=stage_data,
                        stroke_color="#627267",
                        stroke_width=2,
                    )
                )

        elements.append(
            self._text(
                self._id(note_id, "mini_caption"),
                x,
                y + height - 4,
                width,
                14,
                self._visual_caption(custom_data.get("atlas", {}).get("category", "")),
                8,
                "#7b877d",
                bold=False,
                custom_data=custom_data,
            )
        )
        return elements

    @staticmethod
    def _visual_caption(category: str) -> str:
        captions = {
            "DECISION": "Read left → right: situation → choice → basis → consequence.",
            "REQUIREMENT": "Read left → right: need → behaviour → validation.",
            "ACTION": "Read left → right: trigger → action → evidence → outcome.",
            "OPEN QUESTION": "Read left → right: known facts → gap → needed evidence → resolution.",
            "CONSTRAINT": "Read left → right: boundary → limit → design response → impact.",
        }
        return captions.get(
            str(category).upper(),
            "Read left → right to understand the recorded context.",
        )

    @staticmethod
    def _arrow(
        element_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        custom_data: Optional[Dict[str, Any]] = None,
        stroke_color: str = "#738177",
        stroke_width: int = 1,
    ) -> Dict[str, Any]:
        return {
            "id": element_id,
            "type": "arrow",
            "x": x1,
            "y": y1,
            "width": max(1.0, x2 - x1),
            "height": max(1.0, y2 - y1),
            "angle": 0,
            "strokeColor": stroke_color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": stroke_width,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "points": [[0, 0], [max(1.0, x2 - x1), y2 - y1]],
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "isDeleted": False,
            "customData": custom_data or {},
        }

    # ------------------------------------------------------------------
    # Unknown Context column
    # ------------------------------------------------------------------
    def _unknown_column(
        self,
        items: List[UnknownContextItem],
        db: Session,
        workspace_id: str,
    ) -> List[Dict[str, Any]]:
        origin_x = ATLAS_PADDING_X
        height = max(900, NOTES_Y + 700)
        scene: List[Dict[str, Any]] = [
            self._rect(
                self._id("unknown", "frame"),
                origin_x,
                ATLAS_PADDING_Y,
                COLUMN_WIDTH,
                height,
                {"stroke": "#d9c7a3", "background": "#fffdf8"},
                opacity=100,
                roundness=3,
            ),
            self._rect(
                self._id("unknown", "header"),
                origin_x + 22,
                ATLAS_PADDING_Y + 22,
                COLUMN_WIDTH - 44,
                HEADER_H - 28,
                {"stroke": "#b45309", "background": "#fff7e8"},
                opacity=100,
                roundness=3,
            ),
            self._text(
                self._id("unknown", "title"),
                origin_x + 46,
                ATLAS_PADDING_Y + 42,
                COLUMN_WIDTH - 92,
                34,
                "CONTEXT INBOX",
                25,
                "#78350f",
                bold=True,
                custom_data={"atlas": {"type": "unknown_context"}},
            ),
            self._text(
                self._id("unknown", "subtitle"),
                origin_x + 46,
                ATLAS_PADDING_Y + 84,
                COLUMN_WIDTH - 92,
                24,
                "Human attention only when the AI cannot safely place evidence",
                12,
                "#8a6a41",
                custom_data={"atlas": {"type": "unknown_context"}},
            ),
        ]
        scene.append(
            self._text(
                self._id("unknown", "count"),
                origin_x + 46,
                ATLAS_PADDING_Y + 113,
                COLUMN_WIDTH - 92,
                18,
                f"{len(items)} pending",
                11,
                "#9a7b4c",
                bold=True,
                custom_data={"atlas": {"type": "unknown_context"}},
            )
        )

        card_y = ARCH_Y
        for item in items[:6]:
            matches = (
                db.query(PossibleProjectMatch)
                .filter(PossibleProjectMatch.unknown_item_id == item.id)
                .order_by(PossibleProjectMatch.created_at.desc())
                .limit(2)
                .all()
            )
            suggestion_names: List[str] = []
            for match in matches:
                p = db.query(Project).filter(Project.id == match.candidate_project_id).first()
                if p:
                    suggestion_names.append(p.name)

            scene.extend(
                self._unknown_card(
                    item=item,
                    x=origin_x + ARCH_X_PAD,
                    y=card_y,
                    suggestions=suggestion_names,
                )
            )
            card_y += UNKNOWN_CARD_H + 26

        if not items:
            scene.append(
                self._text(
                    self._id("unknown", "empty"),
                    origin_x + ARCH_X_PAD,
                    ARCH_Y + 40,
                    ARCH_W,
                    50,
                    "All source evidence is placed.",
                    18,
                    "#66736a",
                    custom_data={"atlas": {"type": "unknown_context_empty"}},
                )
            )
        return scene

    def _unknown_card(
        self,
        item: UnknownContextItem,
        x: float,
        y: float,
        suggestions: List[str],
    ) -> List[Dict[str, Any]]:
        content = (item.content or "(no text)").replace("\n", " ").strip()
        suggestion_text = ", ".join(suggestions[:2]) if suggestions else "No confident match"
        custom = {
            "atlas": {
                "type": "unknown_item",
                "item_id": item.id,
                "suggestions": suggestions[:2],
            }
        }
        card_id = self._id("unknown", f"item:{item.id}")
        return [
            self._rect(
                card_id,
                x,
                y,
                ARCH_W,
                UNKNOWN_CARD_H,
                STYLE["unknown"],
                opacity=100,
                roundness=3,
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:category",
                x + 18,
                y + 16,
                ARCH_W - 36,
                18,
                f"⚠  {item.source.upper()}  •  NEEDS CONTEXT",
                10,
                STYLE["unknown"]["text"],
                bold=True,
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:content",
                x + 18,
                y + 42,
                ARCH_W - 36,
                45,
                content[:220],
                12,
                "#3e3426",
                bold=True,
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:suggested",
                x + 18,
                y + 94,
                ARCH_W - 36,
                20,
                f"Possible project: {suggestion_text}",
                10,
                "#7b6650",
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:id",
                x + 18,
                y + 116,
                ARCH_W - 36,
                15,
                f"{item.id}  •  human decides",
                9,
                "#98826a",
                custom_data=custom,
            ),
        ]

    # ------------------------------------------------------------------
    # Excalidraw primitive builders
    # ------------------------------------------------------------------
    @staticmethod
    def _id(scope: str, key: str) -> str:
        digest = hashlib.sha1(f"{scope}:{key}".encode()).hexdigest()[:16]
        return f"atlas_{digest}"

    @staticmethod
    def _rect(
        element_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
        style: Dict[str, str],
        opacity: int = 100,
        roundness: int = 3,
        custom_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": element_id,
            "type": "rectangle",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": style["stroke"],
            "backgroundColor": style["background"],
            "fillStyle": "solid",
            "strokeWidth": 1,
            "roughness": 1,
            "opacity": opacity,
            "roundness": {"type": roundness},
            "boundElements": [],
            "isDeleted": False,
            "customData": custom_data or {},
        }

    @staticmethod
    def _text(
        element_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
        text: str,
        font_size: float,
        stroke_color: str,
        bold: bool = False,
        custom_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": element_id,
            "type": "text",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "text": text,
            "originalText": text,
            "fontSize": font_size,
            "fontFamily": 1,
            "textAlign": "left",
            "verticalAlign": "top",
            "lineHeight": 1.25,
            "baseline": max(10, int(font_size)),
            "autoResize": False,
            "strokeColor": stroke_color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "groupIds": [],
            "isDeleted": False,
            "customData": custom_data or {},
        }

    @staticmethod
    def _line(
        element_id: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> Dict[str, Any]:
        return {
            "id": element_id,
            "type": "line",
            "x": x1,
            "y": y1,
            "width": max(1.0, x2 - x1),
            "height": max(1.0, y2 - y1),
            "angle": 0,
            "strokeColor": "#d7ddd6",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": stroke_width,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "points": [[0, 0], [x2 - x1, y2 - y1]],
            "isDeleted": False,
        }

    @staticmethod
    def _project_intent(state: Optional[ProjectState]) -> str:
        if not state:
            return ""
        vision = (state.vision or "").replace("\\n", " ").strip()
        return " ".join(vision.split())[:150]

    @staticmethod
    def _project_domain(project: Project, db: Session, tenant_id: str) -> str:
        try:
            from app.models.project_semantic_profile import ProjectSemanticProfile
            profile = (
                db.query(ProjectSemanticProfile)
                .filter(
                    ProjectSemanticProfile.project_id == project.id,
                    ProjectSemanticProfile.tenant_id == tenant_id,
                )
                .first()
            )
            if profile and profile.domain:
                return profile.domain[:110]
        except Exception:
            pass
        description = (project.description or "").strip().splitlines()
        for line in description:
            clean = line.strip()
            if clean:
                return clean[:110]
        return ""

    @staticmethod
    def _json_list(raw: Optional[str]) -> List[Any]:
        try:
            value = json.loads(raw or "[]")
            return value if isinstance(value, list) else []
        except Exception:
            return []

    @staticmethod
    def _json_dict(raw: Optional[str]) -> Dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}


# Backwards-compatible name for callers that prefer a workspace-oriented service.
ProjectAtlasService = WorkspaceAtlasService
