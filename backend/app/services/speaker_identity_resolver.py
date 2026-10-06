"""Deterministic speaker-to-person resolution for captured Google Meet transcripts.

The service deliberately avoids biometric identification and LLM-based guessing.
It uses explicit self-identification phrases ("I'm Siddhi", "mera naam Siddhi hai")
as high-confidence evidence and optionally cross-checks names against the participant
roster returned by Vexa. Unresolved speakers remain unresolved.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


_GENERIC_SPEAKER_PATTERNS = (
    re.compile(r"^speaker(?:[_ -]?\\d+)?$", re.IGNORECASE),
    re.compile(r"^unknown(?: speaker| participant)?$", re.IGNORECASE),
    re.compile(r"^speaker$", re.IGNORECASE),
)

_INTRO_PATTERNS = (
    re.compile(
        r"\\b(?:hi[ ,.!-]*)?(?:i am|i'm|im|my name is|this is)\\s+"
        r"([A-Za-z][A-Za-z'.-]*(?:\\s+[A-Za-z][A-Za-z'.-]*){0,3})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\\b(?:mera\\s+naam)\\s+"
        r"([A-Za-z][A-Za-z'.-]*(?:\\s+[A-Za-z][A-Za-z'.-]*){0,3})\\s+hai\\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\\bmain\\s+"
        r"([A-Za-z][A-Za-z'.-]*(?:\\s+[A-Za-z][A-Za-z'.-]*){0,3})\\s+hoon\\b",
        re.IGNORECASE,
    ),
)

_STOPWORDS = {
    "i",
    "im",
    "i'm",
    "my",
    "name",
    "is",
    "this",
    "the",
    "one",
    "here",
    "from",
    "and",
    "working",
    "joining",
    "today",
    "speaking",
    "a",
    "an",
    "main",
    "mera",
    "naam",
    "hai",
    "hoon",
}


def normalize_person_name(value: Optional[str]) -> str:
    value = re.sub(r"\\s+", " ", str(value or "").strip())
    value = value.strip(" \\t\\r\\n.,!?;:()[]{}<>\"'")
    return value


def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_person_name(value).lower())


def is_generic_speaker(value: Optional[str]) -> bool:
    name = normalize_person_name(value)
    if not name:
        return True
    return any(pattern.fullmatch(name) for pattern in _GENERIC_SPEAKER_PATTERNS)


def _clean_extracted_name(value: str) -> str:
    tokens = []
    for token in normalize_person_name(value).split():
        if token.lower() in _STOPWORDS:
            break
        tokens.append(token)
    return normalize_person_name(" ".join(tokens))


def roster_names_from_vexa(payload: Optional[Dict[str, Any]], bot_name: str = "") -> List[str]:
    """Extract unique human candidate names from Vexa's participants endpoint."""
    if not isinstance(payload, dict):
        return []

    names: List[str] = []
    seen = set()
    bot_key = _name_key(bot_name)

    for item in payload.get("participants") or []:
        if not isinstance(item, dict):
            continue
        name = normalize_person_name(item.get("name"))
        if not name or is_generic_speaker(name):
            continue
        if bot_key and _name_key(name) == bot_key:
            continue
        key = _name_key(name)
        if key and key not in seen:
            seen.add(key)
            names.append(name)

    return names


def _match_known_name(text: str, known_names: Iterable[str]) -> Optional[Tuple[str, float]]:
    lowered = normalize_person_name(text).lower()
    matches = []
    for name in known_names:
        normalized = normalize_person_name(name)
        key = _name_key(normalized)
        if not key:
            continue
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", re.IGNORECASE)
        if pattern.search(lowered):
            matches.append((normalized, 1.0))
            continue

        compact_name = re.sub(r"[^a-z0-9 ]+", "", normalized.lower())
        compact_text = re.sub(r"[^a-z0-9 ]+", "", lowered)
        if compact_name and re.search(rf"(?<![a-z0-9]){re.escape(compact_name)}(?![a-z0-9])", compact_text):
            matches.append((normalized, 0.97))

    if not matches:
        return None
    matches.sort(key=lambda pair: len(_name_key(pair[0])), reverse=True)
    return matches[0]


def _extract_intro_name(text: str, known_names: Iterable[str]) -> Optional[Tuple[str, float]]:
    known_match = _match_known_name(text, known_names)
    if known_match:
        # A known roster name appearing in an explicit intro gets the strongest score.
        prefix = normalize_person_name(text).lower()
        if any(p.search(prefix) for p in _INTRO_PATTERNS):
            return known_match

    for pattern in _INTRO_PATTERNS:
        match = pattern.search(text or "")
        if not match:
            continue
        candidate = _clean_extracted_name(match.group(1))
        if candidate:
            return candidate, 0.92
    return None


class SpeakerIdentityResolver:
    """Resolve generic diarization labels only from explicit evidence."""

    def resolve(
        self,
        segments: List[Dict[str, Any]],
        *,
        known_names: Optional[Iterable[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        names = [
            normalize_person_name(name)
            for name in (known_names or [])
            if normalize_person_name(name)
        ]
        by_speaker: Dict[str, List[Tuple[str, float, str]]] = defaultdict(list)

        for segment in segments:
            raw_speaker = normalize_person_name(
                segment.get("raw_speaker") or segment.get("speaker") or "Unknown Speaker"
            )
            if not is_generic_speaker(raw_speaker):
                continue
            match = _extract_intro_name(str(segment.get("text") or ""), names)
            if match:
                by_speaker[raw_speaker].append((match[0], match[1], "self_introduction"))

        proposed: Dict[str, Tuple[str, float, str, str]] = {}
        name_to_speakers: Dict[str, set[str]] = defaultdict(set)

        for raw_speaker, observations in by_speaker.items():
            scores: Dict[str, float] = defaultdict(float)
            source_by_name: Dict[str, str] = {}
            for name, score, source in observations:
                scores[_name_key(name)] = max(scores[_name_key(name)], score)
                source_by_name[_name_key(name)] = source
            if not scores:
                continue

            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            best_key, best_score = ranked[0]
            ties = [key for key, score in ranked if abs(score - best_score) < 1e-9]
            if len(ties) != 1 or best_score < 0.90:
                continue

            best_name = next((name for name in [n for n in names] if _name_key(name) == best_key), None)
            if not best_name:
                for observation_name, observation_score, _ in observations:
                    if _name_key(observation_name) == best_key:
                        best_name = observation_name
                        best_score = max(best_score, observation_score)
                        break
            if best_name:
                is_roster_match = any(_name_key(name) == best_key for name in names)
                proposed[raw_speaker] = (
                    best_name,
                    min(
                        0.99 if is_roster_match else 0.94,
                        best_score + min(0.03, max(0, len(observations) - 1) * 0.01),
                    ),
                    source_by_name[best_key],
                    "confirmed" if is_roster_match else "provisional",
                )
                name_to_speakers[_name_key(best_name)].add(raw_speaker)

        # Never allow one claimed human name to be silently assigned to multiple
        # speaker clusters. Ambiguous mappings remain unresolved.
        for name_key, speaker_ids in name_to_speakers.items():
            if len(speaker_ids) > 1:
                for speaker_id in speaker_ids:
                    proposed.pop(speaker_id, None)

        resolved_segments: List[Dict[str, Any]] = []
        resolved_summary: Dict[str, Dict[str, Any]] = {}

        for segment in segments:
            item = dict(segment)
            raw_speaker = normalize_person_name(
                segment.get("raw_speaker") or segment.get("speaker") or "Unknown Speaker"
            ) or "Unknown Speaker"
            item["raw_speaker"] = raw_speaker

            if raw_speaker in proposed:
                display_name, confidence, source, identity_status = proposed[raw_speaker]
                item["speaker"] = display_name
                item["speaker_name"] = display_name
                item["speaker_identity_status"] = identity_status
                item["speaker_identity_confidence"] = confidence
                item["speaker_identity_source"] = source
                resolved_summary[raw_speaker] = {
                    "display_name": display_name,
                    "status": identity_status,
                    "confidence": confidence,
                    "source": source,
                }
            else:
                item["speaker"] = normalize_person_name(segment.get("speaker")) or raw_speaker
                item["speaker_name"] = item["speaker"]
                item["speaker_identity_status"] = (
                    "not_applicable" if not is_generic_speaker(raw_speaker) else "unresolved"
                )
                item["speaker_identity_confidence"] = (
                    1.0 if not is_generic_speaker(raw_speaker) else 0.0
                )
                item["speaker_identity_source"] = (
                    "provider_label" if not is_generic_speaker(raw_speaker) else "none"
                )
                resolved_summary[raw_speaker] = {
                    "display_name": item["speaker"],
                    "status": item["speaker_identity_status"],
                    "confidence": item["speaker_identity_confidence"],
                    "source": item["speaker_identity_source"],
                }

            resolved_segments.append(item)

        confirmed = sum(1 for value in resolved_summary.values() if value["status"] == "confirmed")
        provisional = sum(1 for value in resolved_summary.values() if value["status"] == "provisional")
        unresolved = sum(1 for value in resolved_summary.values() if value["status"] == "unresolved")
        return resolved_segments, {
            "confirmed_speakers": confirmed,
            "provisional_speakers": provisional,
            "unresolved_speakers": unresolved,
            "total_speaker_keys": len(resolved_summary),
            "speaker_map": resolved_summary,
        }
