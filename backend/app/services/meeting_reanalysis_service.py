"""Retry derived meeting intelligence from saved source entries, without STT."""

import asyncio
import json
import re
from collections import Counter
from datetime import datetime, timezone

from app.models.context_resolution import UnknownContextItem
from app.models.evidence import Evidence
from app.models.meeting import Meeting, Transcript, TranscriptEntry
from app.models.project import Project, SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.models.source_event import SourceEvent
from app.services.translation_service import english_note_text, needs_translation, translate_segments


def _metadata(raw):
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _retract_displaced_claims(meeting_id, displaced, db, actor_id):
    """Retract derived claims after automatic routing changes, preserving history."""
    from app.models.intelligence import CandidateKnowledge
    from app.models.project_state import ProjectState, ProjectStateVersion, StateChange
    from app.models.memory_engine import MemoryClaimRevision
    from app.services.project_state_service import ProjectStateService

    now = datetime.now(timezone.utc)
    for project_id, evidence_ids in displaced.items():
        candidates = db.query(CandidateKnowledge).filter(
            CandidateKnowledge.meeting_id == meeting_id, CandidateKnowledge.project_id == project_id,
        ).all()
        invalid = set()
        for candidate in candidates:
            references = set(json.loads(candidate.evidence_ids_json or "[]"))
            if references & evidence_ids:
                candidate.status = "superseded"
                invalid.add(candidate.id)
        if not invalid:
            continue
        for change in db.query(StateChange).filter(StateChange.candidate_id.in_(invalid), StateChange.approval_status == "proposed").all():
            change.approval_status = "superseded"
            change.resolved_at = now
        for claim in db.query(MemoryClaimRevision).filter(MemoryClaimRevision.candidate_id.in_(invalid), MemoryClaimRevision.valid_to.is_(None)).all():
            claim.valid_to = now
        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).with_for_update().first()
        changed = False
        if state:
            for section in ("requirements", "architecture", "decisions", "constraints", "assumptions", "open_questions"):
                field = section + "_json"
                rows = json.loads(getattr(state, field) or "[]")
                kept = [row for row in rows if not isinstance(row, dict) or (
                    row.get("source_candidate_id") not in invalid and not (set(row.get("evidence_ids") or []) & evidence_ids)
                )]
                if len(kept) != len(rows):
                    setattr(state, field, json.dumps(kept))
                    changed = True
        if changed:
            previous = state.current_version
            state.current_version += 1
            state.updated_at = now
            reason = "Retracted claims whose evidence was automatically rerouted during saved-meeting analysis."
            db.add(ProjectStateVersion(project_id=project_id, version_number=state.current_version,
                snapshot_json=json.dumps(ProjectStateService()._dump_state_dict(state)), reason=reason,
                change_summary_json=json.dumps({"action": "routing_retraction", "candidate_ids": sorted(invalid)}), actor_id=actor_id))
            db.add(StateChange(project_id=project_id, state_version_before=previous, state_version_after=state.current_version,
                operation="supersede", target_section="routing_retraction", value_json=json.dumps({"candidate_ids": sorted(invalid)}),
                reason=reason, actor_id=actor_id, evidence_ids_json=json.dumps(sorted(evidence_ids)), approval_status="approved", resolved_at=now))
    db.commit()


def reanalyze_saved_meeting(meeting_id, db, actor_id="meeting_reanalysis"):
    from app.services.pipeline_coordinator import PipelineCoordinator
    from app.services.vexa_sarvam_service import VexaSarvamService, _set_capture_metadata

    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        raise ValueError("Meeting not found.")
    entries = db.query(TranscriptEntry).join(Transcript, TranscriptEntry.transcript_id == Transcript.id).filter(
        Transcript.meeting_id == meeting_id,
    ).order_by(TranscriptEntry.start_time.asc(), TranscriptEntry.created_at.asc()).all()
    if not entries:
        raise ValueError("This meeting has no saved transcript to analyze.")
    source_language = Counter(entry.language_code or "unknown" for entry in entries).most_common(1)[0][0]
    segments = [{"id": entry.id, "text": entry.text, "speaker": str((_metadata(entry.metadata_json)).get("speaker_id") or "Unknown Speaker"),
                 "start_seconds": index * 1.0, "end_seconds": index * 1.0 + 1.0} for index, entry in enumerate(entries)]
    # Use actual timestamps when present; these boundaries affect grouping,
    # never mutate original timestamps or transcript text.
    first_time = entries[0].start_time
    if first_time:
        for entry, segment in zip(entries, segments):
            if entry.start_time:
                segment["start_seconds"] = max(0.0, (entry.start_time - first_time).total_seconds())
                segment["end_seconds"] = max(segment["start_seconds"], ((entry.end_time or entry.start_time) - first_time).total_seconds())

    details = {}
    translations, status, source = translate_segments(segments, source_language, translation_metadata=details)
    accepted_ids = set(details.get("successful_ids", []))
    evidence_rows = db.query(Evidence).filter(Evidence.meeting_id == meeting_id).all()
    by_entry = {}
    for evidence in evidence_rows:
        by_entry.setdefault(evidence.transcript_entry_id, []).append(evidence)
    english = {}
    for index, entry in enumerate(entries):
        meta = _metadata(entry.metadata_json)
        required = needs_translation(entry.text, source_language)
        translated = translations.get(entry.id)
        if index in accepted_ids and translated:
            meta["text_en"] = translated
        meta.update(translation_required=required, translation_status=status, translation_source=source,
                    translation_provider=details.get("provider"), notes_language="en")
        entry.metadata_json = json.dumps(meta, ensure_ascii=False)
        english[entry.id] = english_note_text(entry.text, entry.metadata_json, entry.language_code)
        for evidence in by_entry.get(entry.id, []):
            evidence_meta = _metadata(evidence.metadata_json)
            evidence_meta.update({key: meta.get(key) for key in ("text_en", "translation_required", "translation_status", "translation_source", "translation_provider", "notes_language")})
            # Only derived translation metadata changes. content stays exact.
            evidence.metadata_json = json.dumps(evidence_meta, ensure_ascii=False)
    pending = sum(not english.get(entry.id) for entry in entries if entry.text.strip())
    _set_capture_metadata(meeting, {"status": "ingesting", "analysis_step": "routing", "translation_status": status,
        "translation_source": source, "translation_provider": details.get("provider"),
        "translation_pending_count": pending, "notes_language": "en"})
    db.commit()
    if pending == len(entries):
        raise ValueError("English translation is unavailable. Source transcript preserved; configure an available translation provider and retry analysis.")

    projects = db.query(Project).filter(Project.workspace_id == meeting.workspace_id, Project.is_system.is_(False)).all()
    service = VexaSarvamService()
    routed = 0
    displaced = {}
    for evidence in evidence_rows:
        excluded = service._explicit_project_exclusions(english.get(evidence.transcript_entry_id) or "", projects)
        if evidence.project_id not in excluded:
            continue
        automatic_item = db.query(UnknownContextItem).filter(
            UnknownContextItem.evidence_id == evidence.id,
            UnknownContextItem.status == "assigned",
            UnknownContextItem.assigned_by == "synora_reanalysis",
        ).first()
        if automatic_item:
            # Correct this service's own derived assignment; human-reviewed
            # routing remains untouched.
            displaced.setdefault(evidence.project_id, set()).add(evidence.id)
            evidence.project_id = SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
            event = db.get(SourceEvent, evidence.source_event_id)
            if event:
                event.project_id = SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
            automatic_item.status = "pending"
            automatic_item.assigned_project_id = None
            automatic_item.assigned_by = None
            automatic_item.assigned_at = None
    db.commit()
    routing_segments = [{**segment, "text": english.get(segment["id"]) or ""} for segment in segments]
    groups = []
    anchors = [re.sub(r"[^a-z0-9]+", " ", project.name.lower()).strip() for project in projects]
    for original_group in service._routing_groups(routing_segments):
        current = []
        for index in original_group:
            normalized = re.sub(r"[^a-z0-9]+", " ", routing_segments[index]["text"].lower()).strip()
            boundary = normalized.startswith(("now switching", "this is not about", "this is not ")) or any(
                normalized.startswith(anchor) or normalized.startswith("for " + anchor) for anchor in anchors if anchor
            )
            if current and boundary:
                groups.append(current)
                current = []
            current.append(index)
        if current:
            groups.append(current)
    for group in groups:
        group_text = " ".join(english.get(entries[index].id) or "" for index in group).strip()
        if not group_text:
            continue
        target = service._resolve_project(group_text, segments[group[0]]["speaker"], meeting, db, projects)
        for index in group:
            entry = entries[index]
            if not english.get(entry.id):
                continue
            for evidence in by_entry.get(entry.id, []):
                if evidence.project_id == target:
                    continue
                automatic_item = db.query(UnknownContextItem).filter(
                    UnknownContextItem.evidence_id == evidence.id, UnknownContextItem.status == "assigned",
                    UnknownContextItem.assigned_by == "synora_reanalysis",
                ).first()
                # Re-evaluate our own automatic assignments; preserve human
                # review and assignments made outside this repair service.
                if evidence.project_id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID and automatic_item is None:
                    continue
                if evidence.project_id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID:
                    displaced.setdefault(evidence.project_id, set()).add(evidence.id)
                evidence.project_id = target
                event = db.get(SourceEvent, evidence.source_event_id)
                if event:
                    event.project_id = target
                items = db.query(UnknownContextItem).filter(UnknownContextItem.evidence_id == evidence.id).all()
                for item in items:
                    if target == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID and item is automatic_item:
                        item.status, item.assigned_project_id, item.assigned_by, item.assigned_at = "pending", None, None, None
                    elif target != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID and (item.status == "pending" or item is automatic_item):
                        item.status = "assigned"
                        item.assigned_project_id = target
                        item.assigned_by = "synora_reanalysis"
                        item.assigned_at = datetime.now(timezone.utc)
                routed += 1
        db.commit()

    _retract_displaced_claims(meeting_id, displaced, db, actor_id)

    resolved = sorted({row.project_id for row in evidence_rows if row.project_id != SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID})
    meeting.project_id = resolved[0] if len(resolved) == 1 else SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
    metadata = _metadata(meeting.metadata_json)
    metadata.pop("session_intelligence", None)
    meeting.metadata_json = json.dumps(metadata, ensure_ascii=False)
    _set_capture_metadata(meeting, {"analysis_step": "notes_and_canvas", "resolved_projects": resolved, "reanalyzed_routed_count": routed})
    db.commit()
    result = PipelineCoordinator().process_meeting_with_context(
        meeting_id=meeting_id, project_id=meeting.project_id, db=db, actor_id=actor_id,
        workspace_id=meeting.workspace_id, tenant_id="default_tenant", correlation_id=f"reanalyze:{meeting_id}",
    )
    if not getattr(result, "success", False):
        raise RuntimeError("Meeting analysis did not complete successfully. Original transcript preserved.")
    # Coordinator owns proposals, approval policy and all canvas compilation.
    # A successful pass is not a claim that every proposal was approved.
    db.refresh(meeting)
    _set_capture_metadata(meeting, {"status": "completed", "processed": True, "pipeline_processed": True,
        "analysis_step": "completed", "analysis_completed_at": datetime.now(timezone.utc).isoformat(), "error": None,
        "entries_count": len(entries), "resolved_projects": resolved})
    db.commit()
    return {"meeting_id": meeting_id, "translation_status": status, "translation_provider": details.get("provider"),
            "pending_translations": pending, "routed": routed, "entries_count": len(entries),
            "pipeline_success": bool(getattr(result, "success", False))}


async def reanalyze_saved_meeting_background(meeting_id, actor_id):
    from app.core.database import SessionLocal
    from app.services.vexa_sarvam_service import _PROCESSING_MEETINGS, _set_capture_metadata

    def work():
        with SessionLocal() as db:
            try:
                reanalyze_saved_meeting(meeting_id, db, actor_id)
            except Exception as exc:
                db.rollback()
                meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
                if meeting:
                    _set_capture_metadata(meeting, {"status": "failed", "analysis_step": "failed", "error": str(exc)[:600], "processed": False})
                    db.commit()
                raise
    try:
        await asyncio.to_thread(work)
    finally:
        _PROCESSING_MEETINGS.discard(meeting_id)
