"""Shared conversation-continuity builder for every source.

WhatsApp and Meet use the SAME continuity logic:

1. Group/thread-scoped context first - recent messages from the SAME
   WhatsApp group (matched by group_jid, then group_name) or the
   neighbouring Meet transcript segments.
2. Cross-source context second - a WhatsApp reply ("yes, ship it") only
   makes sense combined with the Meet discussion it continues, and a Meet
   segment only makes sense combined with the WhatsApp thread that
   preceded it.

The window is a plain-text signal appended to the semantic prompt. It can
suggest a project but never authorizes one - the routing gate still
enforces deterministic authorization.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

GROUP_MESSAGE_LIMIT = 6
CROSS_SOURCE_LIMIT = 4
LINE_BUDGET = 1500


def _payload_dict(raw: Optional[str]) -> Dict[str, Any]:
    try:
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _text_of(payload: Dict[str, Any]) -> str:
    for key in ("text", "content", "caption", "summary"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:280]
    return ""


def build_continuity_window(
    db: Session,
    tenant_id: str = "default_tenant",
    group_name: Optional[str] = None,
    group_jid: Optional[str] = None,
    current_text: str = "",
    actor_jid: Optional[str] = None,
    group_limit: int = GROUP_MESSAGE_LIMIT,
    cross_limit: int = CROSS_SOURCE_LIMIT,
) -> str:
    """Build the continuity window for one incoming WhatsApp message."""
    from app.models.source_event import SourceEvent

    lines: List[str] = []
    if group_name and group_name != "WhatsApp Group":
        lines.append(f"WhatsApp Group: {group_name}")

    try:
        recent = (
            db.query(SourceEvent)
            .filter(
                SourceEvent.source == "whatsapp",
                SourceEvent.tenant_id == tenant_id,
            )
            .order_by(SourceEvent.ingested_at.desc())
            .limit(24)
            .all()
        )
    except Exception:
        return ""

    same_group: List[str] = []
    other_group: List[str] = []
    for ev in recent:
        payload = _payload_dict(ev.payload_json)
        body = _text_of(payload)
        if not body:
            continue
        if current_text and body == current_text[:280]:
            continue
        sender = payload.get("sender_name", "") or ""
        ev_group_jid = payload.get("group_jid", "")
        ev_group_name = payload.get("group_name", "")
        entry = f"- {sender + ': ' if sender else ''}{body}"
        is_same = (
            (group_jid and ev_group_jid and ev_group_jid == group_jid)
            or (group_name and ev_group_name and ev_group_name == group_name)
        )
        if is_same:
            same_group.append(entry)
        else:
            other_group.append(entry)

    for entry in list(reversed(same_group))[:group_limit]:
        lines.append(entry)

    cross = build_cross_source_context(db, tenant_id=tenant_id, limit=cross_limit)
    if cross:
        lines.append("Related Meet discussion:")
        lines.append(cross)

    if not same_group and other_group:
        for entry in list(reversed(other_group))[:2]:
            lines.append(entry)

    return "\n".join(lines)[:LINE_BUDGET]


def build_cross_source_context(
    db: Session, tenant_id: str = "default_tenant", limit: int = CROSS_SOURCE_LIMIT
) -> str:
    """Recent Meet evidence, so a short WhatsApp reply resolves against it."""
    try:
        from app.models.evidence import Evidence

        rows = (
            db.query(Evidence)
            .filter(Evidence.source == "google_meet")
            .order_by(Evidence.created_at.desc())
            .limit(limit)
            .all()
        )
        parts = [f"- Meet: {(r.content or '')[:220]}" for r in rows if r.content]
        return "\n".join(parts)[:800]
    except Exception:
        return ""


def build_meet_continuity(
    db: Session,
    tenant_id: str = "default_tenant",
    meeting_id: Optional[str] = None,
    limit: int = CROSS_SOURCE_LIMIT,
) -> str:
    """Recent WhatsApp thread context for one Meet segment (cross-source)."""
    try:
        from app.models.source_event import SourceEvent

        recent = (
            db.query(SourceEvent)
            .filter(
                SourceEvent.source == "whatsapp",
                SourceEvent.tenant_id == tenant_id,
            )
            .order_by(SourceEvent.ingested_at.desc())
            .limit(limit)
            .all()
        )
        parts: List[str] = []
        for ev in recent:
            body = _text_of(_payload_dict(ev.payload_json))
            if body:
                parts.append(f"- WhatsApp: {body[:220]}")
        return "\n".join(parts)[:800]
    except Exception:
        return ""
