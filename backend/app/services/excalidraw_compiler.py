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

    def compile(self, plan: VisualPlan, enforce_grounding: bool = True) -> List[Dict[str, Any]]:
        if (
            not plan.nodes
            and not plan.notes_document
            and not plan.notes_sections
            and not plan.notes
            and not plan.visualizations
        ):
            raise ExcalidrawCompileError("VisualPlan contains no canvas content to compile.")

        # Ground the plan before it becomes geometry. A node that cites no
        # evidence is the model reasoning rather than reporting, so it is
        # refused here. Previously any node survived, which is how a single
        # WhatsApp sentence produced a seven-node architecture whose contents
        # came from the model's imagination.
        #
        # In free design mode (enforce_grounding=False) the agent has complete
        # freedom: ungrounded nodes render, still tagged inferred and still
        # carrying whatever evidence_ids the model cited.
        grounded_nodes = [n for n in plan.nodes if n.evidence_ids]
        if enforce_grounding:
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
        elif len(grounded_nodes) < len(plan.nodes):
            logger.info(
                "visual_plan_free_mode: kept=%d ungrounded=%d",
                len(grounded_nodes),
                len(plan.nodes) - len(grounded_nodes),
            )
        # In enforce mode plan.nodes is already the grounded subset; in free
        # mode it is the full set. Either way this is the rendered set.
        valid_node_ids = {n.id for n in plan.nodes}
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

        # ------------------------------------------------------------------
        # Living project notebook
        # ------------------------------------------------------------------
        # The notes side is a real document. The agent decides the sections and
        # block types; the compiler only lays them out as readable Excalidraw text.
        legacy_rank = {
            "decision": 0,
            "requirement": 1,
            "directive": 2,
            "action": 3,
            "risk": 4,
            "assumption": 5,
            "note": 6,
        }
        legacy_titles = {
            "decision": "Key Decisions",
            "requirement": "Requirements",
            "directive": "Directives",
            "action": "Actions",
            "risk": "Risks",
            "assumption": "Assumptions",
            "note": "Notes",
        }

        def _legacy_document() -> Dict[str, Any]:
            grouped: Dict[str, Dict[str, Any]] = {}
            for raw in plan.notes or []:
                if isinstance(raw, dict):
                    text_value = str(raw.get("text") or raw.get("content") or "").strip()
                    kind = str(raw.get("kind") or "note").strip().lower()
                    evidence = raw.get("evidence_ids")
                    if evidence is not None and not evidence:
                        continue
                    support = "explicit" if evidence else "inferred"
                    evidence_ids = [str(e) for e in (evidence or [])][:4]
                else:
                    text_value = str(raw or "").strip()
                    kind = "note"
                    support = "inferred"
                    evidence_ids = []
                if not text_value:
                    continue
                bucket = grouped.setdefault(
                    kind if kind in legacy_titles else "note",
                    {
                        "id": f"legacy_{kind}",
                        "title": legacy_titles.get(kind, "Notes"),
                        "blocks": [],
                        "order": legacy_rank.get(kind, 9),
                        "evidence_ids": [],
                        "support_type": support,
                    },
                )
                bucket["blocks"].append({
                    "id": f"legacy_block_{len(bucket['blocks'])}",
                    "block_type": "bullets",
                    "items": [text_value],
                    "evidence_ids": evidence_ids,
                    "support_type": support,
                })
                bucket["evidence_ids"] = list(dict.fromkeys(
                    bucket["evidence_ids"] + evidence_ids
                ))[:4]
                if support == "explicit":
                    bucket["support_type"] = "explicit"
            return {
                "title": "PROJECT NOTES",
                "subtitle": None,
                "sections": list(grouped.values()),
                "updated_label": "Maintained from project memory",
            }

        document = None
        if getattr(plan, "notes_document", None):
            document = plan.notes_document.model_dump(mode="json")
        elif getattr(plan, "notes_sections", None):
            document = {
                "title": "PROJECT NOTES",
                "subtitle": None,
                "sections": [
                    section.model_dump(mode="json")
                    if hasattr(section, "model_dump") else dict(section)
                    for section in plan.notes_sections
                ],
                "updated_label": "Maintained from project memory",
            }
        elif plan.notes:
            document = _legacy_document()

        # Positioning is deliberately fixed here: diagrams/visuals stay left,
        # the living written notebook stays on the right.
        diagram_right = BASE_X + 360
        if positions:
            diagram_right = max(diagram_right, max(x + NODE_WIDTH for x, _ in positions.values()))
        notes_x = diagram_right + 120
        notes_y = BASE_Y
        notes_w = 560

        def _line_count(value: str, width: int = 72) -> int:
            raw_lines = str(value or "").splitlines() or [""]
            return sum(max(1, (len(line) + width - 1) // width) for line in raw_lines)

        def _block_text(block: Dict[str, Any]) -> str:
            kind = str(block.get("block_type") or "paragraph").lower()
            text_value = str(block.get("text") or "").strip()
            title_value = str(block.get("title") or "").strip()
            items = [str(item).strip() for item in (block.get("items") or []) if str(item).strip()]
            rows = block.get("rows") or []

            if kind in ("heading", "paragraph", "quote", "callout"):
                return text_value
            if kind == "bullets":
                return "\n".join(f"• {item}" for item in items)
            if kind == "numbered":
                return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
            if kind == "checklist":
                return "\n".join(f"☐ {item}" for item in items)
            if kind == "key_value":
                return "\n".join(
                    f"{str(row[0]).strip()}: {str(row[1]).strip()}"
                    for row in rows
                    if isinstance(row, (list, tuple)) and len(row) >= 2
                ) or "\n".join(f"{item}" for item in items)
            if kind == "table":
                return "\n".join(
                    "  |  ".join(str(cell).strip() for cell in row)
                    for row in rows
                    if isinstance(row, (list, tuple))
                )
            if kind == "divider":
                return ""
            return text_value or "\n".join(items)

        def _block_height(block: Dict[str, Any]) -> int:
            kind = str(block.get("block_type") or "paragraph").lower()
            if kind == "divider":
                return 22
            if kind == "heading":
                return 34
            rendered = _block_text(block)
            return min(360, max(34, 20 * _line_count(rendered, 72) + 8))

        if document and document.get("sections"):
            ordered_sections = sorted(
                document.get("sections") or [],
                key=lambda sec: (int(sec.get("order", 0) or 0), str(sec.get("title") or "")),
            )

            # Build logical pages so long-running projects do not become one
            # enormous text object. The page break is compiler-owned.
            pages: List[List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]] = []
            current_page: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
            current_height = 96
            max_page_height = 2200

            for section in ordered_sections:
                sec = dict(section)
                blocks = [
                    block.model_dump(mode="json") if hasattr(block, "model_dump") else dict(block)
                    for block in (sec.get("blocks") or [])
                ]
                blocks = [b for b in blocks if _block_text(b) or str(b.get("block_type") or "").lower() == "divider"]
                if not blocks:
                    continue
                section_height = 42 + sum(_block_height(b) + 12 for b in blocks) + 18
                if current_page and current_height + section_height > max_page_height:
                    pages.append(current_page)
                    current_page = []
                    current_height = 96
                current_page.append((sec, blocks))
                current_height += section_height
            if current_page:
                pages.append(current_page)

            title_digest = hashlib.sha1((document.get("title") or "PROJECT NOTES").encode("utf-8")).hexdigest()[:12]
            for page_index, page_sections in enumerate(pages):
                page_height = 120
                for _, blocks in page_sections:
                    page_height += 52 + sum(_block_height(b) + 12 for b in blocks) + 18
                page_height = min(max(page_height, 520), max_page_height)
                page_id = f"notes_page_{title_digest}_{page_index}"
                elements.append({
                    "id": page_id,
                    "type": "rectangle",
                    "x": notes_x,
                    "y": notes_y + page_index * (page_height + 70),
                    "width": notes_w,
                    "height": page_height,
                    "angle": 0,
                    "strokeColor": "#8a8a8a",
                    "backgroundColor": "#fffdf7",
                    "fillStyle": "solid",
                    "strokeWidth": 1,
                    "roughness": 0,
                    "opacity": 100,
                    "roundness": {"type": 3},
                    "boundElements": [],
                    "isDeleted": False,
                    "customData": {
                        "visual": {
                            "type": "project_notes_page",
                            "semantic_id": "project_notes",
                            "page": page_index + 1,
                        }
                    },
                })
                cursor_y = notes_y + page_index * (page_height + 70) + 24
                doc_title = str(document.get("title") or "PROJECT NOTES")
                if page_index == 0:
                    title_text = doc_title
                else:
                    title_text = f"{doc_title} · {page_index + 1}"
                elements.append({
                    "id": f"lbl_notes_hdr_{title_digest}" if page_index == 0 else f"notes_title_{title_digest}_{page_index}",
                    "type": "text",
                    "x": notes_x + 24,
                    "y": cursor_y,
                    "width": notes_w - 48,
                    "height": 32,
                    "text": title_text,
                    "originalText": title_text,
                    "fontSize": 19,
                    "fontFamily": 1,
                    "textAlign": "left",
                    "verticalAlign": "top",
                    "lineHeight": 1.2,
                    "baseline": 18,
                    "autoResize": False,
                    "strokeColor": "#202522",
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 1,
                    "roughness": 0,
                    "opacity": 100,
                    "angle": 0,
                    "groupIds": [],
                    "isDeleted": False,
                    "customData": {
                        "visual": {
                            "type": "project_notes_title",
                            "semantic_id": "project_notes",
                        }
                    },
                })
                cursor_y += 36
                subtitle = str(document.get("subtitle") or "").strip()
                if page_index == 0 and subtitle:
                    elements.append({
                        "id": f"notes_subtitle_{title_digest}",
                        "type": "text",
                        "x": notes_x + 24,
                        "y": cursor_y,
                        "width": notes_w - 48,
                        "height": 24,
                        "text": subtitle[:180],
                        "originalText": subtitle[:180],
                        "fontSize": 11,
                        "fontFamily": 1,
                        "textAlign": "left",
                        "verticalAlign": "top",
                        "lineHeight": 1.3,
                        "baseline": 10,
                        "autoResize": True,
                        "strokeColor": "#6c746e",
                        "backgroundColor": "transparent",
                        "fillStyle": "solid",
                        "strokeWidth": 1,
                        "roughness": 0,
                        "opacity": 100,
                        "angle": 0,
                        "groupIds": [],
                        "isDeleted": False,
                        "customData": {"visual": {"type": "project_notes_subtitle"}},
                    })
                    cursor_y += 26

                for sec_index, (section, blocks) in enumerate(page_sections):
                    sec_id = str(section.get("id") or section.get("title") or f"section_{sec_index}")
                    sec_key = hashlib.sha1(sec_id.encode("utf-8")).hexdigest()[:12]
                    heading = str(section.get("title") or "Notes")[:100]
                    section_evidence = [str(e) for e in (section.get("evidence_ids") or [])][:4]
                    section_support = str(section.get("support_type") or ("explicit" if section_evidence else "inferred"))
                    elements.append({
                        "id": f"note_section_{sec_key}_header",
                        "type": "text",
                        "x": notes_x + 24,
                        "y": cursor_y,
                        "width": notes_w - 48,
                        "height": 26,
                        "text": heading,
                        "originalText": heading,
                        "fontSize": 14,
                        "fontFamily": 1,
                        "textAlign": "left",
                        "verticalAlign": "top",
                        "lineHeight": 1.2,
                        "baseline": 13,
                        "autoResize": False,
                        "strokeColor": "#1f4d40",
                        "backgroundColor": "transparent",
                        "fillStyle": "solid",
                        "strokeWidth": 1,
                        "roughness": 0,
                        "opacity": 100,
                        "angle": 0,
                        "groupIds": [],
                        "isDeleted": False,
                        "customData": {
                            "visual": {
                                "type": "note_section_header",
                                "section_id": sec_id,
                                "evidence_ids": section_evidence,
                                "support_type": section_support,
                            }
                        },
                    })
                    cursor_y += 30

                    for block_index, block in enumerate(blocks):
                        kind = str(block.get("block_type") or "paragraph").lower()
                        block_id = str(block.get("id") or f"{sec_id}_block_{block_index}")
                        block_key = hashlib.sha1(block_id.encode("utf-8")).hexdigest()[:12]
                        block_evidence = [str(e) for e in (block.get("evidence_ids") or section_evidence)][:4]
                        block_support = str(block.get("support_type") or ("explicit" if block_evidence else "inferred"))
                        rendered = _block_text(block)
                        bh = _block_height(block)

                        if kind == "divider":
                            elements.append({
                                "id": f"note_block_{block_key}_divider",
                                "type": "line",
                                "x": notes_x + 24,
                                "y": cursor_y + 8,
                                "width": notes_w - 48,
                                "height": 0,
                                "points": [[0, 0], [notes_w - 48, 0]],
                                "strokeColor": "#d5d7d2",
                                "backgroundColor": "transparent",
                                "fillStyle": "solid",
                                "strokeWidth": 1,
                                "roughness": 0,
                                "opacity": 100,
                                "angle": 0,
                                "isDeleted": False,
                                "customData": {
                                    "visual": {
                                        "type": "note_block_divider",
                                        "block_id": block_id,
                                    }
                                },
                            })
                            cursor_y += bh
                            continue

                        if kind in ("callout",):
                            box_id = f"note_block_{block_key}_box"
                            elements.append({
                                "id": box_id,
                                "type": "rectangle",
                                "x": notes_x + 18,
                                "y": cursor_y - 2,
                                "width": notes_w - 36,
                                "height": bh + 6,
                                "angle": 0,
                                "strokeColor": "#66736a",
                                "backgroundColor": "#f5f8f4",
                                "fillStyle": "solid",
                                "strokeWidth": 1,
                                "roughness": 0,
                                "opacity": 100,
                                "roundness": {"type": 3},
                                "boundElements": [],
                                "isDeleted": False,
                                "customData": {
                                    "visual": {
                                        "type": "note_block_callout",
                                        "block_id": block_id,
                                        "evidence_ids": block_evidence,
                                        "support_type": block_support,
                                    }
                                },
                            })

                        font_size = 17 if kind == "heading" else 12
                        if kind == "heading":
                            font_size = max(12, 18 - int(block.get("level", 2) or 2))
                        stroke = "#202522" if kind not in ("quote",) else "#59635d"
                        elements.append({
                            "id": f"note_block_{block_key}_text",
                            "type": "text",
                            "x": notes_x + 28,
                            "y": cursor_y + (2 if kind != "heading" else 0),
                            "width": notes_w - 56,
                            "height": bh,
                            "text": rendered or title_text,
                            "originalText": rendered or title_text,
                            "fontSize": font_size,
                            "fontFamily": 1,
                            "textAlign": "left",
                            "verticalAlign": "top",
                            "lineHeight": 1.4,
                            "baseline": 12,
                            "autoResize": True,
                            "strokeColor": stroke,
                            "backgroundColor": "transparent",
                            "fillStyle": "solid",
                            "strokeWidth": 1,
                            "roughness": 0,
                            "opacity": 100,
                            "angle": 0,
                            "groupIds": [],
                            "isDeleted": False,
                            "customData": {
                                "visual": {
                                    "type": "note_block",
                                    "block_id": block_id,
                                    "block_type": kind,
                                    "evidence_ids": block_evidence,
                                    "support_type": block_support,
                                }
                            },
                        })

                        if kind == "quote":
                            elements.append({
                                "id": f"note_block_{block_key}_quote_bar",
                                "type": "line",
                                "x": notes_x + 20,
                                "y": cursor_y,
                                "width": 0,
                                "height": bh,
                                "points": [[0, 0], [0, bh]],
                                "strokeColor": "#728077",
                                "backgroundColor": "transparent",
                                "fillStyle": "solid",
                                "strokeWidth": 3,
                                "roughness": 0,
                                "opacity": 100,
                                "angle": 0,
                                "isDeleted": False,
                                "customData": {"visual": {"type": "note_block_quote_bar", "block_id": block_id}},
                            })

                        cursor_y += bh + 12

                if page_index == len(pages) - 1:
                    footer = str(document.get("updated_label") or "Maintained automatically from project memory")
                    footer_text = footer + " • rechecked every 30 seconds"
                    elements.append({
                        "id": f"notes_footer_{title_digest}",
                        "type": "text",
                        "x": notes_x + 24,
                        "y": notes_y + page_index * (page_height + 70) + page_height - 34,
                        "width": notes_w - 48,
                        "height": 20,
                        "text": footer_text[:180],
                        "originalText": footer_text[:180],
                        "fontSize": 9,
                        "fontFamily": 1,
                        "textAlign": "left",
                        "verticalAlign": "top",
                        "lineHeight": 1.2,
                        "baseline": 9,
                        "autoResize": False,
                        "strokeColor": "#777a76",
                        "backgroundColor": "transparent",
                        "fillStyle": "solid",
                        "strokeWidth": 1,
                        "roughness": 0,
                        "opacity": 100,
                        "angle": 0,
                        "groupIds": [],
                        "isDeleted": False,
                        "customData": {"visual": {"type": "project_notes_footer"}},
                    })

        # Compatibility metadata for the old notes API. These elements
        # are intentionally deleted: existing integrations/tests can still
        # inspect the historical semantic IDs without creating visible sticky
        # notes on the new canvas.
        if plan.notes:
            legacy_items: List[Dict[str, Any]] = []
            for raw in plan.notes:
                if isinstance(raw, dict):
                    legacy_text = str(raw.get("text") or raw.get("content") or "").strip()
                    legacy_ev = raw.get("evidence_ids")
                    if legacy_ev is not None and not legacy_ev:
                        continue
                    legacy_kind = str(raw.get("kind") or "note").strip().lower()
                    legacy_ids = [str(e) for e in (legacy_ev or [])][:4]
                    legacy_support = "explicit" if legacy_ids else "inferred"
                    legacy_order = int(raw.get("order", 0) or 0)
                else:
                    legacy_text = str(raw or "").strip()
                    legacy_kind = "note"
                    legacy_ids = []
                    legacy_support = "inferred"
                    legacy_order = 0
                if legacy_text:
                    legacy_items.append({
                        "text": legacy_text,
                        "kind": legacy_kind,
                        "evidence_ids": legacy_ids,
                        "support_type": legacy_support,
                        "order": legacy_order,
                    })

            legacy_items.sort(
                key=lambda item: (
                    {"decision": 0, "requirement": 1, "directive": 2, "action": 3,
                     "risk": 4, "assumption": 5, "note": 6}.get(item["kind"], 9),
                    item["order"],
                    item["text"],
                )
            )

            for compat_index, item in enumerate(legacy_items):
                elements.append({
                    "id": f"sticky_text_{compat_index}",
                    "type": "text",
                    "x": notes_x + 24,
                    "y": notes_y + 90 + compat_index * 22,
                    "width": notes_w - 48,
                    "height": 20,
                    "text": item["text"],
                    "originalText": item["text"],
                    "fontSize": 1,
                    "fontFamily": 1,
                    "textAlign": "left",
                    "verticalAlign": "top",
                    "lineHeight": 1,
                    "baseline": 1,
                    "autoResize": False,
                    "strokeColor": "transparent",
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 1,
                    "roughness": 0,
                    "opacity": 0,
                    "angle": 0,
                    "groupIds": [],
                    "isDeleted": True,
                    "customData": {
                        "visual": {
                            "type": "architectural_note",
                            "kind": item["kind"],
                            "evidence_ids": item["evidence_ids"],
                            "support_type": item["support_type"],
                        }
                    },
                })


        # ------------------------------------------------------------------
        # Open visual modeling layer
        # ------------------------------------------------------------------
        # The agent may choose any visual kind and any semantic primitives.
        # It never supplies x/y coordinates. The compiler lays out each
        # composition inside the left visual zone.
        visualizations = getattr(plan, "visualizations", []) or []

        def _safe_style(style: Any) -> Dict[str, Any]:
            if not isinstance(style, dict):
                return {}
            blocked = {"x", "y", "position", "id", "type", "isDeleted"}
            return {k: v for k, v in style.items() if k not in blocked}

        visual_base_y = max(
            [y + NODE_HEIGHT for _, y in positions.values()] or [BASE_Y + 20]
        ) + 100
        for v_index, visualization in enumerate(visualizations):
            v = visualization.model_dump(mode="json") if hasattr(visualization, "model_dump") else dict(visualization)
            vid = str(v.get("id") or f"visual_{v_index}")
            kind = str(v.get("kind") or "custom")
            primitives = v.get("elements") or []
            vx = BASE_X
            vy = visual_base_y + v_index * 260
            vw = 720
            vh = 220

            if not primitives:
                # A custom visualization is still allowed to be semantic-only.
                # Render its purpose/content as a visual callout rather than
                # silently discarding it.
                text_parts = []
                if v.get("title"):
                    text_parts.append(str(v["title"]))
                if v.get("purpose"):
                    text_parts.append(str(v["purpose"]))
                content_dict = v.get("content") or {}
                if isinstance(content_dict, dict):
                    value = content_dict.get("text") or content_dict.get("value")
                    if value:
                        text_parts.append(str(value))
                primitives = [{
                    "id": f"{vid}_summary",
                    "primitive_type": "rectangle",
                    "text": "\n".join(text_parts)[:420] or kind,
                    "width": 620,
                    "height": 130,
                    "style": {},
                    "metadata": {},
                }]

            # Reserve a local grid. This is the only place where positioning is decided.
            placed: Dict[str, Tuple[float, float, float, float]] = {}
            non_connectors = [p for p in primitives if str(p.get("primitive_type") or "").lower() not in ("arrow", "line", "connector", "connect")]
            connectors = [p for p in primitives if p not in non_connectors]

            cursor_x = vx
            cursor_y = vy + 42
            row_height = 0
            for p_index, raw_p in enumerate(non_connectors):
                p = raw_p if isinstance(raw_p, dict) else {}
                pid = str(p.get("id") or f"{vid}_p_{p_index}")
                pw = max(120, min(320, float(p.get("width") or 220)))
                ph = max(44, min(180, float(p.get("height") or 90)))
                if cursor_x + pw > vx + vw:
                    cursor_x = vx
                    cursor_y += row_height + 24
                    row_height = 0
                placed[pid] = (cursor_x, cursor_y, pw, ph)
                cursor_x += pw + 28
                row_height = max(row_height, ph)
            total_needed = cursor_y - vy + row_height + 32
            vh = max(vh, min(total_needed, 720))

            digest = hashlib.sha1(vid.encode("utf-8")).hexdigest()[:12]
            frame_id = f"visual_{digest}_frame"
            elements.append({
                "id": frame_id,
                "type": "rectangle",
                "x": vx,
                "y": vy,
                "width": vw,
                "height": vh,
                "angle": 0,
                "strokeColor": "#a0aaa4",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "dashed",
                "roughness": 0,
                "opacity": 100,
                "roundness": {"type": 3},
                "boundElements": [],
                "isDeleted": False,
                "customData": {
                    "visual": {
                        "type": "freeform_visual_frame",
                        "visualization_id": vid,
                        "kind": kind,
                        "evidence_ids": [str(e) for e in (v.get("evidence_ids") or [])][:4],
                        "support_type": v.get("support_type") or "inferred",
                    }
                },
            })
            elements.append({
                "id": f"visual_{digest}_title",
                "type": "text",
                "x": vx + 18,
                "y": vy + 14,
                "width": vw - 36,
                "height": 22,
                "text": str(v.get("title") or kind)[:100],
                "originalText": str(v.get("title") or kind)[:100],
                "fontSize": 13,
                "fontFamily": 1,
                "textAlign": "left",
                "verticalAlign": "top",
                "lineHeight": 1.2,
                "baseline": 12,
                "autoResize": False,
                "strokeColor": "#34433c",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "roughness": 0,
                "opacity": 100,
                "angle": 0,
                "groupIds": [],
                "isDeleted": False,
            })

            visual_ids: Dict[str, str] = {}
            for p_index, raw_p in enumerate(non_connectors):
                p = raw_p if isinstance(raw_p, dict) else {}
                pid = str(p.get("id") or f"{vid}_p_{p_index}")
                px, py, pw, ph = placed[pid]
                ptype = str(p.get("primitive_type") or "rectangle").lower()
                style = _safe_style(p.get("style"))
                ex_id = f"visual_{digest}_{hashlib.sha1(pid.encode('utf-8')).hexdigest()[:10]}"
                visual_ids[pid] = ex_id

                if ptype in ("text", "label", "paragraph"):
                    el = {
                        "id": ex_id,
                        "type": "text",
                        "x": px,
                        "y": py,
                        "width": pw,
                        "height": ph,
                        "text": str(p.get("text") or p.get("title") or "")[:1200],
                        "originalText": str(p.get("text") or p.get("title") or "")[:1200],
                        "fontSize": 12,
                        "fontFamily": 1,
                        "textAlign": "left",
                        "verticalAlign": "top",
                        "lineHeight": 1.35,
                        "baseline": 11,
                        "autoResize": True,
                        "backgroundColor": "transparent",
                        "fillStyle": "solid",
                        "strokeWidth": 1,
                        "roughness": 0,
                        "opacity": 100,
                        "angle": 0,
                        "groupIds": [],
                        "isDeleted": False,
                    }
                    el.update(style)
                else:
                    shape = {
                        "ellipse": "ellipse",
                        "circle": "ellipse",
                        "diamond": "diamond",
                        "line": "line",
                        "frame": "rectangle",
                        "box": "rectangle",
                        "card": "rectangle",
                        "rectangle": "rectangle",
                    }.get(ptype, "rectangle")
                    label_id = f"{ex_id}_label"
                    text_value = str(p.get("text") or p.get("title") or "")
                    el = {
                        "id": ex_id,
                        "type": shape,
                        "x": px,
                        "y": py,
                        "width": pw,
                        "height": ph,
                        "angle": 0,
                        "strokeColor": "#4b5a53",
                        "backgroundColor": "#f7f9f6",
                        "fillStyle": "solid",
                        "strokeWidth": 1,
                        "roughness": 0,
                        "opacity": 100,
                        "roundness": {"type": 3},
                        "boundElements": [{"type": "text", "id": label_id}] if text_value else [],
                        "isDeleted": False,
                    }
                    el.update(style)
                    elements.append(el)
                    if text_value:
                        elements.append({
                            "id": label_id,
                            "type": "text",
                            "x": px + 12,
                            "y": py + 12,
                            "width": pw - 24,
                            "height": ph - 24,
                            "text": text_value[:800],
                            "originalText": text_value[:800],
                            "fontSize": int(style.get("fontSize") or 12),
                            "fontFamily": int(style.get("fontFamily") or 1),
                            "textAlign": str(style.get("textAlign") or "center"),
                            "verticalAlign": "middle",
                            "lineHeight": 1.3,
                            "baseline": 11,
                            "autoResize": True,
                            "strokeColor": str(style.get("strokeColor") or "#23302a"),
                            "backgroundColor": "transparent",
                            "fillStyle": "solid",
                            "strokeWidth": 1,
                            "roughness": 0,
                            "opacity": 100,
                            "angle": 0,
                            "groupIds": [],
                            "isDeleted": False,
                            "customData": {
                                "visual": {
                                    "type": "freeform_visual_label",
                                    "visualization_id": vid,
                                    "primitive_id": pid,
                                    "evidence_ids": [str(e) for e in (p.get("evidence_ids") or v.get("evidence_ids") or [])][:4],
                                    "support_type": p.get("support_type") or v.get("support_type") or "inferred",
                                }
                            },
                        })
                el["customData"] = {
                    "visual": {
                        "type": "freeform_visual_primitive",
                        "visualization_id": vid,
                        "primitive_id": pid,
                        "kind": kind,
                        "evidence_ids": [str(e) for e in (p.get("evidence_ids") or v.get("evidence_ids") or [])][:4],
                        "support_type": p.get("support_type") or v.get("support_type") or "inferred",
                    }
                }
                if ptype in ("text", "label", "paragraph"):
                    elements.append(el)

            # Connectors are rendered after node placement so they can bind to
            # actual compiler-assigned positions.
            for c_index, raw_c in enumerate(connectors):
                c = raw_c if isinstance(raw_c, dict) else {}
                source_id = str(c.get("source") or "")
                target_id = str(c.get("target") or "")
                if not source_id or not target_id or source_id not in visual_ids or target_id not in visual_ids:
                    continue
                sx, sy, sw, sh = placed[source_id]
                tx, ty, tw, th = placed[target_id]
                start_x = sx + sw
                start_y = sy + sh / 2
                end_x = tx
                end_y = ty + th / 2
                arrow_id = f"visual_{digest}_connector_{c_index}"
                elements.append({
                    "id": arrow_id,
                    "type": "arrow",
                    "x": start_x,
                    "y": start_y,
                    "width": max(1, abs(end_x - start_x)),
                    "height": max(1, abs(end_y - start_y)),
                    "points": [[0, 0], [end_x - start_x, end_y - start_y]],
                    "strokeColor": "#425248",
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 2,
                    "strokeStyle": "dashed" if str(c.get("style") or "").lower() == "dashed" else "solid",
                    "roughness": 0,
                    "opacity": 100,
                    "angle": 0,
                    "groupIds": [],
                    "endArrowhead": "arrow",
                    "isDeleted": False,
                    "startBinding": {"elementId": visual_ids[source_id], "focus": 0, "gap": 6},
                    "endBinding": {"elementId": visual_ids[target_id], "focus": 0, "gap": 6},
                    "customData": {
                        "visual": {
                            "type": "freeform_visual_connector",
                            "visualization_id": vid,
                            "source": source_id,
                            "target": target_id,
                            "evidence_ids": [str(e) for e in (c.get("evidence_ids") or v.get("evidence_ids") or [])][:4],
                            "support_type": c.get("support_type") or v.get("support_type") or "inferred",
                        }
                    },
                })
                if c.get("label"):
                    label_text = str(c["label"])[:80]
                    elements.append({
                        "id": f"{arrow_id}_label",
                        "type": "text",
                        "x": min(start_x, end_x) + abs(end_x - start_x) / 2 - 50,
                        "y": min(start_y, end_y) + abs(end_y - start_y) / 2 - 14,
                        "width": 100,
                        "height": 20,
                        "text": label_text,
                        "originalText": label_text,
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
                        "roughness": 0,
                        "opacity": 90,
                        "angle": 0,
                        "groupIds": [],
                        "isDeleted": False,
                        "customData": {"visual": {"type": "freeform_visual_connector_label", "visualization_id": vid}},
                    })

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
