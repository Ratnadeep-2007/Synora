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
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from sqlalchemy.orm import Session, joinedload

from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.models.meeting import Meeting, Transcript, TranscriptEntry
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID


DUE_HINT_PATTERN = re.compile(
    r"\b(?:by|before|due(?:\s+on)?|deadline(?:\s+is)?)\s+"
    r"([A-Za-z0-9][A-Za-z0-9 ,./:-]{1,48})",
    re.IGNORECASE,
)


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

    @staticmethod
    def _candidate_type(candidate: CandidateKnowledge) -> str:
        category = (candidate.category or "").strip().lower()
        classification = (candidate.classification or "").strip().lower()
        if category in {"decision_candidate", "decision"} or classification == "decision":
            return "decision"
        if category in {"requirement_candidate", "requirement"} or classification == "requirement":
            return "requirement"
        if category in {"question", "open_question"} or classification == "question":
            return "question"
        if category in {"action_item", "actionitem"} or classification in {"actionitem", "action_item"}:
            return "action_item"
        if category in {"constraint"} or classification == "constraint":
            return "constraint"
        if category in {"assumption"} or classification == "assumption":
            return "assumption"
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
                f"{entry.participant.display_name if entry.participant and entry.participant.display_name else 'Speaker'}: {entry.text}"
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
