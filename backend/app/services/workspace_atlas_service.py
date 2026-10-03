from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.context_resolution import PossibleProjectMatch, UnknownContextItem, UnknownItemStatus
from app.models.excalidraw import ExcalidrawArtifact
from app.models.project import Project
from app.models.project_state import ProjectState
from app.models.intelligence import CandidateKnowledge
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
NOTE_H = 286
MINI_W = NOTE_W - 36
MINI_H = 150

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
    "assumption": {"stroke": "#64748b", "background": "#f8fafc", "text": "#334155"},
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
        force: bool = False,
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

        if force or app_state.get("atlas_fingerprint") != fingerprint:
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
                    "memory": {
                        "knowledge": db.query(CandidateKnowledge).filter(CandidateKnowledge.project_id == p.id).count(),
                        "requirements": self._state_count(p.id, db, "requirements"),
                        "decisions": self._state_count(p.id, db, "decisions"),
                        "architecture": self._state_count(p.id, db, "architecture"),
                        "constraints": self._state_count(p.id, db, "constraints"),
                        "assumptions": self._state_count(p.id, db, "assumptions"),
                        "open_questions": self._state_count(p.id, db, "open_questions"),
                        "updated_at": self._state_updated_at(p.id, db),
                    },
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
    def _state_count(project_id: str, db: Session, field: str) -> int:
        row = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        if not row:
            return 0
        column = {
            "requirements": "requirements_json",
            "decisions": "decisions_json",
            "architecture": "architecture_json",
            "constraints": "constraints_json",
            "assumptions": "assumptions_json",
            "open_questions": "open_questions_json",
        }[field]
        return len(WorkspaceAtlasService._json_list(getattr(row, column, "[]")))

    @staticmethod
    def _state_updated_at(project_id: str, db: Session) -> Optional[str]:
        row = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        return row.updated_at.isoformat() if row and row.updated_at else None

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
        recent_knowledge = (
            db.query(CandidateKnowledge)
            .filter(CandidateKnowledge.project_id == project.id)
            .order_by(CandidateKnowledge.created_at.desc())
            .limit(20)
            .all()
        )
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
        assumptions = self._json_list(state.assumptions_json if state else "[]")

        memory_counts = {
            "knowledge": len(recent_knowledge),
            "requirements": len(reqs),
            "decisions": len(decs),
            "architecture": len(self._json_list(state.architecture_json if state else "[]")),
            "constraints": len(constraints),
            "assumptions": len(assumptions),
            "open_questions": len(questions),
            "updated_at": state.updated_at.isoformat() if state and state.updated_at else None,
        }

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
                f"MEMORY v{state_version}   •   {len(reqs)} requirements   •   {len(decs)} decisions   •   {len(questions)} questions   •   {len(constraints)} constraints   •   {len(assumptions)} assumptions",
                10,
                "#66736a",
                custom_data={"atlas": {"type": "project_metrics", "project_id": project.id}},
            )
        )

        # --------------------------------------------------------------
        # Dynamic Architecture Placement
        # --------------------------------------------------------------
        arch_y = ATLAS_PADDING_Y + HEADER_H + 22
        arch_w = COLUMN_WIDTH - (ARCH_X_PAD * 2)
        scene.append(
            self._section_label(
                self._id(project.id, "architecture_label"),
                origin_x + ARCH_X_PAD,
                arch_y - 18,
                arch_w,
                "ARCHITECTURE  •  VISUAL SYSTEM MAP",
            )
        )
        scene.extend(
            self._architecture_legend(
                project.id,
                origin_x + ARCH_X_PAD,
                arch_y + 6,
                arch_w,
            )
        )

        architecture_elements = self._architecture_from_artifact(artifact)
        if not architecture_elements:
            architecture_elements = self._fallback_architecture(state)

        if architecture_elements:
            bbox = self._bbox(architecture_elements)
            min_x, min_y, max_x, max_y = bbox
            raw_w = max(1.0, max_x - min_x)
            raw_h = max(1.0, max_y - min_y)
            # Scale horizontally to fit architecture width; keep height proportional
            scale = min(arch_w / raw_w, 1.0)
            scaled_h = raw_h * scale
            arch_h = max(300.0, scaled_h)

            scene.append(
                self._rect(
                    self._id(project.id, "architecture_surface"),
                    origin_x + ARCH_X_PAD,
                    arch_y + 58,
                    arch_w,
                    arch_h + 44,
                    {"stroke": "#dfe7e1", "background": "#fbfcfb"},
                    opacity=100,
                    roundness=3,
                    custom_data={"atlas": {"type": "architecture_surface", "project_id": project.id}},
                )
            )
            scene.append(
                self._text(
                    self._id(project.id, "architecture_flow_hint"),
                    origin_x + ARCH_X_PAD + 18,
                    arch_y + 69,
                    arch_w - 36,
                    16,
                    "FLOW  •  follow arrows from entry → processing → state → external outcomes",
                    8,
                    "#7a877c",
                    bold=True,
                    custom_data={"atlas": {"type": "architecture_flow_hint", "project_id": project.id}},
                )
            )
            scene.extend(
                self._place_architecture(
                    architecture_elements,
                    origin_x + ARCH_X_PAD,
                    arch_y + 94,
                    arch_w,
                    arch_h,
                    project.id,
                )
            )
            arch_bottom = arch_y + 94 + arch_h
        else:
            arch_bottom = arch_y + 40

        # --------------------------------------------------------------
        # Dynamic Context & Knowledge Cards (Infinite Vertical Growth)
        # --------------------------------------------------------------
        notes_y = arch_bottom + 50
        scene.append(
            self._text(
                self._id(project.id, "notes_header"),
                origin_x + ARCH_X_PAD,
                notes_y,
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
                notes_y + 34,
                origin_x + COLUMN_WIDTH - ARCH_X_PAD,
                notes_y + 34,
            )
        )

        notes = self._knowledge_cards(
            project.id,
            reqs=reqs,
            decs=decs,
            questions=questions,
            constraints=constraints,
            assumptions=assumptions,
        )

        cards_start_y = notes_y + 52
        if notes:
            for i, note in enumerate(notes):
                row = i // 2
                col = i % 2
                nx = origin_x + ARCH_X_PAD + col * (NOTE_W + NOTE_GAP)
                ny = cards_start_y + row * (NOTE_H + NOTE_GAP)
                scene.extend(self._note_card(project.id, note, nx, ny))
            total_rows = (len(notes) + 1) // 2
            content_bottom = cards_start_y + total_rows * (NOTE_H + NOTE_GAP)
        else:
            scene.append(
                self._text(
                    self._id(project.id, "notes_empty"),
                    origin_x + ARCH_X_PAD,
                    cards_start_y + 10,
                    COLUMN_WIDTH - (ARCH_X_PAD * 2),
                    30,
                    "No context notes recorded yet.",
                    12,
                    "#738177",
                    custom_data={"atlas": {"type": "knowledge_empty", "project_id": project.id}},
                )
            )
            content_bottom = cards_start_y + 50

        # Frame height expands dynamically with the full content of the column
        column_bottom = content_bottom + 70
        column_height = max(900, int(round(column_bottom - ATLAS_PADDING_Y)))

        frame_rect = self._rect(
            frame_id,
            origin_x,
            ATLAS_PADDING_Y,
            COLUMN_WIDTH,
            column_height,
            STYLE["frame"],
            opacity=100,
            roundness=3,
        )

        return [frame_rect] + scene

    def _column_height(self, state: Optional[ProjectState]) -> int:
        reqs = len(self._json_list(state.requirements_json if state else "[]"))
        decs = len(self._json_list(state.decisions_json if state else "[]"))
        questions = len(self._json_list(state.open_questions_json if state else "[]"))
        constraints = len(self._json_list(state.constraints_json if state else "[]"))
        assumptions = len(self._json_list(state.assumptions_json if state else "[]"))
        total = reqs + decs + questions + constraints + assumptions
        rows = max(1, (total + 1) // 2) if total > 0 else 1
        return ARCH_Y + ARCH_H + 70 + 52 + rows * (NOTE_H + NOTE_GAP) + 80

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
        scale = min(target_w / width, 1.0)
        if height * scale > target_h:
            scale = target_h / height
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

    def _architecture_legend(
        self,
        project_id: str,
        x: float,
        y: float,
        width: float,
    ) -> List[Dict[str, Any]]:
        items = [
            ("EXPERIENCE", "#ede9fe", "#6d28d9"),
            ("LOGIC", "#ffffff", "#0f766e"),
            ("DATA", "#fef3c7", "#d97706"),
            ("INTEGRATIONS", "#e0f2fe", "#0369a1"),
        ]
        gap = 12
        item_w = int((width - gap * 3) / 4)
        out: List[Dict[str, Any]] = []
        for idx, (label, bg, stroke) in enumerate(items):
            bx = x + idx * (item_w + gap)
            out.append(self._rect(
                self._id(project_id, f"arch_legend_box_{idx}"),
                bx, y, item_w, 28,
                {"stroke": stroke, "background": bg},
                custom_data={"atlas": {"type": "architecture_legend"}},
            ))
            out.append(self._text(
                self._id(project_id, f"arch_legend_text_{idx}"),
                bx + 8, y + 7, item_w - 16, 14,
                label, 8, stroke, bold=True,
                custom_data={"atlas": {"type": "architecture_legend"}},
            ))
        out.append(self._text(
            self._id(project_id, "arch_legend_hint"),
            x, y + 34, width, 15,
            "Follow arrows to read request, event, and data flow. Text inside nodes stays minimal; important meaning belongs in labels and notes below.",
            8, "#738177",
            custom_data={"atlas": {"type": "architecture_legend"}},
        ))
        return out

    def _fallback_architecture(
        self,
        state: Optional[ProjectState],
    ) -> List[Dict[str, Any]]:
        """Create a layered visual architecture when no authored diagram exists."""
        if not state:
            return []
        architecture = self._json_list(state.architecture_json)
        if not architecture:
            return []

        tier_names = {
            "client": "EXPERIENCE",
            "frontend": "EXPERIENCE",
            "actor": "EXPERIENCE",
            "service": "CORE SERVICES",
            "api": "CORE SERVICES",
            "backend": "CORE SERVICES",
            "datastore": "DATA",
            "database": "DATA",
            "infrastructure": "INFRASTRUCTURE",
            "external": "EXTERNAL SYSTEMS",
        }
        tier_order = ["EXPERIENCE", "CORE SERVICES", "DATA", "INFRASTRUCTURE", "EXTERNAL SYSTEMS"]
        grouped: Dict[str, List[str]] = {tier: [] for tier in tier_order}

        for item in architecture[:18]:
            if isinstance(item, dict):
                label = str(
                    item.get("component") or item.get("name") or item.get("title") or "Component"
                ).strip()
                raw_type = str(
                    item.get("type") or item.get("layer") or item.get("node_type") or "service"
                ).lower()
            else:
                label = str(item).strip()
                raw_type = "service"
            tier = tier_names.get(raw_type, "CORE SERVICES")
            if label:
                grouped[tier].append(label[:44])

        elements: List[Dict[str, Any]] = []
        tier_y = 0
        populated = []
        for tier in tier_order:
            labels = grouped[tier]
            if not labels:
                continue
            populated.append(tier)
            group_id = f"fallback_group_{tier.lower().replace(' ', '_')}"
            group_w = min(1000, max(760, 240 + len(labels) * 180))
            elements.append({
                "id": group_id,
                "type": "rectangle",
                "x": 0, "y": tier_y, "width": group_w, "height": 126,
                "angle": 0,
                "strokeColor": "#c6d0c8",
                "backgroundColor": "#f8faf8",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "roughness": 1,
                "opacity": 100,
                "roundness": {"type": 3},
                "boundElements": [],
                "isDeleted": False,
                "customData": {"atlas": {"type": "architecture_tier", "tier": tier}},
            })
            elements.append({
                "id": f"{group_id}:label",
                "type": "text",
                "x": 18, "y": tier_y + 11, "width": group_w - 36, "height": 18,
                "text": tier, "originalText": tier,
                "fontSize": 10, "fontFamily": 1, "textAlign": "left",
                "verticalAlign": "top", "baseline": 10, "autoResize": False,
                "strokeColor": "#66736a", "backgroundColor": "transparent",
                "fillStyle": "solid", "strokeWidth": 1, "roughness": 1,
                "opacity": 100, "isDeleted": False,
                "customData": {"atlas": {"type": "architecture_tier_label", "tier": tier}},
            })

            box_gap = 18
            box_w = max(150, min(240, int((group_w - 36 - max(0, len(labels)-1)*box_gap) / max(1, len(labels)))))
            for idx, label in enumerate(labels):
                bx = 18 + idx * (box_w + box_gap)
                node_id = f"{group_id}:node:{idx}"
                elements.append({
                    "id": node_id,
                    "type": "rectangle",
                    "x": bx, "y": tier_y + 40, "width": box_w, "height": 68,
                    "angle": 0,
                    "strokeColor": "#46745a",
                    "backgroundColor": "#ffffff",
                    "fillStyle": "solid",
                    "strokeWidth": 2 if idx == 0 else 1,
                    "roughness": 1, "opacity": 100,
                    "roundness": {"type": 3},
                    "boundElements": [{"type": "text", "id": f"{node_id}:text"}],
                    "isDeleted": False,
                    "customData": {"atlas": {"type": "architecture_node", "tier": tier}},
                })
                elements.append({
                    "id": f"{node_id}:text",
                    "type": "text",
                    "x": bx + 10, "y": tier_y + 53,
                    "width": box_w - 20, "height": 40,
                    "text": label, "originalText": label,
                    "fontSize": 12 if len(label) > 26 else 14,
                    "fontFamily": 1, "textAlign": "center", "verticalAlign": "middle",
                    "baseline": 12, "autoResize": False,
                    "strokeColor": "#26362b", "backgroundColor": "transparent",
                    "fillStyle": "solid", "strokeWidth": 1, "roughness": 1,
                    "opacity": 100, "isDeleted": False,
                    "customData": {"atlas": {"type": "architecture_node_label", "tier": tier}},
                })
            tier_y += 154

        # Show the system's vertical story explicitly.
        for idx in range(1, len(populated)):
            y = 154 * idx - 28
            elements.append({
                "id": f"fallback_flow_{idx}",
                "type": "arrow",
                "x": 500, "y": y, "width": 0, "height": 34, "angle": 0,
                "strokeColor": "#6b7b70", "backgroundColor": "transparent",
                "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid",
                "roughness": 1, "opacity": 100, "points": [[0,0],[0,34]],
                "startArrowhead": None, "endArrowhead": "arrow",
                "isDeleted": False,
                "customData": {"atlas": {"type": "architecture_flow"}},
            })
        return elements

    @staticmethod
    def _section_label(
        element_id: str,
        x: float,
        y: float,
        width: float,
        text: str,
    ) -> Dict[str, Any]:
        return {
            "id": element_id,
            "type": "text",
            "x": x, "y": y, "width": width, "height": 18,
            "text": text, "originalText": text,
            "fontSize": 9, "fontFamily": 1, "textAlign": "left",
            "verticalAlign": "top", "baseline": 9, "autoResize": False,
            "strokeColor": "#6b7b70", "backgroundColor": "transparent",
            "fillStyle": "solid", "strokeWidth": 1, "roughness": 1,
            "opacity": 100, "isDeleted": False,
            "customData": {"atlas": {"type": "section_label"}},
        }

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
        assumptions: Optional[List[Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Select context records for the visual note layer (infinite vertical layout)."""
        cards: List[Dict[str, Any]] = []

        for item in decs[:2]:
            cards.append(self._knowledge_item("DECISION", item))
        for item in reqs[:2]:
            cards.append(self._knowledge_item("REQUIREMENT", item))
        for item in constraints[:1]:
            cards.append(self._knowledge_item("CONSTRAINT", item))
        for item in (assumptions or [])[:1]:
            cards.append(self._knowledge_item("ASSUMPTION", item))
        for item in questions[:2]:
            cards.append(self._knowledge_item("OPEN QUESTION", item))

        if limit is not None:
            return cards[:limit]
        return cards[:8]

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
            "title": str(title)[:58],
            "content": str(content)[:180],
            "evidence_ids": evidence_ids[:4] if isinstance(evidence_ids, list) else [],
        }

    def _note_card(
        self,
        project_id: str,
        note: Dict[str, Any],
        x: float,
        y: float,
    ) -> List[Dict[str, Any]]:
        """Render a visual-first micro-dashboard for one project knowledge item."""
        category = str(note["category"]).upper()
        style_key = {
            "DECISION": "decision",
            "REQUIREMENT": "requirement",
            "ACTION": "action",
            "CONSTRAINT": "risk",
            "OPEN QUESTION": "question",
            "ASSUMPTION": "assumption",
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
                f"{card_id}:human_question",
                x + NOTE_W - 260,
                y + 12,
                242,
                17,
                self._human_question(category),
                8,
                "#748077",
                bold=False,
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:title",
                x + 18,
                y + 33,
                NOTE_W - 36,
                30,
                note["title"][:58],
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
                y=y + 64,
                width=MINI_W,
                height=MINI_H,
                custom_data=custom,
            )
        )

        takeaway = self._takeaway_text(note["content"])
        elements.extend([
            self._text(
                f"{card_id}:takeaway_label",
                x + 18,
                y + 226,
                76,
                14,
                "TAKEAWAY",
                8,
                style["text"],
                bold=True,
                custom_data=custom,
            ),
            self._text(
                f"{card_id}:takeaway",
                x + 96,
                y + 223,
                NOTE_W - 114,
                38,
                takeaway,
                10,
                "#35413a",
                bold=True,
                custom_data=custom,
            ),
            self._line(
                f"{card_id}:footer_line",
                x + 18,
                y + 264,
                x + NOTE_W - 18,
                y + 264,
            ),
            self._text(
                f"{card_id}:evidence",
                x + 18,
                y + 269,
                NOTE_W - 36,
                13,
                (
                    f"Evidence linked • {len(note['evidence_ids'])} source"
                    + ("s" if len(note["evidence_ids"]) != 1 else "")
                    if note["evidence_ids"]
                    else "Project-state knowledge • no direct evidence link"
                ),
                8,
                "#768176",
                custom_data=custom,
            ),
        ])
        return elements

    @staticmethod
    def _human_question(category: str) -> str:
        questions = {
            "DECISION": "Why this choice?",
            "REQUIREMENT": "What must happen?",
            "ACTION": "What should happen next?",
            "CONSTRAINT": "What must not break?",
            "OPEN QUESTION": "What is still unknown?",
            "ASSUMPTION": "What are we trusting?",
        }
        return questions.get(str(category).upper(), "Why does this matter?")

    @staticmethod
    def _takeaway_text(content: str) -> str:
        clean = " ".join((content or "").replace("\n", " ").split())
        return clean[:180] or "No additional explanation recorded."

    @staticmethod
    def _distinct_clauses(title: str, content: str) -> List[str]:
        """
        Split a knowledge record into clauses that are genuinely distinct from
        one another and from the title.

        A single-sentence candidate (e.g. "Add an agentic layer for NLP
        embedding.") carries no situation / behaviour / validation detail. The
        previous renderer filled every stage from the same string, so BEHAVIOUR
        simply repeated REQUIREMENT. Returning only clauses that differ from the
        title lets the caller mark unsupported stages explicitly instead of
        echoing the requirement back at the reader.
        """
        def norm(value: Any) -> str:
            return " ".join(str(value or "").replace("\n", " ").split()).strip().lower()

        title_norm = norm(title)
        raw = " ".join(str(content or "").replace("\n", " ").split())
        if not raw:
            return []

        parts = [p.strip() for p in re.split(r"(?<=[.;!?])\s+|,\s+(?=[a-z])", raw) if p.strip()]
        if len(parts) < 2:
            parts = [raw]

        seen = {title_norm}
        clauses: List[str] = []
        for part in parts:
            key = norm(part)
            # Skip anything that only restates the title or an earlier clause.
            if not key or key in seen:
                continue
            if key.startswith(title_norm) or title_norm.startswith(key):
                continue
            seen.add(key)
            clauses.append(part[:34])
        return clauses

    def _mini_visual_stages(
        self,
        category: str,
        title: str,
        content: str,
    ) -> List[Dict[str, str]]:
        """
        Turn one knowledge record into a compact visual narrative.

        Each stage is filled only from evidence that actually supports it.
        Stages with no supporting clause render as "Not specified" rather than
        repeating the requirement or inventing acceptance criteria.
        """
        key = category.upper()
        anchor = (title or key.title()).strip()[:18] or key.title()
        clauses = self._distinct_clauses(title, content)
        missing = "Not specified"

        def take(index: int) -> str:
            return clauses[index] if index < len(clauses) else missing

        if key == "DECISION":
            return [
                {"label": "SITUATION", "detail": take(0), "shape": "ellipse"},
                {"label": "CHOICE", "detail": anchor, "shape": "diamond"},
                {"label": "REASON", "detail": take(1), "shape": "rectangle"},
                {"label": "CONSEQUENCE", "detail": take(2), "shape": "ellipse"},
            ]
        if key == "REQUIREMENT":
            return [
                {"label": "NEED", "detail": take(0), "shape": "ellipse"},
                {"label": "REQUIREMENT", "detail": anchor, "shape": "rectangle"},
                {"label": "BEHAVIOUR", "detail": take(1), "shape": "rectangle"},
                {"label": "VALIDATE", "detail": take(2), "shape": "ellipse"},
            ]
        if key == "ACTION":
            return [
                {"label": "TRIGGER", "detail": take(0), "shape": "ellipse"},
                {"label": "ACTION", "detail": anchor, "shape": "rectangle"},
                {"label": "EVIDENCE", "detail": take(1), "shape": "diamond"},
                {"label": "OUTCOME", "detail": take(2), "shape": "ellipse"},
            ]
        if key == "OPEN QUESTION":
            return [
                {"label": "KNOWN", "detail": take(0), "shape": "ellipse"},
                {"label": "GAP", "detail": anchor, "shape": "diamond"},
                {"label": "NEED", "detail": take(1), "shape": "rectangle"},
                {"label": "RESOLVE", "detail": take(2), "shape": "ellipse"},
            ]
        if key == "CONSTRAINT":
            return [
                {"label": "BOUNDARY", "detail": take(0), "shape": "ellipse"},
                {"label": "LIMIT", "detail": anchor, "shape": "diamond"},
                {"label": "DESIGN", "detail": take(1), "shape": "rectangle"},
                {"label": "IMPACT", "detail": take(2), "shape": "ellipse"},
            ]
        if key == "ASSUMPTION":
            return [
                {"label": "PREMISE", "detail": take(0), "shape": "ellipse"},
                {"label": "ASSUME", "detail": anchor, "shape": "diamond"},
                {"label": "DEPEND", "detail": take(1), "shape": "rectangle"},
                {"label": "VERIFY", "detail": take(2), "shape": "ellipse"},
            ]
        return [
            {"label": "CONTEXT", "detail": take(0), "shape": "ellipse"},
            {"label": "KNOWLEDGE", "detail": anchor, "shape": "rectangle"},
            {"label": "INTERPRET", "detail": take(1), "shape": "rectangle"},
            {"label": "OUTCOME", "detail": take(2), "shape": "ellipse"},
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
        box_height = 94
        box_y = y + 18
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
                    "shape": stage.get("shape", "rectangle"),
                },
            }
            highlight = index == 1
            category = str(custom_data.get("atlas", {}).get("category", "")).upper()
            palette = {
                "DECISION": ("#15803d", "#f0fdf4"),
                "REQUIREMENT": ("#4338ca", "#eef2ff"),
                "ACTION": ("#166534", "#f0fdf4"),
                "CONSTRAINT": ("#c2410c", "#fff7ed"),
                "OPEN QUESTION": ("#2563eb", "#eff6ff"),
                "ASSUMPTION": ("#64748b", "#f8fafc"),
            }
            accent, accent_bg = palette.get(category, ("#355a3c", "#f7fbf7"))
            box_style = {
                "stroke": accent if highlight else "#b8c6bb",
                "background": accent_bg if highlight else "#ffffff",
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
                    element_type=stage.get("shape", "rectangle"),
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
                    stage["detail"][:34],
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
                y + height - 8,
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
            "DECISION": "Situation → choice → reason → consequence",
            "REQUIREMENT": "Need → behaviour → validation",
            "ACTION": "Trigger → action → evidence → outcome",
            "OPEN QUESTION": "Known → gap → evidence → resolution",
            "CONSTRAINT": "Boundary → design response → impact",
            "ASSUMPTION": "Premise → dependency → verification",
        }
        return captions.get(str(category).upper(), "Context → meaning → outcome")

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
        card_y = ARCH_Y
        cards_scene: List[Dict[str, Any]] = []

        for item in items:
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

            cards_scene.extend(
                self._unknown_card(
                    item=item,
                    x=origin_x + ARCH_X_PAD,
                    y=card_y,
                    suggestions=suggestion_names,
                )
            )
            card_y += UNKNOWN_CARD_H + 26

        if not items:
            cards_scene.append(
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
            card_y = ARCH_Y + 130

        column_bottom = card_y + 40
        column_height = max(900, int(round(column_bottom - ATLAS_PADDING_Y)))

        frame_rect = self._rect(
            self._id("unknown", "frame"),
            origin_x,
            ATLAS_PADDING_Y,
            COLUMN_WIDTH,
            column_height,
            {"stroke": "#d9c7a3", "background": "#fffdf8"},
            opacity=100,
            roundness=3,
        )

        header_scene: List[Dict[str, Any]] = [
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
            ),
        ]

        return [frame_rect] + header_scene + cards_scene

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
        element_type: str = "rectangle",
    ) -> Dict[str, Any]:
        return {
            "id": element_id,
            "type": element_type,
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
        stroke_width: int = 1,
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
