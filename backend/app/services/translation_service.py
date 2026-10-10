"""Post-transcription translation for Hindi-first meetings.

Vexa records, Sarvam/Whisper transcribe in the spoken language. This service
translates transcript segments into English (Sarvam Translate) so the agent,
memory, and canvases work on English text while the original is preserved
alongside. Any failure degrades to originals-only — translation never blocks
the pipeline.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# Script ranges mapped to BCP-47 source codes. Devanagari defaults to
# Hindi (this product is Hindi-first); callers can override per meeting
# with the STT-detected language.
_SCRIPT_LANGUAGE = [
    ("hi-IN", re.compile("[\u0900-\u097f]")),
    ("bn-IN", re.compile("[\u0980-\u09ff]")),
    ("pa-IN", re.compile("[\u0a00-\u0a7f]")),
    ("gu-IN", re.compile("[\u0a80-\u0aff]")),
    ("ta-IN", re.compile("[\u0b80-\u0bff]")),
    ("te-IN", re.compile("[\u0c00-\u0c7f]")),
    ("kn-IN", re.compile("[\u0c80-\u0cff]")),
    ("ml-IN", re.compile("[\u0d00-\u0d7f]")),
]

_BASE_LANGUAGE = {
    "hi": "hi-IN", "mr": "hi-IN", "bn": "bn-IN", "pa": "pa-IN",
    "gu": "gu-IN", "ta": "ta-IN", "te": "te-IN", "kn": "kn-IN",
    "ml": "ml-IN", "or": "or-IN", "en": "en-IN",
}


def guess_source_language(text: str) -> str:
    """Best-effort BCP-47 source code from script ranges."""
    for code, pattern in _SCRIPT_LANGUAGE:
        if pattern.search(text or ""):
            return code
    return "hi-IN"


def normalize_source_language(code: str, sample: str = "") -> str:
    """Normalize an STT language tag (hi, hi-IN, unknown, ...) to BCP-47."""
    base = str(code or "").strip().lower().split("-")[0].split("_")[0]
    if base in _BASE_LANGUAGE:
        return _BASE_LANGUAGE[base]
    return guess_source_language(sample)


def needs_translation(text: str) -> bool:
    """True when the text contains Indic-script characters.

    Roman-script Hindi (codemix in Latin letters) is a DELIBERATE skip,
    pinned by test_roman_hinglish_skipped below. Rationale: it is
    indistinguishable from English to a script detector, so translating
    it would mean either LLM-detecting every segment (spends Groq TPM —
    the system's scarcest resource) or translating everything (burns
    Sarvam quota for near-zero gain, since the extraction LLMs already
    read Roman Hindi fluently). Revisit only if quota pressure eases.
    """
    return bool(
        re.search(
            "[\u0900-\u097f\u0980-\u09ff\u0a00-\u0a7f\u0a80-\u0aff"
            "\u0b00-\u0b7f\u0b80-\u0bff\u0c00-\u0c7f\u0c80-\u0cff"
            "\u0d00-\u0d7f\u0d80-\u0dff]",
            text or "",
        )
    )


def _chunk_texts(texts: List[str], max_chars: int) -> List[List[int]]:
    """Group text indices into chunks of at most max_chars (by joined size)."""
    groups: List[List[int]] = []
    current: List[int] = []
    current_len = 0
    for index, text in enumerate(texts):
        size = len(text) + 8  # numbering prefix + newline overhead
        if current and current_len + size > max_chars:
            groups.append(current)
            current, current_len = [], 0
        current.append(index)
        current_len += size
    if current:
        groups.append(current)
    return groups


def translate_texts(
    texts: List[str],
    *,
    target_language: str = "en-IN",
    source_language: str = "",
    timeout_seconds: float = 60.0,
) -> Tuple[List[str], str]:
    """Translate texts to the target language via Sarvam Translate.

    Returns (translated_or_original_texts, status) where status is one of
    'translated', 'partial', 'skipped' (nothing needed it), 'disabled',
    or 'unavailable' (any failure — callers keep the originals).
    """
    from app.core.config import settings

    if not texts:
        return [], "skipped"
    if not bool(settings.SARVAM_TRANSLATE_ENABLED):
        return list(texts), "disabled"
    if not settings.SARVAM_API_KEY.strip():
        return list(texts), "disabled"

    pending = [i for i, text in enumerate(texts) if needs_translation(text)]
    if not pending:
        return list(texts), "skipped"

    import httpx

    max_chars = max(200, int(settings.SARVAM_TRANSLATE_MAX_CHARS))
    out = list(texts)
    translated_count = 0
    # The live API rejects source 'auto': resolve one source code for the
    # batch from the caller's STT language, falling back to script detection.
    first_pending = next((texts[i] for i in pending), "")
    source_code = normalize_source_language(source_language, first_pending)
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            for group in _chunk_texts([texts[i] for i in pending], max_chars):
                numbered = "\n".join(
                    f"{n + 1}) {texts[pending[n]]}" for n in group
                )
                # Map chunk-relative line numbers back to pending indices.
                line_order = [pending[n] for n in group]
                response = client.post(
                    "https://api.sarvam.ai/translate",
                    headers={
                        "api-subscription-key": settings.SARVAM_API_KEY.strip(),
                        "Content-Type": "application/json",
                    },
                    json={
                        "input": numbered,
                        "source_language_code": source_code,
                        "target_language_code": target_language,
                        "model": settings.SARVAM_TRANSLATE_MODEL,
                    },
                )
                if response.status_code >= 400:
                    logger.warning(
                        "sarvam_translate_http_%s: %s",
                        response.status_code,
                        response.text[:200],
                    )
                    continue
                translated = str(response.json().get("translated_text") or "")
                lines = translated.split("\n")
                if len(lines) != len(line_order):
                    logger.warning(
                        "sarvam_translate_line_mismatch: expected=%d got=%d",
                        len(line_order),
                        len(lines),
                    )
                    continue
                for text_index, line in zip(line_order, lines):
                    # Strip the "N) " prefix we added.
                    stripped = re.sub(r"^\d+\)\s*", "", line).strip()
                    if stripped:
                        out[text_index] = stripped
                        translated_count += 1
    except Exception as exc:
        logger.warning("sarvam_translate_failed: %s", exc)
        return list(texts), "unavailable"

    if translated_count == 0:
        return list(texts), "unavailable"
    status = "translated" if translated_count == len(pending) else "partial"
    return out, status


def preferred_text(content: str, metadata_json: str = "") -> str:
    """English-first text for intelligence consumers.

    Returns the stored English translation when present, else the
    original content. This is the formal 'prefer English' rule — but
    note it is NOT yet wired into the eight ev.content consumers
    (router, extractors, canvas planners). Reason: zero translated rows
    exist today, so rewiring saves zero tokens while touching every LLM
    prompt path. Wire it per-consumer once Hindi meetings land and TPM
    is measured. The helper exists so that adoption is a one-line swap.
    """
    original = str(content or "")
    try:
        import json as _json

        meta = _json.loads(metadata_json or "{}")
        candidate = str((meta or {}).get("text_en") or "").strip()
        if candidate and candidate != original.strip():
            return candidate
    except Exception:
        pass
    return original


def translate_segments(
    segments: List[Dict[str, object]],
    source_language: str = "",
) -> Tuple[Dict[str, str], str, str]:
    """Translate transcript segments.

    Returns ({segment_id: english}, status, translation_source) where
    translation_source is the resolved BCP-47 code actually sent to the
    API. Callers store it alongside the STT-detected language: when the
    two disagree (e.g. STT 'unknown' vs script-detected 'hi-IN'), the
    disagreement itself is provenance.
    """
    from app.core.config import settings

    texts = [str(seg.get("text") or "") for seg in segments]
    ids = [str(seg.get("id") or f"seg_{i:06d}") for i, seg in enumerate(segments)]
    first_pending = next((t for t in texts if needs_translation(t)), "")
    source = normalize_source_language(source_language, first_pending)
    translated, status = translate_texts(
        texts,
        target_language=settings.SARVAM_TRANSLATE_TARGET,
        source_language=source_language,
    )
    return dict(zip(ids, translated)), status, source
