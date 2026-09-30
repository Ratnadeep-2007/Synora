import hashlib
import logging
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple

from app.core.exceptions import SynesisException
from app.schemas.visual_plan import VisualPlan

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
    "group": {"background": "#f6f7f5", "stroke": "#68706a"},
    "note": {"background": "#fef9c3", "stroke": "#ca8a04"},
}
DEFAULT_STYLE = NODE_STYLES["service"]

NODE_WIDTH = 220
NODE_HEIGHT = 92
H_GAP = 140
V_GAP = 90
COLUMN_WRAP = 4
GROUP_PAD_X = 36
GROUP_PAD_TOP = 44
GROUP_PAD_BOTTOM = 32
GROUP_GAP = 70
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

        positions = self._layout(plan)
        elements: List[Dict[str, Any]] = []
        node_element_ids: Dict[str, str] = {}

        # Draw subtle group frames first so the architecture reads as sections.
        group_frames = self._group_frames(plan, positions)
        elements.extend(group_frames)

        for node in plan.nodes:
            x, y = positions[node.id]
            style = NODE_STYLES.get(node.node_type, DEFAULT_STYLE)
            rect_id = f"node_{node.id}"
            text_id = f"label_{node.id}"
            node_element_ids[node.id] = rect_id

            elements.append(
                {
                    "id": rect_id,
                    "semantic_id": node.id,
                    "semantic_type": "node",
                    "type": "rectangle",
                    "x": x,
                    "y": y,
                    "width": NODE_WIDTH,
                    "height": NODE_HEIGHT,
                    "angle": 0,
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
                    "semantic_id": node.id,
                    "semantic_type": "node_label",
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
                    "autoResize": True,
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
            elements.append(self._arrow(rel, src, dst, index, src_pos, dst_pos))

        # Architectural notes remain compact; conversation history is a separate vertical stream.
        if plan.notes or plan.conversation_notes:
            max_y = max(pos[1] for pos in positions.values())
            notes_hdr_y = max_y + NODE_HEIGHT + 55

            if plan.notes:
                elements.extend(self._render_note_section(
                    header="ARCHITECTURAL NOTES",
                    notes=plan.notes[:6],
                    start_y=notes_hdr_y,
                    prefix="arch_note",
                    category_label="ARCHITECTURE",
                    width=540,
                ))
                notes_hdr_y = notes_hdr_y + 150 + min(len(plan.notes[:6]), 6) * 108

            if plan.conversation_notes:
                elements.extend(self._render_note_section(
                    header="CONVERSATION NOTES",
                    notes=plan.conversation_notes[:8],
                    start_y=notes_hdr_y,
                    prefix="conversation_note",
                    category_label="CONVERSATION",
                    width=760,
                ))


        self.validate_scene(elements)
        return elements

    def _group_frames(
        self, plan: VisualPlan, positions: Dict[str, Tuple[float, float]]
    ) -> List[Dict[str, Any]]:
        groups: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
        for node in plan.nodes:
            if node.group and node.id in positions:
                groups[node.group].append(positions[node.id])

        frames: List[Dict[str, Any]] = []
        for idx, (group_name, coords) in enumerate(sorted(groups.items())):
            min_x = min(x for x, _ in coords) - GROUP_PAD_X
            min_y = min(y for _, y in coords) - GROUP_PAD_TOP
            max_x = max(x for x, _ in coords) + NODE_WIDTH + GROUP_PAD_X
            max_y = max(y for _, y in coords) + NODE_HEIGHT + GROUP_PAD_BOTTOM
            frame_id = f"group_frame_{self._stable_token(group_name)}"
            label_id = f"group_label_{self._stable_token(group_name)}"
            frames.append({
                "id": frame_id,
                "semantic_id": frame_id,
                "semantic_type": "group_frame",
                "type": "rectangle",
                "x": min_x,
                "y": min_y,
                "width": max_x - min_x,
                "height": max_y - min_y,
                "angle": 0,
                "strokeColor": "#94a3b8",
                "backgroundColor": "#f8fafc",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "dashed",
                "roughness": 1,
                "opacity": 45,
                "roundness": {"type": 3},
                "boundElements": [{"type": "text", "id": label_id}],
                "isDeleted": False,
            })
            frames.append({
                "id": label_id,
                "semantic_id": frame_id,
                "semantic_type": "group_label",
                "type": "text",
                "x": min_x + 12,
                "y": min_y + 10,
                "width": min(420, max_x - min_x - 24),
                "height": 20,
                "text": str(group_name).upper(),
                "fontSize": 11,
                "fontFamily": 1,
                "textAlign": "left",
                "verticalAlign": "top",
                "strokeColor": "#64748b",
                "backgroundColor": "transparent",
                "lineHeight": 1.2,
                "containerId": frame_id,
                "autoResize": True,
                "isDeleted": False,
            })
        return frames

    @staticmethod
    def _stable_token(value: str) -> str:
        return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:12]

    def _render_note_section(
        self,
        header: str,
        notes: List[str],
        start_y: float,
        prefix: str,
        category_label: str,
        width: int,
    ) -> List[Dict[str, Any]]:
        elements: List[Dict[str, Any]] = []
        header_id = f"{prefix}_header"
        elements.append({
            "id": header_id,
            "semantic_id": prefix,
            "semantic_type": "note_section",
            "type": "text",
            "x": BASE_X,
            "y": start_y,
            "width": width,
            "height": 24,
            "text": header,
            "fontSize": 13,
            "fontFamily": 1,
            "textAlign": "left",
            "verticalAlign": "top",
            "strokeColor": "#475569",
            "backgroundColor": "transparent",
            "lineHeight": 1.2,
            "isDeleted": False,
        })

        note_y = start_y + 34
        note_h = 92 if category_label == "CONVERSATION" else 96
        for index, note in enumerate(notes):
            clean = str(note).strip()
            if not clean:
                continue
            token = self._stable_token(clean)
            card_id = f"{prefix}_{token}"
            text_id = f"{card_id}_text"
            meta = f"{category_label}  •  {index + 1:02d}"
            elements.append({
                "id": card_id,
                "semantic_id": card_id,
                "semantic_type": "note",
                "type": "rectangle",
                "x": BASE_X,
                "y": note_y,
                "width": width,
                "height": note_h,
                "angle": 0,
                "strokeColor": "#cbd5e1",
                "backgroundColor": "#ffffff",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "roughness": 1,
                "roundness": {"type": 3},
                "opacity": 100,
                "groupIds": [prefix],
                "boundElements": [{"type": "text", "id": text_id}],
                "isDeleted": False,
            })
            elements.append({
                "id": text_id,
                "semantic_id": card_id,
                "semantic_type": "note_text",
                "type": "text",
                "x": BASE_X + 16,
                "y": note_y + 12,
                "width": width - 32,
                "height": note_h - 24,
                "text": meta + "\n" + clean[:650],
                "fontSize": 12,
                "fontFamily": 1,
                "textAlign": "left",
                "verticalAlign": "top",
                "strokeColor": "#334155",
                "backgroundColor": "transparent",
                "lineHeight": 1.35,
                "containerId": card_id,
                "autoResize": True,
                "isDeleted": False,
            })
            note_y += note_h + 18
        return elements

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _layout(self, plan: VisualPlan) -> Dict[str, Tuple[float, float]]:
        """Deterministic dependency-aware layered layout.

        Horizontal plans use graph depth (roots -> downstream systems) rather than
        array order. Vertical plans remain chronological. Layout is stable for the
        same semantic plan.
        """
        if not plan.nodes:
            return {}

        if plan.layout_direction != "horizontal":
            return {
                node.id: (BASE_X, BASE_Y + index * (NODE_HEIGHT + V_GAP))
                for index, node in enumerate(plan.nodes)
            }

        node_ids = [node.id for node in plan.nodes]
        node_index = {node.id: i for i, node in enumerate(plan.nodes)}
        children: Dict[str, List[str]] = defaultdict(list)
        indegree: Dict[str, int] = {nid: 0 for nid in node_ids}

        for rel in plan.relationships:
            if rel.source in indegree and rel.target in indegree:
                children[rel.source].append(rel.target)
                indegree[rel.target] += 1

        depth: Dict[str, int] = {nid: 0 for nid in node_ids}
        queue = deque(sorted((nid for nid, d in indegree.items() if d == 0), key=node_index.get))

        while queue:
            src = queue.popleft()
            for dst in children.get(src, []):
                depth[dst] = max(depth.get(dst, 0), depth[src] + 1)
                indegree[dst] -= 1
                if indegree[dst] == 0:
                    queue.append(dst)

        # Cyclic/disconnected nodes remain stable and are placed in a final deterministic layer.
        max_depth = max(depth.values(), default=0)
        for nid, deg in indegree.items():
            if deg > 0:
                depth[nid] = max_depth + 1

        layers: Dict[int, List[str]] = defaultdict(list)
        for nid in node_ids:
            layers[depth[nid]].append(nid)

        positions: Dict[str, Tuple[float, float]] = {}
        for layer_idx in sorted(layers):
            ids = sorted(layers[layer_idx], key=node_index.get)
            total_height = len(ids) * NODE_HEIGHT + max(0, len(ids) - 1) * V_GAP
            y0 = BASE_Y
            for idx, nid in enumerate(ids):
                x = BASE_X + layer_idx * (NODE_WIDTH + H_GAP)
                y = y0 + idx * (NODE_HEIGHT + V_GAP)
                positions[nid] = (x, y)

        return positions

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
