"""Post-render notes verification (token-free, no LLM).

After a canvas is compiled — project notebook or meeting canvas — every
text element is diffed against the support corpus (project memory +
evidence, or meeting evidence). Elements whose significant words mostly
appear in the corpus are verified; the rest are reported as unverified.

This is the enforcement for faithfulness clauses (names, terms,
negations): it cannot prevent an ungrounded sentence, but it guarantees
one is always flagged, badged, and logged — never silently rendered.

Warn-first by design: verification never blocks a sync or drops content.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)

#: Minimum significant words before an element is worth checking.
MIN_CHECK_WORDS = 3
#: Fraction of significant words that must appear in the corpus.
SUPPORT_THRESHOLD = 0.4
#: Cap on reported unverified items (full counts are still returned).
MAX_REPORTED = 20

#: System chrome that is compiler-written, not a factual claim.
SKIPPED_VISUAL_TYPES = frozenset({
    "project_notes_footer",
    "project_notes_subtitle",
    "freeform_visual_connector_label",
    "architecture_group_label",
})
SKIPPED_TEXT_PATTERNS = (
    "rechecked every 30 seconds",
    "maintained automatically from project memory",
)

_STOPWORDS = frozenset(
    "a an the and or but of to in on for with is are was were be been "
    "it its this that these those as at by from will would can could "
    "should have has had not no yes if then than so such per via "
    "ke ki ka ko ne se mein par hai hain tha thi theen aur ya bhi "
    .split()
)

_WORD_RE = re.compile(r"[A-Za-z\u0900-\u097f]{2,}")


def significant_words(text: str) -> List[str]:
    """Lowercased content words: length>=2, stopwords removed."""
    return [
        word.lower()
        for word in _WORD_RE.findall(text or "")
        if word.lower() not in _STOPWORDS
    ]


def _is_skipped(element: Dict[str, Any]) -> bool:
    if element.get("type") != "text":
        return True
    custom = element.get("customData") or {}
    visual = custom.get("visual") if isinstance(custom, dict) else None
    if isinstance(visual, dict) and visual.get("type") in SKIPPED_VISUAL_TYPES:
        return True
    lowered = str(element.get("text") or "").lower()
    return any(pattern in lowered for pattern in SKIPPED_TEXT_PATTERNS)


def verify_scene(
    scene: List[Dict[str, Any]],
    corpus_texts: List[str],
) -> Dict[str, Any]:
    """Diff scene text elements against the corpus.

    Returns {"checked": int, "verified": int, "unverified": [...]} where
    each unverified item is {"element_id", "excerpt", "score"}.
    """
    corpus: Set[str] = set()
    for text in corpus_texts:
        corpus.update(significant_words(text))

    checked = 0
    verified = 0
    unverified: List[Dict[str, Any]] = []
    for element in scene:
        if _is_skipped(element):
            continue
        words = significant_words(str(element.get("text") or ""))
        if len(words) < MIN_CHECK_WORDS:
            continue
        checked += 1
        if not corpus:
            score = 0.0
        else:
            score = sum(1 for word in words if word in corpus) / len(words)
        if score >= SUPPORT_THRESHOLD:
            verified += 1
        elif len(unverified) < MAX_REPORTED:
            unverified.append({
                "element_id": str(element.get("id") or ""),
                "excerpt": str(element.get("text") or "")[:120],
                "score": round(score, 2),
            })

    result = {
        "checked": checked,
        "verified": verified,
        "unverified": unverified,
        "unverified_total": checked - verified,
    }
    if result["unverified_total"]:
        logger.warning(
            "notes_verification_unverified: checked=%d unverified=%d",
            checked,
            result["unverified_total"],
        )
    return result
