"""Pack a snapshot without changing canonical memory or silently hiding gaps."""

from __future__ import annotations

import copy
import json
import math
from typing import Any, Dict

from app.services.memory_retrieval import excerpt, excerpt_record, query_groups, relevance


def serialized_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _compact_item(item: Any, query: str | None, max_chars: int = 1100) -> tuple[Any, bool]:
    if isinstance(item, str):
        text, start, end = excerpt(item, query, max_chars)
        return text, bool(start or end < len(item))
    if not isinstance(item, dict):
        return copy.deepcopy(item), False
    result = copy.deepcopy(item)
    excerpts = {}
    for field in ("text", "content", "details", "detail", "description", "role", "summary", "title",
                  "current_state_reference", "proposed_change_reference"):
        if isinstance(result.get(field), str) and len(result[field]) > max_chars:
            original = result[field]
            result[field], start, end = excerpt(original, query, max_chars)
            excerpts[field] = {"start": start, "end": end, "original_chars": len(original)}
    if excerpts:
        result["excerpts"] = excerpts
    return result, bool(excerpts)


def pack_agent_context(context: Dict[str, Any], query: str | None = None, token_budget: int = 6000) -> Dict[str, Any]:
    """Enforce a UTF-8 byte cap with a documented token estimate.

    Three UTF-8 bytes per token is an estimate, not a provider tokenizer.
    Serialized bytes are the hard limit. IDs, statuses, and provenance survive
    packing; strings become marked excerpts and skipped items are counted.
    """
    if not 512 <= token_budget <= 32000:
        raise ValueError("token_budget must be between 512 and 32000")
    max_bytes = token_budget * 3
    root = {key: copy.deepcopy(value) for key, value in context.items() if key not in {
        "project_state", "knowledge", "evidence", "project_memory", "prior_agent_outputs", "conflicts"
    }}
    state = context.get("project_state", {})
    root["project_state"] = {}
    metadata = {
        "token_budget": token_budget, "max_serialized_bytes": max_bytes,
        "estimated_tokens": 0, "serialized_bytes": 0,
        "token_estimate_method": "utf8_bytes_divided_by_3",
        "omitted_items": {}, "excerpted_items": 0,
        "complete": True, "evidence_is_source_material": True,
    }
    root["context_metadata"] = metadata
    for key in ("project_id", "version", "title", "vision", "updated_at"):
        if key not in state:
            continue
        value = state[key]
        if isinstance(value, str) and key in {"title", "vision"}:
            limit = min(800 if key == "vision" else 200, max(64, token_budget // 8))
            text, start, end = excerpt(value, query, limit)
            root["project_state"][key] = text
            if start or end < len(value):
                metadata["excerpted_items"] += 1
                metadata.setdefault("state_excerpts", {})[key] = {
                    "start": start, "end": end, "original_chars": len(value)
                }
        else:
            root["project_state"][key] = copy.deepcopy(value)

    sections = [key for key, value in state.items() if isinstance(value, list)]
    for key in sections:
        root["project_state"][key] = []
    for key in ("conflicts", "knowledge", "evidence", "prior_agent_outputs"):
        root[key] = []

    # Reserve space for the omission report before attempting additions.
    counts = {"state." + key: len(state[key]) for key in sections}
    counts.update({key: len(context.get(key, [])) for key in ("conflicts", "knowledge", "evidence", "prior_agent_outputs")})
    metadata["omitted_items"] = dict(counts)
    payload_cap = max_bytes - 160

    def append_items(path: str, items: list, target: list, ceiling: int, field: str | None = None):
        for item in items:
            compact, clipped = _compact_item(item, query)
            if field and isinstance(item, dict):
                compact = excerpt_record(item, field, query, 1100)
                clipped = "excerpt" in compact
            target.append(compact)
            if serialized_bytes(root) > ceiling:
                target.pop()
                # Try a smaller source excerpt before omitting a useful item.
                if field and isinstance(item, dict):
                    compact = excerpt_record(item, field, query, 240)
                    clipped = "excerpt" in compact
                else:
                    compact, clipped = _compact_item(item, query, 240)
                target.append(compact)
                if serialized_bytes(root) > ceiling:
                    target.pop()
                    continue
            metadata["omitted_items"][path] -= 1
            if clipped:
                metadata["excerpted_items"] += 1

    # Conflicts and enduring constraints/decisions precede optional detail.
    append_items("conflicts", context.get("conflicts", []), root["conflicts"], int(payload_cap * 0.25))
    groups = query_groups(query)
    priorities = [key for key in ("constraints", "decisions", "open_questions") if key in sections]
    priorities += [key for key in sections if key not in priorities]
    for key in priorities:
        items = list(state[key])
        if groups:
            items.sort(key=lambda item: relevance(json.dumps(item, ensure_ascii=False, default=str), groups), reverse=True)
        append_items("state." + key, items, root["project_state"][key], int(payload_cap * 0.50))
    append_items("knowledge", context.get("knowledge", []), root["knowledge"], int(payload_cap * 0.72), "content")
    append_items("evidence", context.get("evidence", []), root["evidence"], int(payload_cap * 0.96), "text")
    append_items("prior_agent_outputs", context.get("prior_agent_outputs", []), root["prior_agent_outputs"], payload_cap)

    metadata["omitted_items"] = {key: count for key, count in metadata["omitted_items"].items() if count}
    metadata["complete"] = not metadata["omitted_items"] and not metadata["excerpted_items"]
    # An input can have oversized identity fields; fail clearly instead of
    # returning something above the promised cap or truncating an identifier.
    for _ in range(4):
        metadata["serialized_bytes"] = serialized_bytes(root)
        metadata["estimated_tokens"] = math.ceil(metadata["serialized_bytes"] / 3)
    if serialized_bytes(root) > max_bytes:
        raise ValueError("Context identity metadata exceeds the context budget")
    return root
