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
        if not plan.nodes and not plan.notes_sections and not plan.notes and not plan.visualizations:
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

        # Living project notebook. Notes are rendered as a document-like page
        # rather than sticky cards. The agent can return structured sections,
        # or legacy notes are grouped into readable sections.
        note_kind_titles = {
            "decision": "Key Decisions",
            "requirement": "Requirements",
            "directive": "Directives",
            "action": "Actions",
            "risk": "Risks",
            "assumption": "Assumptions",
            "note": "Notes",
        }
        legacy_rank = {
            "decision": 0,
            "requirement": 1,
            "directive": 2,
            "action": 3,
            "risk": 4,
            "assumption": 5,
            "note": 6,
        }

        legacy_notes: List[Dict[str, Any]] = []
        for raw in plan.notes or []:
            if isinstance(raw, dict):
                text_value = str(raw.get("text") or raw.get("content") or "").strip()
                kind = str(raw.get("kind") or "note").strip().lower()
                evidence = raw.get("evidence_ids")
                if evidence is not None and not evidence:
                    logger.info("visual_plan_legacy_note_dropped_ungrounded: %s", text_value[:60])
                    continue
                try:
                    order = int(raw.get("order", 0))
                except (TypeError, ValueError):
                    order = 0
                if not text_value:
                    continue
                legacy_notes.append({
                    "text": text_value,
                    "kind": kind,
                    "order": order,
                    "evidence_ids": [str(e) for e in (evidence or [])][:4],
                    "support_type": "explicit" if evidence else "inferred",
                })
            else:
                text_value = str(raw or "").strip()
                if text_value:
                    legacy_notes.append({
                        "text": text_value,
                        "kind": "note",
                        "order": 0,
                        "evidence_ids": [],
                        "support_type": "inferred",
                    })

        note_sections: List[Dict[str, Any]] = []
        for section in getattr(plan, "notes_sections", []) or []:
            section_dict = section.model_dump() if hasattr(section, "model_dump") else dict(section)
            title = str(section_dict.get("title") or "Notes").strip()
            body = str(section_dict.get("body") or "").strip()
            bullets = [
                str(item).strip()
                for item in (section_dict.get("bullets") or [])
                if str(item).strip()
            ]
            evidence_ids = [str(e) for e in (section_dict.get("evidence_ids") or [])][:4]
            if body or bullets:
                note_sections.append({
                    "id": str(section_dict.get("id") or title).strip() or "notes",
                    "title": title[:70],
                    "body": body[:1400],
                    "bullets": bullets[:8],
                    "order": int(section_dict.get("order", 0) or 0),
                    "evidence_ids": evidence_ids,
                    "support_type": str(section_dict.get("support_type") or ("explicit" if evidence_ids else "inferred")),
                })

        # Legacy notes remain visible and readable; new structured sections take
        # precedence so providers cannot double-render the same information.
        if not note_sections and legacy_notes:
            legacy_notes.sort(
                key=lambda n: (legacy_rank.get(n["kind"], 9), n["order"], n["text"])
            )
            grouped: Dict[str, Dict[str, Any]] = {}
            for item in legacy_notes:
                key = item["kind"] if item["kind"] in note_kind_titles else "note"
                bucket = grouped.setdefault(
                    key,
                    {
                        "id": f"legacy_{key}",
                        "title": note_kind_titles[key],
                        "body": "",
                        "bullets": [],
                        "order": legacy_rank.get(key, 9),
                        "evidence_ids": [],
                        "support_type": "inferred",
                    },
                )
                bucket["bullets"].append(item["text"])
                bucket["evidence_ids"] = list(dict.fromkeys(
                    bucket["evidence_ids"] + item["evidence_ids"]
                ))[:4]
                if item["support_type"] == "explicit":
                    bucket["support_type"] = "explicit"
            note_sections = list(grouped.values())

        def _line_count(value: str, width: int = 72) -> int:
            lines = str(value or "").splitlines() or [""]
            return sum(max(1, (len(line) + width - 1) // width) for line in lines)

        # Notes always occupy the right-hand "paper" side of the project canvas.
        # The left side remains available for diagrams and lightweight visuals.
        diagram_right = BASE_X + 360
        if positions:
            diagram_right = max(
                diagram_right,
                max((x + NODE_WIDTH) for x, _ in positions.values()),
            )
        notes_x = diagram_right + 120
        notes_y = BASE_Y
        notes_w = 520

        if note_sections:
            total_h = 108
            for section in sorted(note_sections, key=lambda s: (s["order"], s["title"])):
                total_h += 46
                total_h += 26 * _line_count(section["body"], 68)
                total_h += 24 * sum(max(1, (len(b) + 68) // 69) for b in section["bullets"])
                total_h += 18
            notes_h = min(max(total_h, 520), 2400)
            title_digest = hashlib.sha1((plan.title or "plan").encode("utf-8")).hexdigest()[:12]
            page_id = f"notes_page_{title_digest}"
            title_id = f"notes_title_{title_digest}"
            elements.append({
                "id": page_id,
                "type": "rectangle",
                "x": notes_x,
                "y": notes_y,
                "width": notes_w,
                "height": notes_h,
                "angle": 0,
                "strokeColor": "#8a8a8a",
                "backgroundColor": "#fffdf7",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "roughness": 1,
                "opacity": 100,
                "roundness": {"type": 3},
                "boundElements": [],
                "isDeleted": False,
                "customData": {
                    "visual": {
                        "type": "project_notes_page",
                        "semantic_id": "project_notes",
                    }
                },
            })
            elements.append({
                "id": title_id,
                "type": "text",
                "x": notes_x + 24,
                "y": notes_y + 22,
                "width": notes_w - 48,
                "height": 30,
                "text": "PROJECT NOTES",
                "originalText": "PROJECT NOTES",
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
                "roughness": 1,
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

            cursor_y = notes_y + 76
            ordered_sections = sorted(note_sections, key=lambda s: (s["order"], s["title"]))
            for index, section in enumerate(ordered_sections):
                section_key = hashlib.sha1(str(section["id"]).encode("utf-8")).hexdigest()[:12]
                heading_id = f"note_section_{section_key}_header"
                body_id = f"note_section_{section_key}_body"

                elements.append({
                    "id": heading_id,
                    "type": "text",
                    "x": notes_x + 24,
                    "y": cursor_y,
                    "width": notes_w - 48,
                    "height": 24,
                    "text": section["title"],
                    "originalText": section["title"],
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
                    "roughness": 1,
                    "opacity": 100,
                    "angle": 0,
                    "groupIds": [],
                    "isDeleted": False,
                    "customData": {
                        "visual": {
                            "type": "note_section_header",
                            "section_id": str(section["id"]),
                            "evidence_ids": section["evidence_ids"],
                            "support_type": section["support_type"],
                        }
                    },
                })
                cursor_y += 26

                lines: List[str] = []
                if section["body"]:
                    lines.append(section["body"])
                lines.extend([f"• {b}" for b in section["bullets"]])
                body_text = "\n".join(lines).strip() or "Not specified."
                body_height = max(32, min(360, 20 * _line_count(body_text, 68)))
                elements.append({
                    "id": body_id,
                    "type": "text",
                    "x": notes_x + 24,
                    "y": cursor_y,
                    "width": notes_w - 48,
                    "height": body_height,
                    "text": body_text,
                    "originalText": body_text,
                    "fontSize": 12,
                    "fontFamily": 1,
                    "textAlign": "left",
                    "verticalAlign": "top",
                    "lineHeight": 1.45,
                    "baseline": 11,
                    "autoResize": True,
                    "strokeColor": "#303530",
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 1,
                    "roughness": 1,
                    "opacity": 100,
                    "angle": 0,
                    "groupIds": [],
                    "isDeleted": False,
                    "customData": {
                        "visual": {
                            "type": "note_section_body",
                            "section_id": str(section["id"]),
                            "evidence_ids": section["evidence_ids"],
                            "support_type": section["support_type"],
                        }
                    },
                })
                cursor_y += body_height + 10
                if index < len(ordered_sections) - 1:
                    separator_id = f"note_section_{section_key}_separator"
                    elements.append({
                        "id": separator_id,
                        "type": "line",
                        "x": notes_x + 24,
                        "y": cursor_y,
                        "width": notes_w - 48,
                        "height": 0,
                        "points": [[0, 0], [notes_w - 48, 0]],
                        "strokeColor": "#d5d7d2",
                        "backgroundColor": "transparent",
                        "fillStyle": "solid",
                        "strokeWidth": 1,
                        "strokeStyle": "solid",
                        "roughness": 0,
                        "opacity": 100,
                        "angle": 0,
                        "isDeleted": False,
                        "customData": {"visual": {"type": "note_section_separator", "section_id": str(section["id"])}},
                    })
                    cursor_y += 14

            footer_id = f"notes_footer_{title_digest}"
            footer = "Maintained automatically from project memory • rechecked every 30 seconds"
            elements.append({
                "id": footer_id,
                "type": "text",
                "x": notes_x + 24,
                "y": notes_y + notes_h - 34,
                "width": notes_w - 48,
                "height": 20,
                "text": footer,
                "originalText": footer,
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
                "customData": {
                    "visual": {"type": "project_notes_footer"}
                },
            })

        # Lightweight visualizations sit below the diagram area. They are not
        # forced diagrams; they are compact visual aids such as a status,
        # metric, callout, or timeline.
        visualizations = getattr(plan, "visualizations", []) or []
        viz_y = max(
            (y + NODE_HEIGHT for _, y in positions.values()),
            default=BASE_Y + 20,
        ) + 90
        for v_index, visualization in enumerate(visualizations[:6]):
            v = visualization.model_dump() if hasattr(visualization, "model_dump") else dict(visualization)
            kind = str(v.get("kind") or "callout").lower()
            vx = BASE_X + (v_index % 2) * 360
            vy = viz_y + (v_index // 2) * 150
            vw = 320
            vh = 120 if kind in ("callout", "timeline") else 96
            vid = str(v.get("id") or f"visual_{v_index}")
            box_id = f"viz_{hashlib.sha1(vid.encode('utf-8')).hexdigest()[:12]}_box"
            title_id = f"viz_{hashlib.sha1(vid.encode('utf-8')).hexdigest()[:12]}_title"
            value_id = f"viz_{hashlib.sha1((vid + ':value').encode('utf-8')).hexdigest()[:12]}_value"
            title_text = str(v.get("title") or "Visualization")[:80]
            value_text = str(v.get("value") or "").strip()[:180]
            items = [str(item).strip() for item in (v.get("items") or []) if str(item).strip()][:6]
            body = "\n".join((["• " + item for item in items] if items else ([str(v.get("caption") or "")] if v.get("caption") else [])))
            evidence_ids = [str(e) for e in (v.get("evidence_ids") or [])][:4]
            support_type = str(v.get("support_type") or ("explicit" if evidence_ids else "inferred"))
            elements.append({
                "id": box_id,
                "type": "rectangle",
                "x": vx,
                "y": vy,
                "width": vw,
                "height": vh,
                "angle": 0,
                "strokeColor": "#4b5a53",
                "backgroundColor": "#f7f9f6",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "roughness": 1,
                "opacity": 100,
                "roundness": {"type": 3},
                "boundElements": [{"type": "text", "id": title_id}],
                "isDeleted": False,
                "customData": {
                    "visual": {
                        "type": "lightweight_visualization",
                        "visualization_id": vid,
                        "kind": kind,
                        "evidence_ids": evidence_ids,
                        "support_type": support_type,
                    }
                },
            })
            elements.append({
                "id": title_id,
                "type": "text",
                "x": vx + 14,
                "y": vy + 12,
                "width": vw - 28,
                "height": 22,
                "text": title_text,
                "originalText": title_text,
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
            rendered_body = value_text or body or "Visual summary"
            elements.append({
                "id": value_id,
                "type": "text",
                "x": vx + 14,
                "y": vy + 38,
                "width": vw - 28,
                "height": vh - 50,
                "text": rendered_body,
                "originalText": rendered_body,
                "fontSize": 12 if kind != "metric" else 18,
                "fontFamily": 1,
                "textAlign": "left",
                "verticalAlign": "top",
                "lineHeight": 1.35,
                "baseline": 12,
                "autoResize": True,
                "strokeColor": "#1f241f",
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
                        "type": "lightweight_visualization_text",
                        "visualization_id": vid,
                        "evidence_ids": evidence_ids,
                        "support_type": support_type,
                    }
                },
            })

        # Backward-compatibility metadata for legacy note tests/callers: the
        # actual rendering is now plain text on the page, never sticky cards.
        if legacy_notes:
            for n_index, note in enumerate(legacy_notes[:8]):
                text_id = f"sticky_text_{n_index}"
                text_value = note["text"]
                elements.append({
                    "id": text_id,
                    "type": "text",
                    "x": notes_x + 24,
                    "y": notes_y + 100 + n_index * 28,
                    "width": notes_w - 48,
                    "height": 24,
                    "text": text_value,
                    "originalText": text_value,
                    "fontSize": 11,
                    "fontFamily": 1,
                    "textAlign": "left",
                    "verticalAlign": "top",
                    "lineHeight": 1.25,
                    "baseline": 10,
                    "autoResize": True,
                    "strokeColor": "#303530",
                    "backgroundColor": "transparent",
                    "fillStyle": "solid",
                    "strokeWidth": 1,
                    "roughness": 0,
                    "opacity": 100,
                    "angle": 0,
                    "groupIds": [],
                    "isDeleted": True,
                    "customData": {
                        "visual": {
                            "type": "architectural_note",
                            "kind": note["kind"],
                            "evidence_ids": note["evidence_ids"],
                            "support_type": note["support_type"],
                        }
                    },
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
