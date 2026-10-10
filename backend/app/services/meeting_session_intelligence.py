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

    # ------------------------------------------------------------------
    # Free-form Meeting Canvas
    # ------------------------------------------------------------------
    @staticmethod
    def _meeting_canvas_key(meeting_id: str) -> str:
        """Stable visual workspace key that is isolated from any project."""
        return f"meeting_canvas:{meeting_id}"

    def _build_canvas_plans(
        self,
        meeting: Meeting,
        state_summary: Dict[str, Any],
        current_nodes: List[str],
        evidence_snippets: List[Dict[str, Any]],
        focus_prompt: str,
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
                    f"{focus_prompt} This is PART {index + 1} of {len(batches)}: "
                    "record ONLY the evidence in this part. Do not repeat or "
                    "summarize other parts."
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
        current_nodes = []
        for element in current_scene[:120]:
            if not isinstance(element, dict):
                continue
            text_value = str(element.get("text") or "").strip()
            if text_value:
                current_nodes.append(text_value[:120])

        evidence_snippets = [
            {
                "id": evidence.id,
                "content": f"{evidence.actor_id or 'Speaker'}: {evidence.content}",
                "source": evidence.source,
            }
            for evidence in evidence_records
            if evidence.content and evidence.content.strip()
        ]

        state_summary = {
            "title": meeting.title or "Meeting Notes",
            "vision": "Free-form working notes for this meeting only.",
            "participants": participant_names,
            "meeting_id": meeting_id,
            "transcript_entry_count": len(entries),
            "requirements": [],
            "architecture": [],
            "decisions": [],
            "constraints": [],
            "assumptions": [],
            "open_questions": [],
        }
        focus = (
            "MEETING CANVAS MODE. Capture only the substance of this meeting. "
            "There are NO required sections, categories, note formats, or diagram types. "
            "Choose the most natural way to record the discussion. Keep notes grounded in the "
            "meeting evidence. Create a visualization only when it genuinely communicates the "
            "discussion better than words. Do not import project-wide status, Project State, "
            "or information from other meetings. The workspace outside this canvas handles project routing."
        )

        plan, ai_status, batch_info = self._build_canvas_plans(
            meeting=meeting,
            state_summary=state_summary,
            current_nodes=current_nodes,
            evidence_snippets=evidence_snippets,
            focus_prompt=focus,
        )

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
        from app.services.note_verification_service import verify_scene

        verification = verify_scene(
            compiled or [],
            [str(snippet.get("content") or "") for snippet in evidence_snippets],
        )
        scene_fingerprint = hashlib.sha256(
            json.dumps(compiled or [], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        current_fingerprint = hashlib.sha256(
            json.dumps(current_scene or [], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        if scene_fingerprint == current_fingerprint:
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
            scene=compiled,
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
                    "batches": batch_info.get("batches"),
                    "batches_ai": batch_info.get("batches_ai"),
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
