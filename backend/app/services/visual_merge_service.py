import copy
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from app.schemas.visual_patch import (
    PatchSafetyClassification,
    VisualNoteCategory,
    VisualPatch,
    VisualPatchOpType,
    VisualPatchOperation,
)
from app.services.excalidraw_compiler import (
    DEFAULT_STYLE,
    NODE_HEIGHT,
    NODE_STYLES,
    NODE_WIDTH,
)

logger = logging.getLogger(__name__)

NOTE_CATEGORY_STYLES: Dict[str, Dict[str, str]] = {
    "DECISION": {"background": "#ecfdf5", "stroke": "#16a34a", "text": "#14532d"},
    "REQUIREMENT": {"background": "#eef2ff", "stroke": "#4338ca", "text": "#312e81"},
    "ACTION": {"background": "#f0fdf4", "stroke": "#15803d", "text": "#166534"},
    "RISK": {"background": "#fef2f2", "stroke": "#dc2626", "text": "#991b1b"},
    "CONSTRAINT": {"background": "#fff7ed", "stroke": "#ea580c", "text": "#9a3412"},
    "INTEGRATION": {"background": "#fdf4ff", "stroke": "#c026d3", "text": "#86198f"},
    "OPEN_QUESTION": {"background": "#eff6ff", "stroke": "#2563eb", "text": "#1e40af"},
    "ARCHITECTURE_PRINCIPLE": {"background": "#f8fafc", "stroke": "#475569", "text": "#1e293b"},
    "CONVERSATION": {"background": "#ffffff", "stroke": "#94a3b8", "text": "#334155"},
}


class VisualMergeService:
    """Three-Way Visual Merge Engine for Excalidraw scenes.

    BASE is the common ancestor, USER is the current local state, and AI PATCH
    contains semantic changes. User edits are preserved on semantic conflicts.
    """

    _CONCEPT_ALIASES = {
        "kds": "kitchen display system",
        "kitchen display": "kitchen display system",
        "pos": "pos integration service",
        "qr ordering": "table qr ordering",
        "table qr": "table qr ordering",
        "ordering app": "ordering web app",
        "order app": "ordering web app",
    }

    @classmethod
    def _canonical_concept_key(cls, value: Any) -> str:
        import re
        normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
        normalized = cls._CONCEPT_ALIASES.get(normalized, normalized)
        return normalized
    """Three-Way Visual Merge Engine for Excalidraw scenes.

    Inputs:
      - BASE REVISION: The visual state the patch was generated against.
      - USER SCENE: The current canvas state (which may contain user positioning, sizing, manual edits).
      - AI PATCH: The desired semantic changes (ADD_NODE, UPDATE_NODE, ADD_EDGE, ADD_NOTE).

    Guarantees:
      1. User-repositioned elements NEVER have their coordinates silently reset.
      2. AI-generated additions are positioned adjacent to related nodes with collision avoidance.
      3. Semantic identity prevents duplicate nodes (e.g. KDS + KDS2).
      4. Safe non-destructive merge: user-created components are never silently destroyed.
    """

    def merge(
        self,
        base_elements: List[Dict[str, Any]],
        user_elements: List[Dict[str, Any]],
        patch: VisualPatch,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        """Perform 3-way merge returning (merged_scene, applied_operations, conflicts)."""
        conflicts: List[str] = []
        applied_ops: List[Dict[str, Any]] = []

        # BASE is the common ancestor; USER is the current local state.
        base_map = {
            str(el["id"]): copy.deepcopy(el)
            for el in base_elements
            if isinstance(el, dict) and el.get("id")
        }
        element_map: Dict[str, Dict[str, Any]] = {}
        for el in user_elements:
            if isinstance(el, dict) and el.get("id"):
                element_map[str(el["id"])] = copy.deepcopy(el)

        def semantic_signature(el: Optional[Dict[str, Any]]) -> str:
            if not el:
                return ""
            return json.dumps(
                {
                    "type": el.get("type"),
                    "text": el.get("text"),
                    "semantic_id": el.get("semantic_id"),
                    "semantic_type": el.get("semantic_type"),
                    "startBinding": el.get("startBinding"),
                    "endBinding": el.get("endBinding"),
                },
                sort_keys=True,
                default=str,
            )

        def user_changed_target(target_id: str) -> bool:
            base_el = base_map.get(target_id)
            user_el = element_map.get(target_id)
            if base_el is None:
                return False
            if user_el is None:
                return True
            return semantic_signature(base_el) != semantic_signature(user_el)

        # Build index of existing semantic labels and node rectangles
        label_to_id: Dict[str, str] = {}
        for el in element_map.values():
            if el.get("type") == "text" and el.get("text"):
                clean_lbl = self._canonical_concept_key(el["text"])
                label_to_id[clean_lbl] = str(el["id"])
            elif el.get("type") == "rectangle" and "node_" in str(el.get("id", "")):
                # Index by node ID suffix
                suffix = self._canonical_concept_key(str(el["id"]).replace("node_", ""))
                label_to_id[suffix] = str(el["id"])

        # Occupied bounding boxes for collision avoidance
        occupied_boxes: List[Tuple[float, float, float, float]] = []
        for el in element_map.values():
            if el.get("type") in ("rectangle", "text", "diamond", "ellipse"):
                x = float(el.get("x") or 0)
                y = float(el.get("y") or 0)
                w = float(el.get("width") or NODE_WIDTH)
                h = float(el.get("height") or NODE_HEIGHT)
                occupied_boxes.append((x, y, x + w, y + h))

        # Process each operation in the patch
        for op in patch.operations:
            op_dict = op.model_dump()
            try:
                if op.op_type == VisualPatchOpType.ADD_NODE:
                    self._apply_add_node(op, element_map, label_to_id, occupied_boxes, applied_ops, conflicts)
                elif op.op_type == VisualPatchOpType.UPDATE_NODE:
                    target = op.target_id if op.target_id.startswith("node_") else f"node_{op.target_id}"
                    if user_changed_target(target):
                        conflicts.append(f"AI update skipped because the user changed or removed {target} after the patch base.")
                        continue
                    self._apply_update_node(op, element_map, label_to_id, applied_ops, conflicts)
                elif op.op_type == VisualPatchOpType.REMOVE_NODE:
                    target = op.target_id if op.target_id.startswith("node_") else f"node_{op.target_id}"
                    if user_changed_target(target):
                        conflicts.append(f"AI removal skipped because the user changed or removed {target} after the patch base.")
                        continue
                    self._apply_remove_node(op, element_map, patch.safety_classification, applied_ops, conflicts)
                elif op.op_type == VisualPatchOpType.ADD_EDGE:
                    self._apply_add_edge(op, element_map, label_to_id, applied_ops, conflicts)
                elif op.op_type == VisualPatchOpType.ADD_NOTE:
                    self._apply_add_note(op, element_map, occupied_boxes, applied_ops, conflicts)
                elif op.op_type in (VisualPatchOpType.UPDATE_NOTE, VisualPatchOpType.REMOVE_NOTE):
                    self._apply_note_mutation(op, element_map, applied_ops, conflicts)
                else:
                    applied_ops.append(op_dict)
            except Exception as exc:
                logger.warning("visual_patch_op_error: op=%s error=%s", op.op_type, exc)
                conflicts.append(f"Failed to apply {op.op_type} on {op.target_id}: {exc}")

        # Assemble merged scene preserving user order and appending additions
        merged_scene: List[Dict[str, Any]] = list(element_map.values())
        return merged_scene, applied_ops, conflicts

    def _find_free_slot(
        self,
        anchor_x: Optional[float],
        anchor_y: Optional[float],
        width: float,
        height: float,
        occupied_boxes: List[Tuple[float, float, float, float]],
    ) -> Tuple[float, float]:
        """Find non-overlapping coordinates near the anchor or at the next available grid slot."""
        def collides(x: float, y: float) -> bool:
            pad = 20
            nx2 = x + width + pad
            ny2 = y + height + pad
            for ox1, oy1, ox2, oy2 in occupied_boxes:
                if not (nx2 < ox1 or x > ox2 or ny2 < oy1 or y > oy2):
                    return True
            return False

        if anchor_x is not None and anchor_y is not None:
            # Try right, below, left, above
            candidates = [
                (anchor_x + width + 80, anchor_y),
                (anchor_x, anchor_y + height + 60),
                (anchor_x - width - 80, anchor_y),
                (anchor_x, anchor_y - height - 60),
                (anchor_x + width + 80, anchor_y + height + 60),
            ]
            for cx, cy in candidates:
                if cx >= 40 and cy >= 40 and not collides(cx, cy):
                    occupied_boxes.append((cx, cy, cx + width, cy + height))
                    return cx, cy

        # Standard grid sweep from top-left
        col_wrap = 4
        max_x = max([b[2] for b in occupied_boxes], default=80)
        max_y = max([b[3] for b in occupied_boxes], default=80)

        for row in range(20):
            for col in range(col_wrap):
                gx = 80 + col * (width + 90)
                gy = 80 + row * (height + 70)
                if not collides(gx, gy):
                    occupied_boxes.append((gx, gy, gx + width, gy + height))
                    return gx, gy

        # Fallback placed below everything
        new_x = 80
        new_y = max_y + 80
        occupied_boxes.append((new_x, new_y, new_x + width, new_y + height))
        return new_x, new_y

    def _apply_add_node(
        self,
        op: VisualPatchOperation,
        element_map: Dict[str, Dict[str, Any]],
        label_to_id: Dict[str, str],
        occupied_boxes: List[Tuple[float, float, float, float]],
        applied_ops: List[Dict[str, Any]],
        conflicts: List[str],
    ) -> None:
        rect_id = op.target_id if op.target_id.startswith("node_") else f"node_{op.target_id}"
        text_id = f"label_{op.target_id.replace('node_', '')}"
        label = op.label or op.target_id.replace("node_", "").replace("_", " ").title()

        # Deduplication check: if node already exists by ID or exact label, update it instead of duplicating
        clean_lbl = self._canonical_concept_key(label)
        if rect_id in element_map or clean_lbl in label_to_id:
            existing_rect_id = rect_id if rect_id in element_map else label_to_id[clean_lbl]
            if existing_rect_id in element_map:
                el = element_map[existing_rect_id]
                style = NODE_STYLES.get(op.node_type or "service", DEFAULT_STYLE)
                el["strokeColor"] = style["stroke"]
                el["backgroundColor"] = style["background"]
                applied_ops.append({**op.model_dump(), "note": "Updated existing node instead of duplicating"})
                return

        # Position safely near existing components
        x, y = self._find_free_slot(None, None, NODE_WIDTH, NODE_HEIGHT, occupied_boxes)
        style = NODE_STYLES.get(op.node_type or "service", DEFAULT_STYLE)

        rect_element = {
            "id": rect_id,
            "semantic_id": rect_id,
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
            "strokeWidth": 2 if op.emphasis == "primary" else 1,
            "roughness": 1,
            "opacity": 60 if op.emphasis == "muted" else 100,
            "groupIds": [op.group] if op.group else [],
            "roundness": {"type": 3},
            "boundElements": [{"type": "text", "id": text_id}],
            "isDeleted": False,
        }

        is_long = len(label) > 22 or "\n" in label
        font_sz = 13 if is_long else 15
        txt_h = 36 if is_long else 24
        txt_y = y + (NODE_HEIGHT - txt_h) / 2

        text_element = {
            "id": text_id,
            "semantic_id": rect_id,
            "semantic_type": "node_label",
            "type": "text",
            "x": x + 12,
            "y": txt_y,
            "width": NODE_WIDTH - 24,
            "height": txt_h,
            "text": label,
            "originalText": label,
            "fontSize": font_sz,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": 14,
            "containerId": rect_id,
            "strokeColor": "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "roughness": 1,
            "opacity": 100,
            "groupIds": [op.group] if op.group else [],
            "roundness": None,
            "isDeleted": False,
        }

        element_map[rect_id] = rect_element
        element_map[text_id] = text_element
        label_to_id[clean_lbl] = rect_id
        applied_ops.append(op.model_dump())

    def _apply_update_node(
        self,
        op: VisualPatchOperation,
        element_map: Dict[str, Dict[str, Any]],
        label_to_id: Dict[str, str],
        applied_ops: List[Dict[str, Any]],
        conflicts: List[str],
    ) -> None:
        rect_id = op.target_id if op.target_id.startswith("node_") else f"node_{op.target_id}"
        el = element_map.get(rect_id)
        if not el and op.label:
            clean_lbl = op.label.strip().lower()
            if clean_lbl in label_to_id:
                el = element_map.get(label_to_id[clean_lbl])

        if not el:
            conflicts.append(f"Node '{op.target_id}' not found for update; skipping")
            return

        if op.node_type:
            style = NODE_STYLES.get(op.node_type, DEFAULT_STYLE)
            el["strokeColor"] = style["stroke"]
            el["backgroundColor"] = style["background"]
        if op.emphasis:
            el["strokeWidth"] = 2 if op.emphasis == "primary" else 1
            el["opacity"] = 60 if op.emphasis == "muted" else 100

        # Update text if label changed
        if op.label:
            text_id = f"label_{op.target_id.replace('node_', '')}"
            txt_el = element_map.get(text_id)
            if txt_el:
                txt_el["text"] = op.label
                txt_el["originalText"] = op.label

        applied_ops.append(op.model_dump())

    def _apply_remove_node(
        self,
        op: VisualPatchOperation,
        element_map: Dict[str, Dict[str, Any]],
        safety: PatchSafetyClassification,
        applied_ops: List[Dict[str, Any]],
        conflicts: List[str],
    ) -> None:
        if safety == PatchSafetyClassification.SAFE_AUTO_APPLY:
            # Conservative: SAFE_AUTO_APPLY cannot silently delete user components
            conflicts.append(f"Silently removing node '{op.target_id}' is restricted; human review required")
            return

        rect_id = op.target_id if op.target_id.startswith("node_") else f"node_{op.target_id}"
        text_id = f"label_{op.target_id.replace('node_', '')}"

        element_map.pop(rect_id, None)
        element_map.pop(text_id, None)
        applied_ops.append(op.model_dump())

    def _apply_add_edge(
        self,
        op: VisualPatchOperation,
        element_map: Dict[str, Dict[str, Any]],
        label_to_id: Dict[str, str],
        applied_ops: List[Dict[str, Any]],
        conflicts: List[str],
    ) -> None:
        src_key = (op.source or "").strip()
        dst_key = (op.target or "").strip()
        if not src_key or not dst_key:
            return

        src_id = src_key if src_key.startswith("node_") else f"node_{src_key}"
        dst_id = dst_key if dst_key.startswith("node_") else f"node_{dst_key}"

        if src_id not in element_map:
            src_id = label_to_id.get(src_key.lower(), src_id)
        if dst_id not in element_map:
            dst_id = label_to_id.get(dst_key.lower(), dst_id)

        src_el = element_map.get(src_id)
        dst_el = element_map.get(dst_id)
        if not src_el or not dst_el:
            conflicts.append(f"Cannot connect {src_key} -> {dst_key}: nodes missing")
            return

        edge_id = f"edge_{src_id.replace('node_', '')}_{dst_id.replace('node_', '')}"
        canonical_edge_key = f"edge_{self._canonical_concept_key(src_id)}_{self._canonical_concept_key(dst_id)}"
        if edge_id in element_map:
            # Edge already exists, no duplicate needed
            return

        sx = float(src_el.get("x") or 0)
        sy = float(src_el.get("y") or 0)
        sw = float(src_el.get("width") or NODE_WIDTH)
        sh = float(src_el.get("height") or NODE_HEIGHT)

        dx = float(dst_el.get("x") or 0)
        dy = float(dst_el.get("y") or 0)
        dw = float(dst_el.get("width") or NODE_WIDTH)
        dh = float(dst_el.get("height") or NODE_HEIGHT)

        start_x = sx + sw
        start_y = sy + sh / 2
        end_x = dx
        end_y = dy + dh / 2

        if dx < sx - 20:
            start_x = sx + sw / 2
            start_y = sy + sh
            end_x = dx + dw / 2
            end_y = dy

        delta_x = end_x - start_x
        delta_y = end_y - start_y

        arrow_element = {
            "id": edge_id,
            "semantic_id": canonical_edge_key,
            "semantic_type": "edge",
            "type": "arrow",
            "x": start_x,
            "y": start_y,
            "width": max(1, abs(delta_x)),
            "height": max(1, abs(delta_y)),
            "angle": 0,
            "strokeColor": "#64748b",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "dashed" if op.style == "dashed" else "solid",
            "roughness": 1,
            "opacity": 100,
            "points": [[0, 0], [delta_x, delta_y]],
            "startBinding": {"elementId": src_id, "focus": 0.1, "gap": 4},
            "endBinding": {"elementId": dst_id, "focus": -0.1, "gap": 4},
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "isDeleted": False,
        }

        element_map[edge_id] = arrow_element
        applied_ops.append(op.model_dump())

    def _apply_add_note(
        self,
        op: VisualPatchOperation,
        element_map: Dict[str, Dict[str, Any]],
        occupied_boxes: List[Tuple[float, float, float, float]],
        applied_ops: List[Dict[str, Any]],
        conflicts: List[str],
    ) -> None:
        note_id = (
            op.target_id
            if op.target_id.startswith(("note_", "conversation_note_"))
            else f"note_{op.target_id}"
        )
        text_id = f"txt_{note_id}"
        content = op.content or op.label or "Architectural note"

        if note_id in element_map:
            existing = element_map[note_id]
            existing["text"] = content
            applied_ops.append({**op.model_dump(), "note": "Updated existing note instead of duplicating"})
            return
        category = op.category.value if op.category else "DECISION"
        style = NOTE_CATEGORY_STYLES.get(category, NOTE_CATEGORY_STYLES["DECISION"])

        note_w = 620 if category == "CONVERSATION" else 260
        note_h = 132 if category == "CONVERSATION" else 80

        if category == "CONVERSATION":
            # Conversation cards form a strict chronological vertical stream.
            conversation_cards = [
                el for el in element_map.values()
                if isinstance(el, dict) and el.get("semantic_type") == "note"
                and str(el.get("id", "")).startswith("conversation_note_")
            ]
            node_right = max(
                [
                    float(el.get("x") or 0) + float(el.get("width") or 0)
                    for el in element_map.values()
                    if isinstance(el, dict)
                    and (
                        el.get("semantic_type") == "node"
                        or str(el.get("id", "")).startswith("node_")
                    )
                ],
                default=BASE_X + NODE_WIDTH,
            )
            x = node_right + 80
            y = BASE_Y + len(conversation_cards) * (note_h + 18)
            occupied_boxes.append((x, y, x + note_w, y + note_h))
        else:
            x, y = self._find_free_slot(None, None, note_w, note_h, occupied_boxes)

        rect_element = {
            "id": note_id,
            "semantic_id": note_id,
            "semantic_type": "note",
            "type": "rectangle",
            "x": x,
            "y": y,
            "width": note_w,
            "height": note_h,
            "strokeColor": style["stroke"],
            "backgroundColor": style["background"],
            "fillStyle": "solid",
            "strokeWidth": 1,
            "roughness": 1,
            "opacity": 100,
            "roundness": {"type": 2},
            "boundElements": [{"type": "text", "id": text_id}],
            "isDeleted": False,
        }

        display_text = f"[{category}]\n{content[:480]}"
        text_element = {
            "id": text_id,
            "type": "text",
            "x": x + 10,
            "y": y + 10,
            "width": note_w - 20,
            "height": note_h - 20,
            "text": display_text,
            "originalText": display_text,
            "fontSize": 12,
            "fontFamily": 1,
            "textAlign": "left",
            "verticalAlign": "top",
            "baseline": 12,
            "containerId": note_id,
            "strokeColor": style["text"],
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "lineHeight": 1.35,
            "autoResize": True,
            "isDeleted": False,
        }

        element_map[note_id] = rect_element
        element_map[text_id] = text_element
        applied_ops.append(op.model_dump())

    def _apply_note_mutation(
        self,
        op: VisualPatchOperation,
        element_map: Dict[str, Dict[str, Any]],
        applied_ops: List[Dict[str, Any]],
        conflicts: List[str],
    ) -> None:
        note_id = op.target_id if op.target_id.startswith("note_") else f"note_{op.target_id}"
        text_id = f"txt_{note_id}"

        if op.op_type == VisualPatchOpType.REMOVE_NOTE:
            element_map.pop(note_id, None)
            element_map.pop(text_id, None)
            applied_ops.append(op.model_dump())
        elif op.op_type == VisualPatchOpType.UPDATE_NOTE:
            txt_el = element_map.get(text_id)
            if txt_el and op.content:
                category = op.category.value if op.category else "DECISION"
                txt_el["text"] = f"[{category}]\n{op.content[:90]}"
            applied_ops.append(op.model_dump())
