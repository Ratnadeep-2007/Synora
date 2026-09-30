"""Unknown Context living board: one Excalidraw page for unassigned notes.

Every item that the Agent cannot map to a project still gets a visible note
on the Unknown Context board, annotated with its best-guess project (if any).
No human triage tab is required: the board IS the triage surface.
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
        best_name: str = ""
        best_reasons: List[str] = []
        if matches:
            best = matches[0]
            project = db.query(Project).filter(Project.id == best.candidate_project_id).first()
            best_name = project.name if project else best.candidate_project_id
            best_reasons = _match_reasons(best)
        try:
            payload = json.loads(item.payload_json or "{}")
        except Exception:
            payload = {}
        sender = item.actor_id or payload.get("sender_name") or "unknown"
        cards.append(
            {
                "item_id": item.id,
                "content": (item.content or "")[:400],
                "sender": sender,
                "source": item.source,
                "suggested_project": best_name,
                "reasons": best_reasons,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
        )
    return cards


def render_unknown_context_board(db: Session, tenant_id: str = "default_tenant") -> Dict[str, Any]:
    """Rebuild the Unknown Context board from current pending items.

    The board REPLACES its previous content (no replication): one note per
    pending item, each annotated with the project it should go to.
    """
    from app.services.excalidraw_compiler import ExcalidrawCompiler
    from app.services.excalidraw_service import ExcalidrawService
    from app.services.visual_revision_service import VisualRevisionService
    from app.models.excalidraw import ExcalidrawProposal, ExcalidrawProposalStatus
    from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship

    cards = pending_board_items(db, tenant_id=tenant_id)
    nodes: List[VisualNode] = []
    for idx, card in enumerate(cards):
        label = (card["content"] or "")[:90] or "Unassigned note"
        annotations = [f"From: {card['sender']} via {card['source']}"]
        if card["suggested_project"]:
            annotations.append(f"Should go to: {card['suggested_project']}")
        else:
            annotations.append("Should go to: (no confident project yet)")
        annotations.extend(card["reasons"][:2])
        nodes.append(
            VisualNode(
                id=f"unknown_{idx}_{card['item_id'][:8]}",
                label=label,
                node_type="note",
                group="Unknown Context",
                emphasis="muted",
                annotations=annotations[:3],
            )
        )
    if not nodes:
        nodes.append(
            VisualNode(
                id="unknown_empty",
                label="No unassigned notes",
                node_type="note",
                group="Unknown Context",
                emphasis="muted",
                annotations=["Agent will place new unassigned notes here"],
            )
        )
    plan = VisualPlan(
        title=BOARD_TITLE,
        layout_direction="vertical",
        nodes=nodes,
        relationships=[
            VisualRelationship(source=nodes[i].id, target=nodes[i + 1].id, style="dashed")
            for i in range(max(0, len(nodes) - 1))
        ],
        notes=["Agent-maintained board of unassigned context"],
        model="deterministic",
        prompt_version="unknown-board-v1",
    )
    elements = ExcalidrawCompiler().compile(plan)
    labels = [n.label for n in plan.nodes]

    service = ExcalidrawService()
    artifact = service.get_or_create_artifact(
        SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, db, tenant_id=tenant_id, name=BOARD_TITLE
    )
    # REPLACE (never replicate): the unknown board always mirrors pending items.
    artifact.elements_json = json.dumps(elements)
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
        diff_preview_json=json.dumps({"nodes_after": labels, "ai_status": "deterministic"}),
        evidence_ids_json="[]",
    )
    db.add(proposal)
    db.commit()
    db.refresh(artifact)
    logger.info("unknown_board_refreshed: notes=%d version=%d", len(cards), artifact.version)
    return {"ok": True, "notes": len(cards), "artifact_version": artifact.version}
