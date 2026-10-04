import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.exceptions import SynesisException
from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship

logger = logging.getLogger(__name__)

#: Deterministic style table. The model chooses a node_type; the compiler
#: owns every visual property (colour, size, spacing, typography).
NODE_STYLES: Dict[str, Dict[str, Any]] = {
    "client": {"background": "#e0f2fe", "stroke": "#0369a1"},
    "service": {"background": "#ffffff", "stroke": "#0f766e"},
    "datastore": {"background": "#fef3c7", "stroke": "#d97706"},
    "actor": {"background": "#ede9fe", "stroke": "#6d28d9"},
    "decision": {"background": "#ecfdf5", "stroke": "#16a34a"},
    "requirement": {"background": "#eef2ff", "stroke": "#4338ca"},
    "infrastructure": {"background": "#e0e7ff", "stroke": "#3730a3"},
    "queue": {"background": "#fce7f3", "stroke": "#be185d"},
    "external": {"background": "#e0f2fe", "stroke": "#0369a1"},
    "group": {"background": "#f6f7f5", "stroke": "#68706a"},
    "note": {"background": "#fef9c3", "stroke": "#ca8a04"},
}
DEFAULT_STYLE = NODE_STYLES["service"]

NODE_WIDTH = 220
NODE_HEIGHT = 92
H_GAP = 110
V_GAP = 70
COLUMN_WRAP = 4
BASE_X = 80
BASE_Y = 80


class ExcalidrawCompileError(SynesisException):
    """Raised when a VisualPlan cannot be compiled into a valid scene."""


class ExcalidrawCompiler:
    """Deterministic VisualPlan -> Excalidraw scene compiler.

    Owns coordinates, spacing, alignment, routing, dimensions, collision
    avoidance, typography, grouping and viewport fitting. Produces stable
    element ids so recompiling an unchanged plan is idempotent.
    """

    def compile(self, plan: VisualPlan) -> List[Dict[str, Any]]:
        if not plan.nodes:
            raise ExcalidrawCompileError("VisualPlan contains no nodes to compile.")

        # Ground the plan before it becomes geometry. A node that cites no
        # evidence is the model reasoning rather than reporting, so it is
        # refused here. Previously any node survived, which is how a single
        # WhatsApp sentence produced a seven-node architecture whose contents
        # came from the model's imagination.
        grounded_nodes = [n for n in plan.nodes if n.evidence_ids]
        if not grounded_nodes:
            raise ExcalidrawCompileError(
                "VisualPlan has no evidence-backed nodes; refusing to compile an ungrounded diagram."
            )
        if len(grounded_nodes) < len(plan.nodes):
            logger.info(
                "visual_plan_nodes_dropped_ungrounded: kept=%d dropped=%d",
                len(grounded_nodes),
                len(plan.nodes) - len(grounded_nodes),
            )
        plan = plan.model_copy(update={"nodes": grounded_nodes})
        valid_node_ids = {n.id for n in grounded_nodes}
        # An edge is only meaningful if both endpoints survived grounding.
        plan.relationships = [
            r
            for r in plan.relationships
            if r.source in valid_node_ids and r.target in valid_node_ids
        ]

        positions = self._layout(plan)
        elements: List[Dict[str, Any]] = []
        node_element_ids: Dict[str, str] = {}

        elements.extend(self._group_backdrops(plan, positions))

        for node in plan.nodes:
            x, y = positions[node.id]
            style = NODE_STYLES.get(node.node_type, DEFAULT_STYLE)
            rect_id = f"node_{node.id}"
            text_id = f"label_{node.id}"
            node_element_ids[node.id] = rect_id
            # Fix 5: inferred nodes are drawn dashed so a reader can tell a
            # stated component from a modelled one at a glance.
            inferred = (node.support_type or "inferred") != "explicit"

            node_shape = {
                "actor": "ellipse",
                "decision": "diamond",
                "requirement": "rectangle",
                "service": "rectangle",
                "client": "rectangle",
                "datastore": "rectangle",
                "queue": "rectangle",
                "external": "rectangle",
                "infrastructure": "rectangle",
                "group": "rectangle",
                "note": "rectangle",
            }.get(node.node_type, "rectangle")

            elements.append(
                {
                    "id": rect_id,
                    "type": node_shape,
                    "x": x,
                    "y": y,
                    "width": NODE_WIDTH,
                    "height": NODE_HEIGHT,
                    "angle": 0,
                    "strokeStyle": "dashed" if inferred else "solid",
                    "strokeColor": style["stroke"],
                    "backgroundColor": style["background"],
                    "fillStyle": "solid",
                    "strokeWidth": 2 if node.emphasis == "primary" else 1,
                    "roughness": 1,
                    "opacity": 60 if node.emphasis == "muted" else 100,
                    "groupIds": [node.group] if node.group else [],
                    "roundness": {"type": 3},
                    "boundElements": [{"type": "text", "id": text_id}],
                    "isDeleted": False,
                    "customData": {
                        "visual": {
                            "semantic_id": node.id,
                            "node_type": node.node_type,
                            "group": node.group,
                            "emphasis": node.emphasis,
                            "evidence_ids": list(node.evidence_ids or [])[:4],
                            "support_type": "explicit" if not inferred else "inferred",
                        }
                    },
                }
            )

            # Adaptive font and height for clean text rendering
            is_long = len(node.label) > 22 or "\n" in node.label
            font_sz = 13 if is_long or node.node_type == "note" else 15
            txt_h = 36 if is_long else 24
            txt_y = y + (NODE_HEIGHT - txt_h) / 2
            txt_color = "#713f12" if node.node_type == "note" else "#1e1e1e"

            elements.append(
                {
                    "id": text_id,
                    "type": "text",
                    "x": x + 12,
                    "y": txt_y,
                    "width": NODE_WIDTH - 24,
                    "height": txt_h,
                    "text": node.label,
                    "originalText": node.label,
                    "fontSize": font_sz,
                    "fontFamily": 1,
                    "textAlign": "center",
                    "verticalAlign": "middle",
                    "containerId": rect_id,
                    "lineHeight": 1.25,
                    "baseline": 12 if is_long else 14,
                    "autoResize": False,
                    "strokeColor": txt_color,
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 1,
                    "strokeStyle": "solid",
                    "roughness": 1,
                    "opacity": 100,
                    "angle": 0,
                    "groupIds": [],
                    "isDeleted": False,
                }
            )
            # Annotations render as small captions under the node.
            for idx, annotation in enumerate(node.annotations[:2]):
                elements.append(
                    {
                        "id": f"annotation_{node.id}_{idx}",
                        "type": "text",
                        "x": x + 12,
                        "y": y + NODE_HEIGHT + 6 + idx * 16,
                        "width": NODE_WIDTH - 24,
                        "height": 16,
                        "text": annotation,
                        "originalText": annotation,
                        "fontSize": 11,
                        "fontFamily": 1,
                        "textAlign": "center",
                        "verticalAlign": "middle",
                        "lineHeight": 1.25,
                        "baseline": 10,
                        "autoResize": True,
                        "strokeColor": "#555555",
                        "backgroundColor": "transparent",
                        "fillStyle": "solid",
                        "strokeWidth": 1,
                        "strokeStyle": "solid",
                        "roughness": 1,
                        "opacity": 100,
                        "angle": 0,
                        "groupIds": [],
                        "isDeleted": False,
                        # An annotation is a factual claim about the node, so it
                        # inherits the node's provenance. Without this the text
                        # on the canvas was the one element with no traceable
                        # source, which is exactly where invented detail landed.
                        "customData": {
                            "visual": {
                                "type": "node_annotation",
                                "semantic_id": node.id,
                                "evidence_ids": list(node.evidence_ids or [])[:4],
                                "support_type": "explicit" if not inferred else "inferred",
                            }
                        },
                    }
                )

        for index, rel in enumerate(plan.relationships):
            src = node_element_ids.get(rel.source)
            dst = node_element_ids.get(rel.target)
            if not src or not dst:
                logger.warning(
                    "visual_plan_relationship_dropped: %s -> %s (unknown node)",
                    rel.source,
                    rel.target,
                )
                continue
            src_pos = positions.get(rel.source)
            dst_pos = positions.get(rel.target)
            arrow = self._arrow(rel, src, dst, index, src_pos, dst_pos)
            arrow.setdefault("customData", {})["visual"] = {
                "semantic_source": rel.source,
                "semantic_target": rel.target,
                "evidence_ids": list(rel.evidence_ids or [])[:4],
                "support_type": rel.support_type or "inferred",
            }
            # An edge the model only inferred is drawn dashed, matching nodes.
            if (rel.support_type or "inferred") != "explicit":
                arrow["strokeStyle"] = "dashed"
            elements.append(arrow)
            if rel.label:
                elements.append(self._edge_label(rel, arrow, index))

        # First-class architectural sticky notes from plan.notes
        #
        # Notes are grounded and ordered. An entry may be a plain string or a
        # dict carrying {"text", "kind", "order", "evidence_ids"}. Entries with
        # a declared-but-empty evidence_ids list are dropped, because a note
        # that cannot cite a source is an invention rather than a directive.
        # Remaining notes are sorted by kind rank then explicit order, so the
        # reader gets a stable sequence instead of whatever order the model
        # happened to return.
        NOTE_KIND_RANK = {
            "decision": 0,
            "requirement": 1,
            "directive": 2,
            "action": 3,
            "risk": 4,
            "assumption": 5,
            "note": 6,
        }
        NOTE_KIND_ICON = {
            "decision": "✅",
            "requirement": "📋",
            "directive": "⚡",
            "action": "⚡",
            "risk": "⚠️",
            "assumption": "💡",
            "note": "📌",
        }

        def _normalise_note(raw: Any) -> Optional[Dict[str, Any]]:
            if isinstance(raw, dict):
                text = str(raw.get("text") or raw.get("content") or "").strip()
                kind = str(raw.get("kind") or "note").strip().lower()
                evidence = raw.get("evidence_ids")
                # Declared evidence but empty => ungrounded, refuse to render.
                if evidence is not None and not evidence:
                    logger.info("visual_plan_note_dropped_ungrounded: %s", text[:60])
                    return None
                try:
                    order = int(raw.get("order", 0))
                except (TypeError, ValueError):
                    order = 0
                if not text:
                    return None
                return {
                    "text": text,
                    "kind": kind,
                    "order": order,
                    "evidence_ids": [str(e) for e in (evidence or [])][:4],
                }
            text = str(raw or "").strip()
            if not text:
                return None
            return {"text": text, "kind": "note", "order": 0, "evidence_ids": []}

        grounded_notes: List[Dict[str, Any]] = []
        for raw in plan.notes or []:
            normalised = _normalise_note(raw)
            if normalised:
                grounded_notes.append(normalised)
        grounded_notes.sort(
            key=lambda n: (NOTE_KIND_RANK.get(n["kind"], 9), n["order"], n["text"])
        )

        if grounded_notes:
            max_y = max(pos[1] for pos in positions.values())
            notes_hdr_y = max_y + NODE_HEIGHT + 45
            # Stable across process restarts. The builtin hash() is salted per
            # interpreter (PYTHONHASHSEED), which made this id change on every
            # restart and showed up as a spurious remove+add in compare mode.
            title_digest = hashlib.sha1((plan.title or "plan").encode("utf-8")).hexdigest()[:12]
            header_id = f"lbl_notes_hdr_{title_digest}"
            elements.append(
                {
                    "id": header_id,
                    "type": "text",
                    "x": BASE_X,
                    "y": notes_hdr_y,
                    "width": 500,
                    "height": 22,
                    "text": "📌 ARCHITECTURAL NOTES & DIRECTIVES",
                    "originalText": "📌 ARCHITECTURAL NOTES & DIRECTIVES",
                    "fontSize": 13,
                    "fontFamily": 1,
                    "textAlign": "left",
                    "verticalAlign": "top",
                    "containerId": None,
                    "lineHeight": 1.25,
                    "baseline": 12,
                    "autoResize": True,
                    "strokeColor": "#854d0e",
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 1,
                    "strokeStyle": "solid",
                    "roughness": 1,
                    "opacity": 100,
                    "angle": 0,
                    "groupIds": [],
                    "isDeleted": False,
                }
            )

            cards_start_y = notes_hdr_y + 32
            NOTE_W = 320
            NOTE_H = 110
            NOTE_GAP_X = 35
            NOTE_GAP_Y = 25
            NOTES_PER_ROW = 3

            for n_idx, note in enumerate(grounded_notes[:6]):
                col = n_idx % NOTES_PER_ROW
                row = n_idx // NOTES_PER_ROW
                nx = BASE_X + col * (NOTE_W + NOTE_GAP_X)
                ny = cards_start_y + row * (NOTE_H + NOTE_GAP_Y)

                icon = NOTE_KIND_ICON.get(note["kind"], "📌")
                clean_text = note["text"]
                if not any(clean_text.startswith(p) for p in ("📌", "💡", "⚡", "📋", "⚠️", "✅")):
                    clean_text = f"{icon} {clean_text}"

                card_id = f"sticky_note_{n_idx}"
                text_id = f"sticky_text_{n_idx}"

                elements.append(
                    {
                        "id": card_id,
                        "type": "rectangle",
                        "x": nx,
                        "y": ny,
                        "width": NOTE_W,
                        "height": NOTE_H,
                        "angle": 0,
                        "strokeColor": "#ca8a04",
                        "backgroundColor": "#fef9c3",
                        "fillStyle": "solid",
                        "strokeWidth": 2,
                        "roughness": 1,
                        "opacity": 100,
                        "groupIds": ["architectural_notes"],
                        "roundness": {"type": 3},
                        "boundElements": [{"type": "text", "id": text_id}],
                        "isDeleted": False,
                        # Every rendered element carries its provenance, so a
                        # sticky note can be traced back to the evidence that
                        # prompted it like any node.
                        "customData": {
                            "visual": {
                                "type": "architectural_note",
                                "kind": note["kind"],
                                "evidence_ids": note["evidence_ids"],
                                "support_type": "explicit" if note["evidence_ids"] else "inferred",
                            }
                        },
                    }
                )
                elements.append(
                    {
                        "id": text_id,
                        "type": "text",
                        "x": nx + 14,
                        "y": ny + 12,
                        "width": NOTE_W - 28,
                        "height": NOTE_H - 24,
                        "text": clean_text,
                        "originalText": clean_text,
                        "fontSize": 12,
                        "fontFamily": 1,
                        "textAlign": "left",
                        "verticalAlign": "top",
                        "containerId": card_id,
                        "lineHeight": 1.35,
                        "baseline": 12,
                        "autoResize": True,
                        "strokeColor": "#713f12",
                        "backgroundColor": "transparent",
                        "fillStyle": "solid",
                        "strokeWidth": 1,
                        "strokeStyle": "solid",
                        "roughness": 1,
                        "opacity": 100,
                        "angle": 0,
                        "groupIds": ["architectural_notes"],
                        "isDeleted": False,
                    }
                )

        self.validate_scene(elements)
        return elements

    def _group_backdrops(
        self,
        plan: VisualPlan,
        positions: Dict[str, Tuple[float, float]],
    ) -> List[Dict[str, Any]]:
        """Render subtle swimlanes so related components read as one system layer."""
        grouped: Dict[str, List[VisualNode]] = {}
        for node in plan.nodes:
            group = (node.group or "").strip() or "main"
            grouped.setdefault(group, []).append(node)

        if len(grouped) <= 1:
            return []

        palette = [
            ("#f8fafc", "#cbd5e1"),
            ("#f0fdf4", "#bbdbc4"),
            ("#eff6ff", "#bfdbfe"),
            ("#fff7ed", "#fed7aa"),
            ("#fdf4ff", "#e9d5ff"),
        ]
        output: List[Dict[str, Any]] = []

        for index, (group, nodes) in enumerate(grouped.items()):
            coords = [positions[n.id] for n in nodes if n.id in positions]
            if not coords:
                continue

            min_x = min(p[0] for p in coords) - 28
            min_y = min(p[1] for p in coords) - 28
            max_x = max(p[0] for p in coords) + NODE_WIDTH + 28
            max_y = max(p[1] for p in coords) + NODE_HEIGHT + 42
            bg, stroke = palette[index % len(palette)]
            label = group.replace("_", " ").strip().upper()
            # A lane inherits the provenance of its members: if every node in
            # it is stated, the lane is solid; if any is inferred the lane is
            # dashed so the reader can see the layer is partly modelled.
            group_evidence: List[str] = []
            for n in nodes:
                for e in (n.evidence_ids or []):
                    if e not in group_evidence:
                        group_evidence.append(e)
            group_support = (
                "explicit"
                if nodes and all((n.support_type or "inferred") == "explicit" for n in nodes)
                else "inferred"
            )

            output.append({
                "id": f"group_backdrop_{index}_{group}",
                "type": "rectangle",
                "x": min_x,
                "y": min_y,
                "width": max_x - min_x,
                "height": max_y - min_y,
                "angle": 0,
                "strokeStyle": "solid" if group_support == "explicit" else "dashed",
                "strokeColor": stroke,
                "backgroundColor": bg,
                "fillStyle": "solid",
                "strokeWidth": 1,
                "roughness": 1,
                "opacity": 45,
                "roundness": {"type": 3},
                "boundElements": [],
                "isDeleted": False,
                "customData": {
                    "visual": {
                        "type": "architecture_group",
                        "group": group,
                        "evidence_ids": group_evidence[:6],
                        "support_type": group_support,
                        "node_count": len(nodes),
                    }
                },
            })
            output.append({
                "id": f"group_label_{index}_{group}",
                "type": "text",
                "x": min_x + 14,
                "y": min_y + 8,
                "width": max_x - min_x - 28,
                "height": 16,
                "text": label,
                "originalText": label,
                "fontSize": 9,
                "fontFamily": 1,
                "textAlign": "left",
                "verticalAlign": "top",
                "lineHeight": 1.15,
                "baseline": 9,
                "autoResize": False,
                "strokeColor": "#66736a",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "roughness": 1,
                "opacity": 100,
                "angle": 0,
                "groupIds": [],
                "isDeleted": False,
                "customData": {"visual": {"type": "architecture_group_label", "group": group}},
            })

        return output

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _layout(self, plan: VisualPlan) -> Dict[str, Tuple[float, float]]:
        """Deterministic group-aware layout with readable horizontal component flow."""
        positions: Dict[str, Tuple[float, float]] = {}
        grouped: Dict[str, List[VisualNode]] = {}

        for node in plan.nodes:
            group = (node.group or "").strip() or "main"
            grouped.setdefault(group, []).append(node)

        if len(grouped) > 1:
            lane_y = BASE_Y
            for _, group_nodes in grouped.items():
                rows = max(1, (len(group_nodes) + COLUMN_WRAP - 1) // COLUMN_WRAP)
                for index, node in enumerate(group_nodes):
                    col = index % COLUMN_WRAP
                    row = index // COLUMN_WRAP
                    x = BASE_X + col * (NODE_WIDTH + H_GAP)
                    y = lane_y + row * (NODE_HEIGHT + V_GAP)
                    positions[node.id] = (x, y)
                lane_y += rows * (NODE_HEIGHT + V_GAP) + 64
            return positions

        horizontal = plan.layout_direction == "horizontal"
        for index, node in enumerate(plan.nodes):
            if horizontal:
                col = index % COLUMN_WRAP
                row = index // COLUMN_WRAP
                x = BASE_X + col * (NODE_WIDTH + H_GAP)
                y = BASE_Y + row * (NODE_HEIGHT + V_GAP)
            else:
                row = index
                x = BASE_X
                y = BASE_Y + row * (NODE_HEIGHT + V_GAP)
            positions[node.id] = (x, y)
        return positions

    def _edge_label(
        self,
        rel: VisualRelationship,
        arrow: Dict[str, Any],
        index: int,
    ) -> Dict[str, Any]:
        """Render relationship labels as small readable chips, not paragraphs."""
        points = arrow.get("points") or [[0, 0], [0, 0]]
        end = points[-1] if isinstance(points[-1], list) else [0, 0]
        dx = float(end[0] or 0)
        dy = float(end[1] or 0)
        x = float(arrow.get("x") or 0) + dx / 2 - 48
        y = float(arrow.get("y") or 0) + dy / 2 - 12
        label = str(rel.label).strip()[:34]
        return {
            "id": f"edge_label_{index}_{rel.source}_{rel.target}",
            "type": "text",
            "x": x,
            "y": y,
            "width": 96,
            "height": 20,
            "text": label,
            "originalText": label,
            "fontSize": 9,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "lineHeight": 1.15,
            "baseline": 9,
            "autoResize": False,
            "strokeColor": "#425248",
            "backgroundColor": "#ffffff",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "roughness": 1,
            "opacity": 90,
            "angle": 0,
            "groupIds": [],
            "isDeleted": False,
            "customData": {
                "visual": {
                    "type": "relationship_label",
                    "source": rel.source,
                    "target": rel.target,
                }
            },
        }

    def _arrow(
        self,
        rel,
        source_element_id: str,
        target_element_id: str,
        index: int,
        source_pos: Optional[Tuple[float, float]] = None,
        target_pos: Optional[Tuple[float, float]] = None,
    ) -> Dict[str, Any]:
        if source_pos and target_pos:
            src_x, src_y = source_pos
            dst_x, dst_y = target_pos
            if dst_x > src_x + 10:
                start_x = src_x + NODE_WIDTH
                start_y = src_y + NODE_HEIGHT / 2
                end_x = dst_x
                end_y = dst_y + NODE_HEIGHT / 2
            elif dst_x < src_x - 10:
                start_x = src_x + NODE_WIDTH / 2
                start_y = src_y + NODE_HEIGHT
                end_x = dst_x + NODE_WIDTH / 2
                end_y = dst_y
            else:
                start_x = src_x + NODE_WIDTH / 2
                start_y = src_y + NODE_HEIGHT
                end_x = dst_x + NODE_WIDTH / 2
                end_y = dst_y
            dx = end_x - start_x
            dy = end_y - start_y
            points = [[0, 0], [dx, dy]]
            width = max(1, abs(dx))
            height = max(1, abs(dy))
        else:
            start_x = 0
            start_y = 0
            width = NODE_WIDTH + H_GAP
            height = 0
            points = [[0, 0], [width, 0]]

        return {
            "id": f"edge_{index}_{rel.source}_{rel.target}",
            "type": "arrow",
            "x": start_x,
            "y": start_y,
            "width": width,
            "height": height,
            "points": points,
            "strokeColor": "#173f35",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "dashed" if rel.style == "dashed" else "solid",
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "groupIds": [],
            "startBinding": {"elementId": source_element_id, "focus": 0, "gap": 6},
            "endBinding": {"elementId": target_element_id, "focus": 0, "gap": 6},
            "endArrowhead": "arrow",
            "isDeleted": False,
            "customData": {
                "visual": {
                    "type": "relationship",
                    "source": rel.source,
                    "target": rel.target,
                    "label": rel.label,
                }
            },
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def validate_scene(elements: List[Dict[str, Any]]) -> None:
        """Guard the compiler output before it becomes a proposal."""
        if not isinstance(elements, list) or not elements:
            raise ExcalidrawCompileError("Compiled scene is empty.")
        ids = set()
        for el in elements:
            if not isinstance(el, dict):
                raise ExcalidrawCompileError("Compiled scene contains a non-object element.")
            for required in ("id", "type"):
                if not el.get(required):
                    raise ExcalidrawCompileError(
                        f"Compiled element missing required field '{required}'."
                    )
            if el["id"] in ids:
                raise ExcalidrawCompileError(f"Duplicate element id '{el['id']}'.")
            ids.add(el["id"])
            if el["type"] in ("rectangle", "text", "ellipse", "diamond"):
                if not all(k in el for k in ("x", "y", "width", "height")):
                    raise ExcalidrawCompileError(
                        f"Element '{el['id']}' is missing geometry fields."
                    )
