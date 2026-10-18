"""Meet-specific session intelligence built on the shared Synora evidence/memory pipeline.

This service is intentionally source-specific only at the *meeting session* layer.
It does not own a separate memory store or project knowledge system.

It turns a completed transcript into a compact, persisted meeting projection:
- a complete-transcript intelligence view over persisted Synora evidence
- bounded routing/timeline windows for speaker/timestamp navigation
- participants/speakers per window
- topic labels derived from extracted knowledge
- action items with evidence-backed owner hints
- decision / requirement / question highlights
- per-project memory version deltas
- explicit one-sync provenance showing that no Google API call is needed after persistence

The canonical project memory remains ProjectMemoryService.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session, joinedload

from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.models.meeting import Meeting, Transcript, TranscriptEntry
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.services.visual_plan_service import VisualPlanService
from app.services.translation_service import english_note_text, needs_translation

import logging

logger = logging.getLogger(__name__)


DUE_HINT_PATTERN = re.compile(
    r"\b(?:by|before|due(?:\s+on)?|deadline(?:\s+is)?)\s+"
    r"([A-Za-z0-9][A-Za-z0-9 ,./:-]{1,48})",
    re.IGNORECASE,
)

#: Evidence snippets per meeting-canvas plan call. Matches the prompt
#: builder's own cap, so every batch is fully seen by the design model and
#: long meetings no longer lose their early parts.
MEETING_CANVAS_BATCH_SIZE = 16
#: Plan attempts per batch before accepting the deterministic fallback.
#: Retries stay short: this path also serves sync-on-read GET requests.
MEETING_CANVAS_PLAN_ATTEMPTS = 2
MEETING_CANVAS_RETRY_DELAY_S = 10.0


def _semantic_provider_configured() -> bool:
    """True when any LLM design provider could serve a plan (retry is useful)."""
    from app.core.config import settings

    return bool(
        settings.is_groq_configured
        or settings.is_gemini_configured
        or settings.is_meta_configured
        or settings.is_nvidia_nim_configured
    )


def _remap_ids(value: Any, idmap: Dict[str, str]) -> Any:
    """Rewrite batch-local semantic ids inside opaque group payloads."""
    if isinstance(value, str):
        return idmap.get(value, value)
    if isinstance(value, list):
        return [_remap_ids(item, idmap) for item in value]
    if isinstance(value, dict):
        return {key: _remap_ids(item, idmap) for key, item in value.items()}
    return value


def _merge_meeting_plans(plans: List[Any], meeting_title: str) -> Any:
    """Merge per-batch VisualPlans into one compilable plan.

    Batch ids are namespaced (m0_, m1_, ...) so identical model-chosen ids
    across batches cannot collide, and intra-batch references (relationships,
    visualization connectors, group members) are remapped to the new ids.
    Sections keep chronological order via an order offset per batch.
    """
    from app.schemas.visual_plan import VisualPlan

    if len(plans) == 1:
        return plans[0]

    merged_nodes: List[Dict[str, Any]] = []
    merged_rels: List[Dict[str, Any]] = []
    merged_sections: List[Dict[str, Any]] = []
    merged_notes: List[Any] = []
    merged_viz: List[Dict[str, Any]] = []
    merged_groups: List[Any] = []
    merged_emphasis: List[Any] = []
    strategies: List[str] = []
    doc_title: Optional[str] = None
    doc_subtitle: Optional[str] = None
    doc_updated: Optional[str] = None
    order_base = 0

    for index, plan in enumerate(plans):
        tag = f"m{index}"
        idmap: Dict[str, str] = {}
        for node in (plan.nodes or []):
            node_dict = node.model_dump(mode="json")
            new_id = f"{tag}_{node_dict.get('id') or f'node_{len(merged_nodes)}'}"
            idmap[str(node_dict.get("id"))] = new_id
            node_dict["id"] = new_id
            merged_nodes.append(node_dict)
        for rel in (plan.relationships or []):
            rel_dict = rel.model_dump(mode="json")
            rel_dict["source"] = idmap.get(str(rel_dict.get("source")), f"{tag}_{rel_dict.get('source')}")
            rel_dict["target"] = idmap.get(str(rel_dict.get("target")), f"{tag}_{rel_dict.get('target')}")
            merged_rels.append(rel_dict)
        # Sections may live on notes_sections, inside notes_document, or
        # both (dedupe by id so a section is never recorded twice).
        seen_section_ids: set = set()
        raw_sections: List[Any] = []
        if plan.notes_document is not None:
            raw_sections.extend(plan.notes_document.sections or [])
        raw_sections.extend(plan.notes_sections or [])
        for section in raw_sections:
            if section.id in seen_section_ids:
                continue
            seen_section_ids.add(section.id)
            section_dict = section.model_dump(mode="json")
            section_dict["id"] = f"{tag}_{section_dict.get('id')}"
            try:
                section_dict["order"] = int(section_dict.get("order") or 0) + order_base
            except (TypeError, ValueError):
                section_dict["order"] = order_base
            blocks = []
            for block in (section_dict.get("blocks") or []):
                block_dict = dict(block)
                block_dict["id"] = f"{tag}_{block_dict.get('id')}"
                blocks.append(block_dict)
            section_dict["blocks"] = blocks
            merged_sections.append(section_dict)
        document = plan.notes_document
        if document is not None:
            doc_dict = document.model_dump(mode="json")
            if doc_title is None:
                doc_title = doc_dict.get("title") or None
                doc_subtitle = doc_dict.get("subtitle")
            doc_updated = doc_dict.get("updated_label") or doc_updated
        merged_notes.extend(plan.notes or [])
        for viz in (plan.visualizations or []):
            viz_dict = viz.model_dump(mode="json")
            viz_dict["id"] = f"{tag}_{viz_dict.get('id')}"
            prim_map: Dict[str, str] = {}
            prims = []
            for prim in (viz_dict.get("elements") or []):
                prim_dict = dict(prim)
                new_pid = f"{tag}_{prim_dict.get('id')}"
                prim_map[str(prim_dict.get("id"))] = new_pid
                prim_dict["id"] = new_pid
                prims.append(prim_dict)
            for prim_dict in prims:
                if str(prim_dict.get("source")) in prim_map:
                    prim_dict["source"] = prim_map[str(prim_dict.get("source"))]
                if str(prim_dict.get("target")) in prim_map:
                    prim_dict["target"] = prim_map[str(prim_dict.get("target"))]
            viz_dict["elements"] = prims
            merged_viz.append(viz_dict)
        for group in (plan.groups or []):
            merged_groups.append(_remap_ids(group, idmap))
        merged_emphasis.extend(plan.emphasis or [])
        strategies.append(plan.canvas_strategy or "mixed")
        order_base += 10000

    strategy = "mixed" if "mixed" in strategies else (strategies[0] if strategies else "mixed")
    first = plans[0]
    # Collapse same-titled sections (e.g. twelve "Notes" sections from
    # twelve deterministic batches) into one section per title, keeping
    # blocks chronological. Without this the merged canvas looks like a
    # fixed template repeated per batch instead of one free document.
    grouped: Dict[str, Dict[str, Any]] = {}
    for section_dict in sorted(merged_sections, key=lambda s: s.get("order", 0)):
        key = str(section_dict.get("title") or "Notes")
        if key not in grouped:
            grouped[key] = dict(section_dict)
            grouped[key]["blocks"] = list(section_dict.get("blocks") or [])
        else:
            grouped[key]["blocks"].extend(section_dict.get("blocks") or [])
            for eid in section_dict.get("evidence_ids") or []:
                if eid not in grouped[key].get("evidence_ids", []):
                    grouped[key].setdefault("evidence_ids", []).append(eid)
    merged_sections = list(grouped.values())
    for order, section_dict in enumerate(merged_sections):
        section_dict["order"] = order
    return VisualPlan.model_validate({
        "title": (first.title if first else None) or meeting_title,
        "canvas_strategy": strategy,
        "nodes": merged_nodes,
        "relationships": merged_rels,
        "groups": merged_groups,
        "emphasis": merged_emphasis,
        "notes_document": {
            "title": doc_title or meeting_title,
            "subtitle": doc_subtitle,
            "sections": merged_sections,
            "updated_label": doc_updated,
        } if (merged_sections or doc_title) else None,
        "notes_sections": merged_sections,
        "visualizations": merged_viz,
        "notes": merged_notes,
        "model": f"merged/{len(plans)}-batches",
        "prompt_version": first.prompt_version if first else "",
    })


class MeetingSessionIntelligenceService:
    """Build and persist the Meet-only session projection.

    The service never creates a parallel memory store. It reads shared Evidence
    and CandidateKnowledge and writes only a source-session projection into the
    existing Meeting.metadata_json field.
    """

    VERSION = "v2"

    @staticmethod
    def segment_entries(
        entries: Sequence[TranscriptEntry],
        window_size: int = 12,
        gap_seconds: int = 45,
    ) -> List[List[TranscriptEntry]]:
        """Create bounded windows for routing and timeline presentation only.

        Windows are bounded by a 45-second timestamp gap or a maximum number
        of entries. They are never used as independent intelligence passes:
        shared intelligence receives the full persisted transcript/evidence
        assigned to each project so long-range conversational context is kept.
        """
        ordered = sorted(
            [entry for entry in entries if entry.text],
            key=lambda entry: entry.start_time or datetime.min.replace(tzinfo=timezone.utc),
        )
        windows: List[List[TranscriptEntry]] = []
        current: List[TranscriptEntry] = []

        for entry in ordered:
            if current:
                prev = current[-1].start_time
                current_start = entry.start_time
                gap_exceeded = (
                    prev is not None
                    and current_start is not None
                    and (current_start - prev).total_seconds() >= gap_seconds
                )
                if gap_exceeded or len(current) >= window_size:
                    windows.append(current)
                    current = []
            current.append(entry)

        if current:
            windows.append(current)

        return windows

    @staticmethod
    def _unique(values: Iterable[str], limit: Optional[int] = None) -> List[str]:
        seen = set()
        result: List[str] = []
        for value in values:
            cleaned = str(value or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            result.append(cleaned)
            if limit and len(result) >= limit:
                break
        return result

    @staticmethod
    def _due_hint(text: str) -> Optional[str]:
        match = DUE_HINT_PATTERN.search(text or "")
        if not match:
            return None
        return match.group(1).strip(" .,:;")

    # Category strings arrive from the extraction model, which is free to pick
    # its own wording ("Decision", "decisions", "decision_candidate",
    # "requirement_candidate", ...). Matching an exact set meant anything the
    # model spelled differently fell through to "knowledge", and the session
    # summary then reported zero decisions and zero requirements for meetings
    # that plainly contained them. Normalising first keeps the view honest.
    _CATEGORY_ALIASES = {
        "decision": "decision",
        "decisions": "decision",
        "decision_candidate": "decision",
        "decisioncandidate": "decision",
        "requirement": "requirement",
        "requirements": "requirement",
        "requirement_candidate": "requirement",
        "requirementcandidate": "requirement",
        "question": "question",
        "questions": "question",
        "open_question": "question",
        "openquestion": "question",
        "action_item": "action_item",
        "action_items": "action_item",
        "actionitem": "action_item",
        "actionitems": "action_item",
        "task": "action_item",
        "todo": "action_item",
        "constraint": "constraint",
        "constraints": "constraint",
        "assumption": "assumption",
        "assumptions": "assumption",
    }

    @staticmethod
    def _candidate_type(candidate: CandidateKnowledge) -> str:
        for raw in (candidate.category, candidate.classification):
            token = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
            if not token:
                continue
            mapped = MeetingSessionIntelligenceService._CATEGORY_ALIASES.get(token)
            if mapped:
                return mapped
            # Tolerate a prefixed form such as "extracted_decision".
            for alias, mapped_type in MeetingSessionIntelligenceService._CATEGORY_ALIASES.items():
                if token.endswith("_" + alias):
                    return mapped_type
        return "knowledge"

    @staticmethod
    def _compact_candidate(candidate: CandidateKnowledge, evidence_map: Mapping[str, Evidence]) -> Dict[str, Any]:
        evidence_ids = []
        try:
            evidence_ids = json.loads(candidate.evidence_ids_json or "[]")
        except (TypeError, ValueError):
            evidence_ids = []

        source_evidence = [evidence_map[eid] for eid in evidence_ids if eid in evidence_map]
        owners = MeetingSessionIntelligenceService._unique(
            [e.actor_id or "" for e in source_evidence],
            limit=3,
        )

        return {
            "id": candidate.id,
            "title": candidate.title,
            "content": candidate.content,
            "project_id": candidate.project_id,
            "classification": candidate.classification,
            "category": candidate.category,
            "confidence": float(candidate.confidence or 0.0),
            "evidence_ids": evidence_ids,
            "owner_hints": owners,
            "due_hint": MeetingSessionIntelligenceService._due_hint(candidate.content or ""),
        }

    def build_session_intelligence(
        self,
        meeting_id: str,
        db: Session,
        candidates: Optional[Sequence[CandidateKnowledge]] = None,
        memory_results: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Build a complete session projection from shared Meet evidence."""
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            raise ValueError(f"Meeting '{meeting_id}' not found.")

        transcript = (
            db.query(Transcript)
            .options(joinedload(Transcript.entries).joinedload(TranscriptEntry.participant))
            .filter(Transcript.meeting_id == meeting_id)
            .order_by(Transcript.created_at.desc())
            .first()
        )

        entries = list(transcript.entries) if transcript else []
        windows = self.segment_entries(entries)

        evidence_records = (
            db.query(Evidence)
            .filter(Evidence.meeting_id == meeting_id)
            .order_by(Evidence.occurred_at.asc())
            .all()
        )
        evidence_map = {e.id: e for e in evidence_records}

        meeting_candidates = list(candidates or [])
        if candidates is None:
            meeting_candidates = (
                db.query(CandidateKnowledge)
                .filter(CandidateKnowledge.meeting_id == meeting_id)
                .order_by(CandidateKnowledge.created_at.asc())
                .all()
            )

        # Routing/timeline windows are only a navigational projection. Candidate
        # extraction and project intelligence are based on the complete persisted
        # Evidence set, so a decision or action is not fragmented at a 45-second
        # boundary. This service never calls the Google API; it reads Synora DB only.
        entry_to_segment: Dict[str, int] = {}
        for segment_index, window in enumerate(windows):
            for entry in window:
                entry_to_segment[entry.id] = segment_index
        evidence_to_segment: Dict[str, int] = {}
        for evidence in evidence_records:
            if evidence.transcript_entry_id in entry_to_segment:
                evidence_to_segment[evidence.id] = entry_to_segment[evidence.transcript_entry_id]

        segments: List[Dict[str, Any]] = []
        for segment_index, window in enumerate(windows):
            segment_candidates = [
                candidate
                for candidate in meeting_candidates
                if any(
                    evidence_to_segment.get(evidence_id) == segment_index
                    for evidence_id in self._candidate_evidence_ids(candidate)
                )
            ]
            speakers = self._unique(
                [
                    entry.participant.display_name
                    if entry.participant and entry.participant.display_name
                    else "Unknown Speaker"
                    for entry in window
                ]
            )
            candidate_topics = [
                candidate.title
                for candidate in segment_candidates
                if self._candidate_type(candidate) != "question"
            ]
            preview = " ".join(
                f"{entry.participant.display_name if entry.participant and entry.participant.display_name else 'Speaker'}: {english_note_text(entry.text, entry.metadata_json, entry.language_code) or 'English translation pending.'}"
                for entry in window[:3]
            )[:900]

            segments.append(
                {
                    "segment_id": f"{meeting_id}:seg{segment_index}",
                    "start_time": window[0].start_time.isoformat() if window and window[0].start_time else None,
                    "end_time": (
                        window[-1].end_time.isoformat()
                        if window and window[-1].end_time
                        else (window[-1].start_time.isoformat() if window and window[-1].start_time else None)
                    ),
                    "entry_count": len(window),
                    "speakers": speakers,
                    "topics": self._unique(candidate_topics, limit=4),
                    "preview": preview,
                    "candidate_ids": self._unique([c.id for c in segment_candidates], limit=12),
                }
            )

        typed: Dict[str, List[Dict[str, Any]]] = {
            "decisions": [],
            "requirements": [],
            "action_items": [],
            "open_questions": [],
            "constraints": [],
            "assumptions": [],
        }
        for candidate in meeting_candidates:
            candidate_type = self._candidate_type(candidate)
            if candidate_type == "decision":
                typed["decisions"].append(self._compact_candidate(candidate, evidence_map))
            elif candidate_type == "requirement":
                typed["requirements"].append(self._compact_candidate(candidate, evidence_map))
            elif candidate_type == "action_item":
                typed["action_items"].append(self._compact_candidate(candidate, evidence_map))
            elif candidate_type == "question":
                typed["open_questions"].append(self._compact_candidate(candidate, evidence_map))
            elif candidate_type == "constraint":
                typed["constraints"].append(self._compact_candidate(candidate, evidence_map))
            elif candidate_type == "assumption":
                typed["assumptions"].append(self._compact_candidate(candidate, evidence_map))

        project_ids = self._unique(
            [candidate.project_id for candidate in meeting_candidates]
            + [e.project_id for e in evidence_records]
        )
        project_ids = [
            project_id
            for project_id in project_ids
            if project_id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
        ]
        memory_delta: List[Dict[str, Any]] = []
        for project_id in project_ids:
            result = (memory_results or {}).get(project_id, {})
            memory_delta.append(
                {
                    "project_id": project_id,
                    "version_before": result.get("state_version_before"),
                    "version_after": result.get("state_version_after"),
                    "applied": int(result.get("applied", 0) or 0),
                    "skipped": int(result.get("skipped", 0) or 0),
                }
            )

        participant_names = self._unique(
            [
                participant.display_name or "Unknown Participant"
                for participant in meeting.participants
            ],
            limit=50,
        )

        summary = (
            f"{len(typed['decisions'])} decisions · "
            f"{len(typed['requirements'])} requirements · "
            f"{len(typed['action_items'])} action items · "
            f"{len(typed['open_questions'])} open questions"
        )
        if project_ids:
            summary += f" across {len(project_ids)} project{'s' if len(project_ids) != 1 else ''}"

        sync_metadata: Dict[str, Any] = {}
        try:
            meeting_metadata = json.loads(meeting.metadata_json or "{}")
            sync_metadata = dict(meeting_metadata.get("synora_meet_sync") or {})
        except (TypeError, ValueError):
            sync_metadata = {}

        sync_metadata.setdefault("retrieval_mode", "completed_meeting_once")
        sync_metadata["intelligence_input"] = "full_persisted_transcript"
        sync_metadata["google_api_calls_after_persistence"] = 0
        sync_metadata["transcript_entry_count"] = len(entries)

        return {
            "version": self.VERSION,
            "meeting_id": meeting_id,
            "provider": meeting.provider,
            "summary": summary,
            "participant_count": len(participant_names),
            "participants": participant_names,
            "transcript_entry_count": len(entries),
            "routing_window_count": len(segments),
            "segment_count": len(segments),
            "segments": segments,
            "decisions": typed["decisions"],
            "requirements": typed["requirements"],
            "action_items": typed["action_items"],
            "open_questions": typed["open_questions"],
            "constraints": typed["constraints"],
            "assumptions": typed["assumptions"],
            "memory_delta": memory_delta,
            "source_sync": sync_metadata,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _candidate_evidence_ids(candidate: CandidateKnowledge) -> List[str]:
        try:
            value = json.loads(candidate.evidence_ids_json or "[]")
        except (TypeError, ValueError):
            value = []
        return [str(item) for item in value if item]

    def persist_session_intelligence(self, meeting_id: str, db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            raise ValueError(f"Meeting '{meeting_id}' not found.")

        try:
            metadata = json.loads(meeting.metadata_json or "{}")
        except (TypeError, ValueError):
            metadata = {}

        metadata["session_intelligence"] = payload
        meeting.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        return payload

    # ------------------------------------------------------------------
    # Free-form Meeting Canvas
    # ------------------------------------------------------------------
    @staticmethod
    def _meeting_canvas_key(meeting_id: str) -> str:
        """Stable visual workspace key that is isolated from any project."""
        return f"meeting_canvas:{meeting_id}"

    # Minor work filter for the canvas ONLY (evidence/transcripts are never
    # touched): greetings, acknowledgments, and one-word filler carry no
    # work content ("haan", "hoga", "hmm", "चलिए।", "हो गया।"). Anything
    # with work substance — development, product, delivery, business of
    # work — is kept regardless of project, speaker, or routing.
    _FILLER_WORDS = frozenset({
        "haan", "haa", "hoga", "hmm", "hm", "ok", "okay", "yes", "no", "right",
        "chalo", "chaliye", "theek", "thik", "achha", "accha", "bas", "ji", "sir",
        "oh", "wow", "hmm", "um", "uh", "er", "ah", "bye", "hello", "hi", "hey",
        "है", "होगा", "हम्म", "हाँ", "चलिए", "देखो", "हो", "गया", "सर", "जी", "अच्छा", "ठीक",
    })
    _WORK_ANCHORS = frozenset({
        "api", "app", "agent", "architecture", "auth", "backend", "build", "bug",
        "canvas", "claims", "client", "code", "component", "cost", "customer",
        "dashboard", "data", "database", "decision", "deliver", "delivery", "deploy",
        "design", "develop", "development", "docker", "endpoint", "engine", "excalidraw",
        "feature", "fix", "flow", "frontend", "implement", "integration", "integrate",
        "launch", "llm", "market", "model", "payment", "pipeline", "plan", "price",
        "pricing", "process", "product", "project", "prototype", "queue", "repo",
        "requirement", "roadmap", "schema", "scope", "server", "service", "software",
        "sprint", "synora", "system", "task", "team", "test", "testing", "timeline",
        "token", "tool", "ui", "user", "users", "ux", "version", "webhook", "workflow",
    })

    @classmethod
    def _is_work_discussion(cls, text: str) -> bool:
        """Minor noise filter: False only for pure filler/casual statements."""
        from app.services.context_intelligence import ContextIntelligenceService

        raw = (text or "").strip()
        if not raw:
            return False
        if ContextIntelligenceService.is_casual_chatter(raw):
            return False
        words = [w.lower() for w in re.findall(r"[^\W_]+", raw, flags=re.UNICODE) if len(w) > 1 or w.isdigit()]
        if not words:
            return False
        if all(word in cls._FILLER_WORDS for word in words):
            return False
        # Very short statements survive only when they carry a work anchor
        # (a product name, a component, a decision word) — not as filler.
        if len(words) <= 2 and not any(word in cls._WORK_ANCHORS for word in words):
            return False
        return True

    @staticmethod
    def _discussion_snippets(
        entries: Sequence[TranscriptEntry],
        evidence_records: Sequence[Evidence],
    ) -> List[Dict[str, Any]]:
        """Complete work discussion for the canvas, in chronological order.

        The meeting canvas is not a project-memory view: it must not be
        limited to routed evidence, extracted candidates, categories, or
        project labels. Transcript entries are therefore the primary source;
        evidence is only a fallback for meetings without a transcript. A
        minor noise filter drops pure filler/casual statements; all work
        content is kept regardless of project or routing.
        """
        snippets: List[Dict[str, Any]] = []
        ordered_entries = sorted(
            [
                entry for entry in entries
                if (entry.text or "").strip()
                and MeetingSessionIntelligenceService._is_work_discussion(entry.text)
            ],
            key=lambda entry: entry.start_time or datetime.min.replace(tzinfo=timezone.utc),
        )
        for entry in ordered_entries:
            text = english_note_text(entry.text, entry.metadata_json, entry.language_code)
            if not text:
                snippets.append({"id": entry.id, "content": "English translation pending. Original transcript preserved as evidence.", "source": "translation_pending"})
                continue
            speaker = "Speaker"
            participant = getattr(entry, "participant", None)
            if participant is not None and participant.display_name:
                speaker = participant.display_name
            else:
                try:
                    metadata = json.loads(entry.metadata_json or "{}")
                    speaker = str(metadata.get("speaker_id") or speaker)
                except (TypeError, ValueError):
                    pass
            snippets.append(
                {
                    "id": entry.id,
                    "content": f"{speaker}: {text}",
                    "source": "meeting_transcript",
                }
            )
        if snippets:
            return snippets
        return [
            {
                "id": evidence.id,
                "content": f"{evidence.actor_id or 'Speaker'}: {english_note_text(evidence.content, evidence.metadata_json) or 'English translation pending. Original evidence preserved.'}",
                "source": evidence.source or "meeting_evidence",
            }
            for evidence in evidence_records
            if evidence.content and evidence.content.strip()
            and MeetingSessionIntelligenceService._is_work_discussion(evidence.content)
        ]

    @staticmethod
    def _global_meeting_outline(
        snippets: List[Dict[str, Any]],
        participant_names: List[str],
    ) -> str:
        """Compact whole-meeting context shared by every chronological batch.

        This is coherence context only, not a content filter: each batch
        still receives its complete chronological slice. Representative
        detailed statements are selected by length and restored to
        chronological order so cross-batch implementation references,
        decisions, and intent remain understandable.
        """
        if not snippets:
            return ""
        indexed = list(enumerate(snippets))
        detailed = sorted(indexed, key=lambda pair: len(pair[1].get("content") or ""), reverse=True)[:12]
        detailed.sort(key=lambda pair: pair[0])
        lines = [
            f"Speakers/participants: {', '.join(participant_names) if participant_names else 'not recorded'}.",
            f"Complete discussion size: {len(snippets)} statements.",
            "Representative detailed statements in chronological order:",
        ]
        lines.extend(
            f"[{index + 1}] {str(snippet.get('content') or '')[:180]}"
            for index, snippet in detailed
        )
        return "\n".join(lines)

    def _build_canvas_plans(
        self,
        meeting: Meeting,
        state_summary: Dict[str, Any],
        current_nodes: List[str],
        evidence_snippets: List[Dict[str, Any]],
        focus_prompt: str,
        global_outline: str = "",
    ) -> Tuple[Any, str, Dict[str, Any]]:
        """Plan the meeting canvas in chronological evidence batches.

        Long meetings exceed what one plan call sees, so evidence is split
        into batches of MEETING_CANVAS_BATCH_SIZE and each batch gets its own
        plan (with one short retry on rate-limit fallback). The batch plans
        are merged into a single compilable plan, so the canvas covers the
        whole meeting — early parts included — in one go.
        """
        planner = VisualPlanService()
        batches = [
            evidence_snippets[i:i + MEETING_CANVAS_BATCH_SIZE]
            for i in range(0, len(evidence_snippets), MEETING_CANVAS_BATCH_SIZE)
        ] or [[]]
        meeting_title = str(meeting.title or meeting.id)

        plans: List[Any] = []
        statuses: List[str] = []
        for index, batch in enumerate(batches):
            if len(batches) == 1:
                part_focus: Optional[str] = focus_prompt
            else:
                part_focus = (
                    f"{focus_prompt} This is chronological PART {index + 1} of {len(batches)}. "
                    "Design this part freely. Use the global meeting context below to understand "
                    "references, implementation intent, decisions, and dependencies that span parts; "
                    "do not omit implementation detail merely because it is also relevant elsewhere.\n\n"
                    f"GLOBAL MEETING CONTEXT (coherence only):\n{global_outline}"
                )
            plan, status = planner.build_plan(
                state_summary=state_summary,
                current_nodes=current_nodes,
                evidence_snippets=batch,
                focus_prompt=part_focus,
                constraints=None,
            )
            if status != "ai" and _semantic_provider_configured():
                # One short retry: transient TPM rate limits clear quickly,
                # and this path also serves sync-on-read GETs, so retries
                # must stay bounded.
                for _ in range(MEETING_CANVAS_PLAN_ATTEMPTS - 1):
                    time.sleep(MEETING_CANVAS_RETRY_DELAY_S)
                    retry_plan, retry_status = planner.build_plan(
                        state_summary=state_summary,
                        current_nodes=current_nodes,
                        evidence_snippets=batch,
                        focus_prompt=part_focus,
                        constraints=None,
                    )
                    if retry_status == "ai":
                        plan, status = retry_plan, retry_status
                        break
            plans.append(plan)
            statuses.append(status)

        merged = plans[0] if len(plans) == 1 else _merge_meeting_plans(plans, meeting_title)
        if all(status == "ai" for status in statuses):
            overall = "ai"
        elif all(status == "deterministic" for status in statuses):
            overall = "deterministic"
        else:
            overall = "partial"
        merged_dashboard = {
            "batches": len(batches),
            "batches_ai": sum(1 for status in statuses if status == "ai"),
        }
        return merged, overall, merged_dashboard

    def sync_meeting_canvas(
        self,
        meeting_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        actor_id: str = "meeting_canvas_agent",
    ) -> Dict[str, Any]:
        """Build the meeting-only Excalidraw canvas from the full discussion.

        This canvas is deliberately independent of Project State and project
        routing. The entire persisted meeting evidence set is the source, so
        the agent can choose any natural note structure and any useful visual
        composition. The stored canvas is a derived view; transcript/evidence
        history remains untouched.
        """
        from app.services.excalidraw_service import ExcalidrawService
        from app.services.excalidraw_compiler import ExcalidrawCompiler, ExcalidrawCompileError
        from app.services.visual_revision_service import VisualRevisionService

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            raise ValueError(f"Meeting '{meeting_id}' not found.")

        evidence_records = (
            db.query(Evidence)
            .filter(Evidence.meeting_id == meeting_id)
            .order_by(Evidence.occurred_at.asc())
            .all()
        )
        transcript = (
            db.query(Transcript)
            .options(joinedload(Transcript.entries).joinedload(TranscriptEntry.participant))
            .filter(Transcript.meeting_id == meeting_id)
            .order_by(Transcript.created_at.desc())
            .first()
        )
        entries = list(transcript.entries) if transcript else []
        participant_names = self._unique(
            [p.display_name or "Unknown Participant" for p in meeting.participants],
            limit=50,
        )

        canvas_key = self._meeting_canvas_key(meeting_id)
        excal = ExcalidrawService()
        artifact = excal.get_or_create_artifact(
            canvas_key,
            db,
            tenant_id=tenant_id,
            name=f"Meeting Notes · {meeting.title or meeting_id}",
        )
        current_scene = self._json_list(artifact.elements_json)
        # Design context only (never a content filter): a short summary of
        # what is already drawn. Feeding hundreds of existing note texts
        # into every batch prompt blows the providers' per-minute token
        # budget and starves the actual design calls.
        current_nodes = []
        for element in current_scene:
            if len(current_nodes) >= 24:
                break
            if not isinstance(element, dict):
                continue
            text_value = str(element.get("text") or "").strip()
            if text_value:
                current_nodes.append(text_value[:100])

        evidence_snippets = self._discussion_snippets(entries, evidence_records)
        _total_statements = (
            sum(1 for entry in entries if (entry.text or "").strip())
            or sum(1 for evidence in evidence_records if (evidence.content or "").strip())
        )
        discussion_filter = {
            "kept": len(evidence_snippets),
            "dropped_noise": max(0, _total_statements - len(evidence_snippets)),
            "total": _total_statements,
        }
        global_outline = self._global_meeting_outline(evidence_snippets, participant_names)

        state_summary = {
            "title": meeting.title or "Meeting Notes",
            "vision": "Free-form working notes for this meeting only.",
            "participants": participant_names,
            "meeting_id": meeting_id,
            "transcript_entry_count": len(entries),
            "discussion_snippet_count": len(evidence_snippets),
            "context_scope": "complete_meeting_discussion",
            "requirements": [],
            "architecture": [],
            "decisions": [],
            "constraints": [],
            "assumptions": [],
            "open_questions": [],
        }
        focus = (
            "MEETING CANVAS MODE. Capture only the substance of this meeting. "
            "Use the complete discussion itself as context. Project routing, candidate categories, "
            "Project State, approval status, and memory filters must NOT decide what you may use. "
            "There are NO required sections, categories, note formats, or diagram types. "
            "Choose the most natural way to record the discussion, freely. "
            "When the discussion is about implementation, turn it into useful implementation notes "
            "and, when helpful, diagrams or flows covering components, interfaces, APIs, data, UI, "
            "responsibilities, dependencies, deployment, bugs and fixes, risks, and unresolved choices. "
            "Preserve technical terms and speaker intent; distinguish what was stated from inference. "
            "Do not import project-wide status, Project State, or information from other meetings. "
            "The workspace outside this canvas handles project routing."
        )

        plan, ai_status, batch_info = self._build_canvas_plans(
            meeting=meeting,
            state_summary=state_summary,
            current_nodes=current_nodes,
            evidence_snippets=evidence_snippets,
            focus_prompt=focus,
            global_outline=global_outline,
        )

        # Enforce the display-language boundary even when a model ignores
        # instructions. Operate only on generated display fields, never on
        # IDs, source evidence, or user-drawn canvas elements.
        withheld_fields = 0
        display_fields = {"title", "subtitle", "text", "label", "items", "rows", "annotations", "notes", "description", "heading"}

        def english_display(value, field=""):
            nonlocal withheld_fields
            if isinstance(value, str):
                if field in display_fields and needs_translation(value):
                    withheld_fields += 1
                    return "English translation pending."
                return value
            if isinstance(value, list):
                return [english_display(item, field) for item in value]
            if isinstance(value, dict):
                return {key: english_display(item, key) for key, item in value.items()}
            return value

        plan = type(plan).model_validate(english_display(plan.model_dump(mode="json")))
        batch_info["notes_language"] = "en"
        batch_info["translation_pending_count"] = sum(snippet.get("source") == "translation_pending" for snippet in evidence_snippets)
        batch_info["non_english_fields_withheld"] = withheld_fields
        if withheld_fields and ai_status == "ai":
            ai_status = "partial"

        try:
            compiled = ExcalidrawCompiler().compile(
                plan,
                enforce_grounding=False,
            )
        except ExcalidrawCompileError as exc:
            logger.warning("meeting_canvas_compile_failed: meeting=%s error=%s", meeting_id, exc)
            return {
                "meeting_id": meeting_id,
                "artifact": excal.format_artifact_read(artifact).model_dump(),
                "synced": False,
                "reason": f"compile_failed: {exc}"[:300],
                "ai_status": ai_status,
            }

        plan_dump = plan.model_dump(mode="json")
        plan_fingerprint = hashlib.sha256(
            json.dumps(plan_dump, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        # Post-render verification (warn-first, never blocking): diff the
        # compiled meeting scene against the meeting evidence.
        from app.services.note_verification_service import (
            VERIFICATION_VERSION,
            verify_scene,
        )
        from app.services.visual_sync_service import _is_agent_managed

        verification = verify_scene(
            compiled or [],
            [str(snippet.get("content") or "") for snippet in evidence_snippets],
        )
        verification["version"] = VERIFICATION_VERSION
        # Preserve user-drawn elements: without this, the next sync would
        # wipe edits the user saved through the editable canvas.
        user_scene = [
            element for element in (current_scene or [])
            if isinstance(element, dict) and not _is_agent_managed(element)
        ]
        merged_scene = list(compiled or []) + user_scene
        scene_fingerprint = hashlib.sha256(
            json.dumps(merged_scene, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        current_fingerprint = hashlib.sha256(
            json.dumps(current_scene or [], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        if scene_fingerprint == current_fingerprint:
            # Scene unchanged — but verification logic may have moved on.
            # Refresh a stale/missing verification block in place (no new
            # revision, no recompile) so reads always report current logic.
            from app.services.note_verification_service import (
                VERIFICATION_VERSION,
                verify_scene as _verify,
            )

            stored = ((excal.format_artifact_read(artifact).model_dump().get("app_state") or {}).get("meeting_canvas") or {})
            if stored.get("verification", {}).get("version") != VERIFICATION_VERSION:
                refreshed = _verify(
                    current_scene or [],
                    [str(snippet.get("content") or "") for snippet in evidence_snippets],
                )
                refreshed["version"] = VERIFICATION_VERSION
                try:
                    state_blob = json.loads(artifact.app_state_json or "{}")
                    state_blob.setdefault("meeting_canvas", {})["verification"] = refreshed
                    artifact.app_state_json = json.dumps(state_blob)
                    db.commit()
                except Exception as exc:
                    logger.warning("meeting_canvas_verification_refresh_failed: %s", exc)
                    db.rollback()
                return {
                    "meeting_id": meeting_id,
                    "artifact": excal.format_artifact_read(artifact).model_dump(),
                    "synced": True,
                    "reason": "verification_refreshed",
                    "ai_status": ai_status,
                    "plan_fingerprint": plan_fingerprint,
                    "verification": refreshed,
                }
            return {
                "meeting_id": meeting_id,
                "artifact": excal.format_artifact_read(artifact).model_dump(),
                "synced": False,
                "reason": "no_change",
                "ai_status": ai_status,
                "plan_fingerprint": plan_fingerprint,
            }

        revision = VisualRevisionService().commit_revision(
            project_id=canvas_key,
            scene=merged_scene,
            db=db,
            tenant_id=tenant_id,
            app_state={
                "theme": "light",
                "viewBackgroundColor": "#ffffff",
                "meeting_canvas": {
                    "meeting_id": meeting_id,
                    "ai_status": ai_status,
                    "plan_fingerprint": plan_fingerprint,
                    "evidence_ids": [e.id for e in evidence_records],
                    "transcript_entry_count": len(entries),
                    "discussion_snippet_count": len(evidence_snippets),
                    "context_scope": "complete_meeting_discussion",
                    "project_filtering": False,
                    "discussion_filter": discussion_filter,
                    "batches": batch_info.get("batches"),
                    "batches_ai": batch_info.get("batches_ai"),
                    "notes_language": "en",
                    "translation_pending_count": batch_info.get("translation_pending_count", 0),
                    "non_english_fields_withheld": withheld_fields,
                    "verification": verification,
                },
            },
            operations=[
                {
                    "op_type": "meeting_canvas_reconcile",
                    "target_element_id": "meeting_canvas",
                    "payload": {
                        "mode": "free_form_meeting_notes",
                        "representation": plan.canvas_strategy,
                        "diagram_created": bool(plan.nodes or plan.relationships or plan.visualizations),
                        "ai_status": ai_status,
                        "context_scope": "complete_meeting_discussion",
                        "project_filtering": False,
                    },
                    "source_evidence_ids": [e.id for e in evidence_records],
                }
            ],
            evidence_ids=[e.id for e in evidence_records],
            actor_id=actor_id,
            reason="Meeting discussion canvas synchronized from persisted evidence",
            workspace_name=f"Meeting Canvas · {meeting.title or meeting_id}",
        )
        artifact = excal.get_or_create_artifact(
            canvas_key,
            db,
            tenant_id=tenant_id,
            name=f"Meeting Notes · {meeting.title or meeting_id}",
        )
        return {
            "meeting_id": meeting_id,
            "artifact": excal.format_artifact_read(artifact).model_dump(),
            "synced": True,
            "revision_number": revision.revision_number,
            "ai_status": ai_status,
            "plan_fingerprint": plan_fingerprint,
            "evidence_count": len(evidence_records),
            "transcript_entry_count": len(entries),
            "discussion_snippet_count": len(evidence_snippets),
            "context_scope": "complete_meeting_discussion",
            "project_filtering": False,
            "discussion_filter": discussion_filter,
            "batches": batch_info.get("batches"),
            "batches_ai": batch_info.get("batches_ai"),
            "verification": verification,
        }

    @staticmethod
    def _json_list(raw: Optional[str]) -> List[Any]:
        try:
            value = json.loads(raw or "[]")
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def get_or_build(
        self,
        meeting_id: str,
        db: Session,
        candidates: Optional[Sequence[CandidateKnowledge]] = None,
        memory_results: Optional[Mapping[str, Mapping[str, Any]]] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            raise ValueError(f"Meeting '{meeting_id}' not found.")

        try:
            metadata = json.loads(meeting.metadata_json or "{}")
            cached = metadata.get("session_intelligence")
        except (TypeError, ValueError):
            cached = None

        if (
            cached
            and cached.get("version") == self.VERSION
            and not candidates
            and not memory_results
        ):
            return cached

        payload = self.build_session_intelligence(
            meeting_id=meeting_id,
            db=db,
            candidates=candidates,
            memory_results=memory_results,
        )
        if persist:
            return self.persist_session_intelligence(meeting_id, db, payload)
        return payload
