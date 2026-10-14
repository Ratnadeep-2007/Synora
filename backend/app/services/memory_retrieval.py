"""Bounded, offline retrieval helpers; scores are relevance, not confidence."""

from __future__ import annotations

import math
import re
from itertools import islice
from typing import Any, Dict, Iterable, List, Sequence

from sqlalchemy import case, or_

STOP_WORDS = frozenset(
    "a an and are as at be been by can could do does for from had has have how "
    "i in is it me my of on or our please should tell that the their them there "
    "these they this to us was we were what when where which who why will with "
    "would you your about show find explain remember project context".split()
)
# Deliberately small and inspectable. This is lexical expansion, not a model
# claiming to understand arbitrary paraphrases.
TERM_FAMILIES = (
    frozenset({"swap", "swapping", "exchange"}),
    frozenset({"auth", "authentication", "login", "signin"}),
    frozenset({"postgres", "postgresql"}),
    frozenset({"db", "database"}),
    frozenset({"deadline", "due"}),
    frozenset({"deploy", "deployment"}),
    frozenset({"notify", "notification"}),
)
INACTIVE_STATUSES = frozenset({"rejected", "superseded", "dismissed"})


def words(text: str) -> List[str]:
    tokens = re.findall(r"[^\W_]+(?:_[^\W_]+)*", (text or "").lower(), re.UNICODE)
    result: List[str] = []
    for token in tokens:
        if len(token) < 2 or token in STOP_WORDS:
            continue
        if any(token in family for family in TERM_FAMILIES):
            result.append(token)
            continue
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us")):
            token = token[:-1]
        result.append(token)
    return result


def query_groups(query: str | None) -> List[frozenset[str]]:
    groups: List[frozenset[str]] = []
    for term in dict.fromkeys(words(query or "")):
        family = next((group for group in TERM_FAMILIES if term in group), frozenset({term}))
        if family not in groups:
            groups.append(family)
        if len(groups) >= 12:
            break
    return groups


def search_predicate(columns: Sequence[Any], groups: Sequence[frozenset[str]]):
    """Parameterized SQL shortlist, ranked before LIMIT so old hits survive."""
    clauses = []
    ranks = []
    for group in groups:
        term_clauses = []
        for column in columns:
            for term in sorted(group):
                escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                term_clauses.append(column.ilike(f"%{escaped}%", escape="\\"))
        clause = or_(*term_clauses)
        clauses.append(clause)
        ranks.append(case((clause, 1), else_=0))
    return or_(*clauses), sum(ranks)


def relevance(text: str, groups: Sequence[frozenset[str]]) -> float:
    if not groups:
        return 0.0
    tokens = set(words(text))
    matches = sum(bool(tokens & group) for group in groups)
    if not matches:
        return 0.0
    # Coverage matters more than length or repetitions of a generic word.
    coverage = matches / len(groups)
    density = matches / math.sqrt(max(1, len(tokens)))
    return round(coverage + min(0.2, density / 5), 4)


def rank_records(records: Iterable[Dict[str, Any]], query: str | None, indexed_hits=None) -> List[Dict[str, Any]]:
    """SQL supplies recency order; stable sorting keeps it only as a tie-break."""
    groups = query_groups(query)
    hits = {hit["id"]: hit for hit in (indexed_hits or [])}
    scored = []
    for record in records:
        copy = dict(record)
        text = str(record.get("title") or "") + " " + str(record.get("content") or record.get("text") or "")
        score = relevance(text, groups)
        hit = hits.get(record.get("id"))
        if hit:
            score += float(hit["rank"]) * 30
            if "start" in hit:
                copy["retrieval_span"] = {"start": hit["start"], "end": hit["end"]}
        if groups and score <= 0:
            continue
        copy["retrieval_score"] = score
        scored.append(copy)
    scored.sort(key=lambda record: (
        record["retrieval_score"],
        str(record.get("status") or "").lower() == "approved",
    ), reverse=True)
    return scored


def excerpt(text: str, query: str | None, max_chars: int = 1600) -> tuple[str, int, int]:
    """Keep a useful window and offsets; never change stored evidence."""
    text = text or ""
    if len(text) <= max_chars:
        return text, 0, len(text)
    groups = query_groups(query)
    lowered = text.lower()
    starts = {0}
    for group in groups:
        for term in group:
            for match in islice(re.finditer(r"\b" + re.escape(term), lowered), 12):
                starts.add(max(0, min(len(text) - max_chars, match.start() - max_chars // 4)))
    start = max(sorted(starts), key=lambda pos: relevance(text[pos:pos + max_chars], groups))
    end = min(len(text), start + max_chars)
    return text[start:end], start, end


def excerpt_record(record: Dict[str, Any], field: str, query: str | None, max_chars: int = 1600) -> Dict[str, Any]:
    copy = dict(record)
    text = str(record.get(field) or "")
    preferred = record.get("retrieval_span")
    if isinstance(preferred, dict):
        start = max(0, min(len(text), int(preferred.get("start", 0))))
        end = min(len(text), start + max_chars)
        content = text[start:end]
    else:
        content, start, end = excerpt(text, query, max_chars)
    copy[field] = content
    if start or end < len(text):
        copy["excerpt"] = {"field": field, "start": start, "end": end, "original_chars": len(text)}
    return copy
