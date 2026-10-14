"""Proactive memory for Synora (Mem0 proactive-memory patterns, plan.md).

Canonical memory stays in Synora's DB; this layer only decides WHEN to
surface it and precomputes WHAT to surface:

- Pattern 1 (session-start scan): before the first message, probe memory
  with ambient context (project, open file/topic, time of day) and return
  blockers, active decisions, and precomputed hints.
- Pattern 2 (context-trigger scan): a DEMAND/NO_DEMAND gate (deterministic
  signals + optional LLM classifier with regex fallback) decides whether a
  context shift is worth a retrieval. Acknowledgments never fire it.
- Pattern 3 (scheduled reflection hints): after reflection, unresolved
  blockers/decisions are precomputed into ProactiveHint rows so the next
  session start is a pure lookup with zero LLM cost.

All proactive operations are deduped (ProactiveEvent keys) and cooled down
(PROACTIVE_MIN_INTERVAL_SECONDS): knowing when NOT to fire is the point.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.proactive_memory import ProactiveEvent, ProactiveHint
from app.services.memory_provider import MemoryRetrievalProvider, get_retrieval_provider

logger = logging.getLogger(__name__)

_DEMAND_PATTERNS = (
    r"\b[\w\-]+\.(py|ts|tsx|js|jsx|java|go|rs|rb|sql|yaml|yml|json|toml|md)\b",
    r"\b(error|bug|blocker|blocked|failing|failure|issue|deploy|deployment|migration|migrate)\b",
    r"\b(where we left off|last session|previous session|pick up|resume)\b",
    r"\b(decision|decided|kyu|kyun|why did we)\b",
    r"\b(new project|topic change|switch to|dusra|dusri|ab .*project)\b",
    r"\b(check|dikhao|batao|status)\b",
)
_ACK_PATTERNS = (
    r"^\s*(ok|okay|thanks|thank you|got it|sounds good|theek hai|thik hai|samajh gaya|done|great|perfect|nice)\W*$",
)


def _fallback_query(message: str) -> str:
    cleaned = " ".join((message or "").strip().split())
    return cleaned[:200] if cleaned else "recent task context"


def detect_intent(
    message: str,
    history: Optional[List[Dict[str, Any]]] = None,
    llm_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """DEMAND/NO_DEMAND gate. LLM classifier is optional and outside the
    memory store; deterministic signals always override a hedged NO_DEMAND
    (and an acknowledgment can never be upgraded to DEMAND)."""
    text = (message or "").strip()
    lowered = text.lower()
    if any(re.match(pattern, lowered) for pattern in _ACK_PATTERNS):
        return {"decision": "NO_DEMAND", "query": None, "source": "ack"}
    regex_demand = any(re.search(pattern, lowered) for pattern in _DEMAND_PATTERNS)

    if llm_client is not None:
        try:
            from pydantic import BaseModel

            class _IntentResult(BaseModel):
                decision: str
                query: Optional[str] = None

            recent = "\n".join(
                f"{item.get('role', 'user')}: {item.get('content', '')}" for item in (history or [])[-4:]
            ) or "(start of conversation)"
            prompt = (
                "Decide whether the latest message warrants searching long-term project memory.\n"
                "DEMAND when it names a file/module/project, references past work or a decision, "
                "starts a new task or switches topic, or mentions an error/blocker/deploy step.\n"
                "NO_DEMAND for short acknowledgments or direct continuations.\n"
                f"Recent history:\n{recent}\nLatest message: {text}\n"
                'Return JSON: {"decision": "DEMAND"|"NO_DEMAND", "query": str|null}'
            )
            raw = llm_client.generate_structured(prompt, _IntentResult)
            decision = "DEMAND" if str(raw.decision).upper().startswith("DEMAND") else "NO_DEMAND"
            query = raw.query if isinstance(raw.query, str) and raw.query else None
            if decision == "NO_DEMAND" and regex_demand:
                return {"decision": "DEMAND", "query": query or _fallback_query(text), "source": "regex_fallback"}
            if decision == "DEMAND" and not query:
                query = _fallback_query(text)
            return {"decision": decision, "query": query, "source": "llm"}
        except Exception as exc:
            logger.warning("proactive_intent_classifier_failed: %s", exc)

    if regex_demand:
        return {"decision": "DEMAND", "query": _fallback_query(text), "source": "regex"}
    return {"decision": "NO_DEMAND", "query": None, "source": "regex"}


def _json_list(raw: Optional[str]) -> List[Any]:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def _item_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("title") or item.get("content") or item.get("text") or "").strip()
    return str(item or "").strip()


class ProactiveMemoryService:
    def __init__(self, provider: Optional[MemoryRetrievalProvider] = None):
        self.provider = provider

    # ------------------------------------------------------------------
    # Dedupe / cooldown (ProactiveEvent log)
    # ------------------------------------------------------------------
    @staticmethod
    def _event_key(kind: str, project_id: Optional[str], user_id: Optional[str], digest: str = "") -> str:
        raw = f"{kind}:{project_id or ''}:{user_id or ''}:{digest}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _record_event(self, db: Session, kind: str, project_id: Optional[str], user_id: Optional[str], digest: str = "") -> bool:
        """True when this exact operation is new (not a duplicate)."""
        key = self._event_key(kind, project_id, user_id, digest)
        if db.query(ProactiveEvent).filter(ProactiveEvent.event_key == key).first():
            return False
        db.add(ProactiveEvent(
            id=f"pev_{key[:24]}", event_key=key, kind=kind,
            project_id=project_id, user_id=user_id,
            payload_json=json.dumps({"digest": digest}),
        ))
        db.commit()
        return True

    def _in_cooldown(self, db: Session, kind: str, project_id: Optional[str], user_id: Optional[str]) -> bool:
        latest = (
            db.query(ProactiveEvent)
            .filter(ProactiveEvent.kind == kind, ProactiveEvent.project_id == project_id, ProactiveEvent.user_id == user_id)
            .order_by(ProactiveEvent.created_at.desc())
            .first()
        )
        if not latest or not latest.created_at:
            return False
        created = latest.created_at
        if created.tzinfo is None:  # SQLite returns naive datetimes
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created).total_seconds()
        return age < int(settings.PROACTIVE_MIN_INTERVAL_SECONDS)

    def _provider(self) -> MemoryRetrievalProvider:
        return self.provider or get_retrieval_provider()

    # ------------------------------------------------------------------
    # Pattern 3: precompute hints (zero LLM at session start)
    # ------------------------------------------------------------------
    def refresh_hints(self, db: Session, project_id: str, tenant_id: str = "default_tenant") -> Dict[str, Any]:
        from app.models.project_state import ProjectState

        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        candidates: List[tuple] = []
        if state:
            for item in _json_list(state.open_questions_json)[:2]:
                if _item_text(item):
                    candidates.append(("blocker", f"Unresolved: {_item_text(item)[:160]}"))
            for item in _json_list(state.decisions_json)[:1]:
                if _item_text(item):
                    candidates.append(("decision", f"Decided: {_item_text(item)[:160]}"))
            for item in _json_list(state.constraints_json)[:1]:
                if _item_text(item):
                    candidates.append(("constraint", f"Constraint: {_item_text(item)[:160]}"))

        created = 0
        for kind, text in candidates[: int(settings.PROACTIVE_MAX_HINTS)]:
            digest = hashlib.sha256(f"{project_id}:{kind}:{text}".encode("utf-8")).hexdigest()
            if db.query(ProactiveHint).filter(
                ProactiveHint.project_id == project_id, ProactiveHint.dedupe_hash == digest
            ).first():
                continue
            db.add(ProactiveHint(
                id=f"phint_{digest[:24]}", tenant_id=tenant_id, project_id=project_id,
                kind=kind, text=text, dedupe_hash=digest,
                source_refs_json=json.dumps({"state_version": state.current_version if state else None}),
            ))
            created += 1
        if created:
            db.commit()
        return {"created": created, "candidates": len(candidates)}

    # ------------------------------------------------------------------
    # Pattern 1: session-start scan (project opened)
    # ------------------------------------------------------------------
    def session_start_scan(
        self,
        db: Session,
        project_id: str,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        tenant_id: str = "default_tenant",
    ) -> Dict[str, Any]:
        from app.models.project import Project
        from app.models.project_state import ProjectState

        context = context or {}
        project = db.query(Project).filter(Project.id == project_id).first()
        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()

        # Refresh precomputed hints lazily when stale; bounded and LLM-free.
        self.refresh_hints(db, project_id, tenant_id=tenant_id)
        hints = (
            db.query(ProactiveHint)
            .filter(ProactiveHint.project_id == project_id)
            .order_by(ProactiveHint.created_at.desc())
            .limit(int(settings.PROACTIVE_MAX_HINTS))
            .all()
        )

        hour = datetime.now(timezone.utc).hour
        time_of_day = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
        probe_parts = [f"What is blocked or recently decided in {project.name if project else project_id}"]
        if context.get("open_file"):
            probe_parts.append(f"related to {context['open_file']}")
        if context.get("topic"):
            probe_parts.append(str(context["topic"]))
        probe = " ".join(probe_parts) + f"? It is {time_of_day}."

        suppressed = self._in_cooldown(db, "session_scan", project_id, user_id)
        memories: List[Dict[str, Any]] = []
        if not suppressed:
            try:
                memories = self._provider().search(db, project_id, probe, limit=4)
            except Exception as exc:
                logger.warning("proactive_session_search_failed: %s", exc)
            self._record_event(db, "session_scan", project_id, user_id, digest=probe)
            now = datetime.now(timezone.utc)
            for hint in hints:
                hint.surface_count = int(hint.surface_count or 0) + 1
                hint.last_surfaced_at = now
            db.commit()

        return {
            "project_id": project_id,
            "project_name": project.name if project else None,
            "state_version": state.current_version if state else 0,
            "probe": probe,
            "suppressed": suppressed,
            "hints": [{"id": h.id, "kind": h.kind, "text": h.text} for h in hints],
            "blockers": [_item_text(i) for i in (_json_list(state.open_questions_json) if state else [])[:3] if _item_text(i)],
            "active_decisions": [_item_text(i) for i in (_json_list(state.decisions_json) if state else [])[:3] if _item_text(i)],
            "memories": memories,
        }

    # ------------------------------------------------------------------
    # Pattern 2: context-trigger scan (topic shift / demand gate)
    # ------------------------------------------------------------------
    def on_context_message(
        self,
        db: Session,
        project_id: str,
        message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
        llm_client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        intent = detect_intent(message, history=history, llm_client=llm_client)
        if intent["decision"] != "DEMAND":
            return {"decision": "NO_DEMAND", "query": None, "memories": [], "suppressed": False}
        if self._in_cooldown(db, "context_scan", project_id, user_id):
            return {"decision": "DEMAND", "query": intent["query"], "memories": [], "suppressed": True}
        memories: List[Dict[str, Any]] = []
        try:
            memories = self._provider().search(db, project_id, intent["query"] or message, limit=4)
        except Exception as exc:
            logger.warning("proactive_context_search_failed: %s", exc)
        self._record_event(db, "context_scan", project_id, user_id, digest=intent["query"] or message[:80])
        return {"decision": "DEMAND", "query": intent["query"], "memories": memories, "suppressed": False}

    # ------------------------------------------------------------------
    # Proactive event: project created -> recheck pending Unknown Context
    # ------------------------------------------------------------------
    def on_project_created(self, db: Session, project: Any, tenant_id: str = "default_tenant") -> Dict[str, Any]:
        """Suggest (never assign) the new project for matching unknown items."""
        from app.models.context_resolution import PossibleProjectMatch, UnknownContextItem, UnknownItemStatus
        from app.services.memory_retrieval import query_groups, relevance

        if getattr(project, "is_system", False):
            return {"suggested": 0}
        groups = query_groups(f"{project.name} {project.description or ''}")
        if not groups:
            return {"suggested": 0}
        items = (
            db.query(UnknownContextItem)
            .filter(
                UnknownContextItem.tenant_id == tenant_id,
                UnknownContextItem.status == UnknownItemStatus.PENDING.value,
            )
            .order_by(UnknownContextItem.created_at.desc())
            .limit(50)
            .all()
        )
        suggested = 0
        for item in items:
            if relevance(item.content or "", groups) < 0.35:
                continue
            exists = db.query(PossibleProjectMatch).filter(
                PossibleProjectMatch.unknown_item_id == item.id,
                PossibleProjectMatch.candidate_project_id == project.id,
            ).first()
            if exists:
                continue
            db.add(PossibleProjectMatch(
                unknown_item_id=item.id,
                candidate_project_id=project.id,
                similarity_reason_json=json.dumps([
                    f"Proactive recheck: new project '{project.name}' matches this unassigned item. Assignment stays a human action."
                ]),
                recommendation="review",
            ))
            suggested += 1
        if suggested:
            db.commit()
            logger.info("proactive_project_created_suggestions: project=%s suggested=%d", project.id, suggested)
        return {"suggested": suggested}
