"""Unknown Context living board: one Excalidraw page for unassigned notes.

Every item that the Agent cannot map to a project gets one free note on the
Unknown Context board: the item's raw content wrapped at the note width,
with the note height growing as the wrapped content grows, stacked
vertically with a 12px gap. Provenance (source, sender, evidence link,
suggested projects) is never rendered as a fixed note template; it lives
only in each element's customData. No human triage tab is required: the
board IS the triage surface.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.context_resolution import PossibleProjectMatch, UnknownContextItem, UnknownItemStatus
from app.models.project import Project, SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID

logger = logging.getLogger(__name__)

BOARD_TITLE = "Unknown Context Board"

# Free-note geometry, shared in spirit with the Atlas Unknown column:
# raw content wrapped at the note text width (server-side _wrap_text),
# height growing per wrapped line, notes stacked with a 12px gap.
NOTE_X = 80
NOTE_Y = 80
NOTE_W = 640
NOTE_GAP = 12
NOTE_PAD_X = 18
NOTE_PAD_Y = 16
NOTE_FONT_SIZE = 12


def _match_reasons(match: PossibleProjectMatch) -> List[str]:
    try:
        value = json.loads(match.similarity_reason_json or "[]")
        return [str(v) for v in value if v][:3]
    except Exception:
        return []


def pending_board_items(db: Session, tenant_id: str = "default_tenant", limit: int = 30) -> List[Dict[str, Any]]:
    items = (
        db.query(UnknownContextItem)
        .filter(
            UnknownContextItem.tenant_id == tenant_id,
            UnknownContextItem.status == UnknownItemStatus.PENDING.value,
        )
        .order_by(UnknownContextItem.created_at.desc())
        .limit(limit)
        .all()
    )
    cards: List[Dict[str, Any]] = []
    for item in items:
        matches = (
            db.query(PossibleProjectMatch)
            .filter(PossibleProjectMatch.unknown_item_id == item.id)
            .all()
        )
        suggestion_names: List[str] = []
        suggestion_ids: List[str] = []
        for match in matches[:2]:
            suggestion_ids.append(match.candidate_project_id)
            project = db.query(Project).filter(Project.id == match.candidate_project_id).first()
            suggestion_names.append(project.name if project else match.candidate_project_id)
        best_name: str = suggestion_names[0] if suggestion_names else ""
        best_reasons: List[str] = _match_reasons(matches[0]) if matches else []
        try:
            payload = json.loads(item.payload_json or "{}")
        except Exception:
            payload = {}
        sender = item.actor_id or payload.get("sender_name") or "unknown"
        cards.append(
            {
                "item_id": item.id,
                "content": item.content or "",
                "sender": sender,
                "source": item.source,
                "evidence_id": item.evidence_id,
                "meeting_id": item.meeting_id,
                "source_event_id": item.source_event_id,
                "suggested_project": best_name,
                "suggestions": suggestion_names,
                "suggestion_ids": suggestion_ids,
                "reasons": best_reasons,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
        )
    return cards


def _note_height(content: str, text_width: float) -> int:
    """Note height for raw content wrapped at ``text_width`` (never capped)."""
    from app.services.excalidraw_compiler import _wrap_text

    wrapped = _wrap_text(content, max(60.0, float(text_width)), NOTE_FONT_SIZE)
    lines = max(1, len(wrapped.split("\n")))
    text_h = float(NOTE_FONT_SIZE) * 1.3 * lines + 6
    return int(round((NOTE_PAD_Y * 2) + text_h))


def _free_note_elements(card: Dict[str, Any], x: float, y: float):
    """One free note for one pending item: rect + its raw content text.

    The only visible text is the item's raw content (server-wrapped).
    Everything else is provenance and stays in customData (no warning
    header, no "Should go to:" line, no item id).
    """
    from app.services.excalidraw_compiler import _wrap_text

    content = (card.get("content") or "").strip() or "(no text)"
    text_width = NOTE_W - (NOTE_PAD_X * 2)
    note_h = _note_height(content, text_width)
    wrapped = _wrap_text(content, max(60.0, float(text_width)), NOTE_FONT_SIZE)
    provenance = {
        "type": "unknown_item",
        "item_id": card["item_id"],
        "source": card.get("source"),
        "sender": card.get("sender"),
        "evidence_id": card.get("evidence_id"),
        "meeting_id": card.get("meeting_id"),
        "source_event_id": card.get("source_event_id"),
        "suggested_project": card.get("suggested_project") or "",
        "suggestions": (card.get("suggestions") or [])[:2],
        "suggestion_ids": (card.get("suggestion_ids") or [])[:2],
        "reasons": (card.get("reasons") or [])[:3],
        "created_at": card.get("created_at"),
    }
    custom = {
        "unknown_context": provenance,
        "visual": {
            "note_kind": "unknown_item",
            "unknown_item_id": card["item_id"],
            "evidence_ids": [card["evidence_id"]] if card.get("evidence_id") else [card["item_id"]],
        },
    }
    note_id = f"unknown_note_{card['item_id']}"
    text_id = f"{note_id}:content"
    rect = {
        "id": note_id,
        "type": "rectangle",
        "x": x,
        "y": y,
        "width": NOTE_W,
        "height": note_h,
        "angle": 0,
        "strokeColor": "#b45309",
        "backgroundColor": "#fffbeb",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "roughness": 1,
        "opacity": 100,
        "roundness": {"type": 3},
        "boundElements": [{"type": "text", "id": text_id}],
        "isDeleted": False,
        "customData": custom,
    }
    text = {
        "id": text_id,
        "type": "text",
        "x": x + NOTE_PAD_X,
        "y": y + NOTE_PAD_Y,
        "width": text_width,
        "height": note_h - (NOTE_PAD_Y * 2),
        "text": wrapped,
        "originalText": wrapped,
        "fontSize": NOTE_FONT_SIZE,
        "fontFamily": 1,
        "textAlign": "left",
        "verticalAlign": "top",
        "lineHeight": 1.25,
        "baseline": NOTE_FONT_SIZE,
        "autoResize": False,
        "containerId": note_id,
        "strokeColor": "#3e3426",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "roughness": 1,
        "opacity": 100,
        "angle": 0,
        "groupIds": [],
        "isDeleted": False,
        "customData": custom,
    }
    return [rect, text], note_h


AGENT_FOCUS = (
    "UNKNOWN CONTEXT BOARD MODE. These items could not be assigned to a project. "
    "Design this board freely: notes, groupings, sketches, or diagrams - whatever "
    "best reveals what the items are about. Items that explicitly name the same "
    "concept or project may be grouped or diagrammed together. When two or more "
    "items describe the same named concept, ALSO draw it as a diagram: the "
    "concept as a node, each stated feature as a connected node, with labelled "
    "relationships - do not leave a multi-item concept as prose only. Cite "
    "the item id in evidence_ids for everything drawn from an item. Do NOT invent "
    "project assignments, facts, or links between unrelated items, and do not "
    "create project columns. Every item must remain represented; anything you "
    "do not use will be appended verbatim below your canvas."
)


def _raw_note_elements(cards: List[Dict[str, Any]], start_y: float):
    elements: List[Dict[str, Any]] = []
    cursor_y = start_y
    for card in cards:
        note_elements, note_h = _free_note_elements(card, NOTE_X, cursor_y)
        elements.extend(note_elements)
        cursor_y += note_h + NOTE_GAP
    return elements


def _item_represented(card: Dict[str, Any], elements: List[Dict[str, Any]]) -> bool:
    content_head = " ".join((card.get("content") or "").split())[:60]
    for el in elements:
        if card["item_id"] in json.dumps(el.get("customData") or {}):
            return True
        text = " ".join(str(el.get("text") or "").split())
        if content_head and content_head in text:
            return True
    return False


def _board_elements(cards: List[Dict[str, Any]], db: Session, tenant_id: str):
    """Agent-designed board when a design provider answers, raw notes otherwise.

    The agent is free-form here (notes, groupings, diagrams). Coverage is
    then verified item by item: anything the design did not represent is
    appended verbatim as a raw free note below the agent canvas, so no
    pending item can silently disappear. With no provider (or a failed
    compile) the board is exactly the raw stacked notes.
    """
    if not cards:
        return [], "deterministic"
    try:
        from app.services.excalidraw_compiler import ExcalidrawCompiler
        from app.services.excalidraw_service import ExcalidrawService
        from app.services.visual_plan_service import VisualPlanService

        artifact = ExcalidrawService().get_or_create_artifact(
            SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, db, tenant_id=tenant_id, name=BOARD_TITLE
        )
        try:
            current_scene = json.loads(artifact.elements_json or "[]")
        except (TypeError, ValueError):
            current_scene = []
        current_nodes = [
            str(el.get("text") or "")[:120]
            for el in current_scene[:120]
            if isinstance(el, dict) and str(el.get("text") or "").strip()
        ]
        plan, ai_status = VisualPlanService().build_plan(
            state_summary={
                "title": BOARD_TITLE,
                "unassigned_context": [
                    {
                        "item_id": card["item_id"],
                        "content": card["content"],
                        "source": card["source"],
                        "sender": card["sender"],
                        "suggested_project": card["suggested_project"],
                    }
                    for card in cards
                ],
            },
            current_nodes=current_nodes,
            evidence_snippets=[
                {"id": card["item_id"], "content": card["content"], "source": card["source"]}
                for card in cards
            ],
            focus_prompt=AGENT_FOCUS,
            constraints=None,
        )
        if ai_status != "ai":
            return _raw_note_elements(cards, NOTE_Y), "deterministic"
        elements = ExcalidrawCompiler().compile(plan, enforce_grounding=False)
        uncovered = [card for card in cards if not _item_represented(card, elements)]
        if uncovered:
            bottom = max(
                float(el.get("y") or 0) + float(el.get("height") or 0) for el in elements
            )
            elements = elements + _raw_note_elements(uncovered, bottom + 24)
            logger.info(
                "unknown_board_agent_coverage_appended: missing=%d of %d",
                len(uncovered), len(cards),
            )
        return elements, "ai"
    except Exception as exc:
        logger.warning("unknown_board_agent_design_failed: %s", exc)
        return _raw_note_elements(cards, NOTE_Y), "deterministic"


def render_unknown_context_board(db: Session, tenant_id: str = "default_tenant") -> Dict[str, Any]:
    """Rebuild the Unknown Context board from current pending items.

    The board REPLACES its previous content (no replication). The agent
    designs it freely (notes, groupings, diagrams); items its design does
    not represent are appended as raw free notes, and with no design
    provider the board is exactly one raw free note per pending item,
    stacked vertically with a 12px gap, provenance only in customData.
    """
    from app.services.excalidraw_service import ExcalidrawService
    from app.services.visual_revision_service import VisualRevisionService
    from app.models.excalidraw import ExcalidrawProposal, ExcalidrawProposalStatus

    cards = pending_board_items(db, tenant_id=tenant_id)
    elements, ai_status = _board_elements(cards, db, tenant_id)
    if not elements:
        elements.append(
            {
                "id": "unknown_empty",
                "type": "text",
                "x": NOTE_X,
                "y": NOTE_Y,
                "width": NOTE_W,
                "height": 24,
                "text": "No unassigned notes",
                "originalText": "No unassigned notes",
                "fontSize": 14,
                "fontFamily": 1,
                "textAlign": "left",
                "verticalAlign": "top",
                "lineHeight": 1.25,
                "baseline": 12,
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
                "customData": {"unknown_context": {"type": "unknown_empty"}},
            }
        )
    labels = [
        (card["content"] or "").strip().splitlines()[0][:90] if (card["content"] or "").strip() else card["item_id"]
        for card in cards
    ]

    service = ExcalidrawService()
    artifact = service.get_or_create_artifact(
        SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, db, tenant_id=tenant_id, name=BOARD_TITLE
    )
    # REPLACE (never replicate): the unknown board always mirrors pending items.
    artifact.elements_json = json.dumps(elements)
    artifact.app_state_json = json.dumps({"unknown_item_ids": [card["item_id"] for card in cards], "ai_status": ai_status})
    artifact.extracted_nodes_json = json.dumps(labels)
    artifact.version += 1
    artifact.updated_at = datetime.now(timezone.utc)
    VisualRevisionService().commit_revision(
        project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        scene=elements,
        db=db,
        tenant_id=tenant_id,
        operations=[{"op_type": "update", "payload": {"action": "unknown_board_refresh"}}],
        actor_id="synora_agent",
        reason=f"Unknown board refreshed: {len(cards)} pending notes",
        workspace_name=BOARD_TITLE,
    )
    proposal = ExcalidrawProposal(
        artifact_id=artifact.id,
        project_id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
        tenant_id=tenant_id,
        derived_from_state_version=1,
        status=ExcalidrawProposalStatus.APPROVED.value,
        approved_at=datetime.now(timezone.utc),
        approved_by="synora_agent",
        reason=f"Unknown board refresh: {len(cards)} pending notes",
        proposed_elements_json=json.dumps(elements),
        diff_preview_json=json.dumps({"nodes_after": labels, "ai_status": ai_status}),
        evidence_ids_json="[]",
    )
    db.add(proposal)
    db.commit()
    db.refresh(artifact)
    logger.info("unknown_board_refreshed: notes=%d version=%d", len(cards), artifact.version)
    return {"ok": True, "notes": len(cards), "artifact_version": artifact.version, "ai_status": ai_status}
