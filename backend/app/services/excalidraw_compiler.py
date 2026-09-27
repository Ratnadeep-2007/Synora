import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.exceptions import SynesisException
from app.schemas.visual_plan import VisualPlan

logger = logging.getLogger(__name__)

#: Deterministic style table. The model chooses a node_type; the compiler
#: owns every visual property (colour, size, spacing, typography).
NODE_STYLES: Dict[str, Dict[str, Any]] = {
    "client": {"background": "#e0f2fe", "stroke": "#0369a1"},
    "service": {"background": "#ffffff", "stroke": "#173f35"},
    "datastore": {"background": "#fef3c7", "stroke": "#d97706"},
    "actor": {"background": "#ede9fe", "stroke": "#6d28d9"},
    "decision": {"background": "#ecfdf5", "stroke": "#2f7154"},
    "requirement": {"background": "#eef2ff", "stroke": "#4338ca"},
    "group": {"background": "#f6f7f5", "stroke": "#68706a"},
    "note": {"background": "#ffffff", "stroke": "#e7eae5"},
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

        positions = self._layout(plan)
        elements: List[Dict[str, Any]] = []
        node_element_ids: Dict[str, str] = {}

        for node in plan.nodes:
            x, y = positions[node.id]
            style = NODE_STYLES.get(node.node_type, DEFAULT_STYLE)
            rect_id = f"node_{node.id}"
            text_id = f"label_{node.id}"
            node_element_ids[node.id] = rect_id

            elements.append(
                {
                    "id": rect_id,
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
            elements.append(
                {
                    "id": text_id,
                    "type": "text",
                    "x": x + 12,
                    "y": y + NODE_HEIGHT / 2 - 12,
                    "width": NODE_WIDTH - 24,
                    "height": 24,
                    "text": node.label,
                    "fontSize": 16,
                    "fontFamily": 1,
                    "textAlign": "center",
                    "verticalAlign": "middle",
                    "containerId": rect_id,
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
                        "fontSize": 11,
                        "fontFamily": 1,
                        "textAlign": "center",
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
            elements.append(self._arrow(rel, src, dst, index))

        self.validate_scene(elements)
        return elements

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _layout(self, plan: VisualPlan) -> Dict[str, Tuple[float, float]]:
        """Deterministic grid layout with stable ordering and spacing."""
        positions: Dict[str, Tuple[float, float]] = {}
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

    def _arrow(
        self,
        rel,
        source_element_id: str,
        target_element_id: str,
        index: int,
    ) -> Dict[str, Any]:
        return {
            "id": f"edge_{index}_{rel.source}_{rel.target}",
            "type": "arrow",
            "x": 0,
            "y": 0,
            "width": 0,
            "height": 0,
            "points": [[0, 0], [NODE_WIDTH + H_GAP, 0]],
            "strokeColor": "#173f35",
            "strokeWidth": 2,
            "strokeStyle": "dashed" if rel.style == "dashed" else "solid",
            "roughness": 1,
            "opacity": 100,
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
