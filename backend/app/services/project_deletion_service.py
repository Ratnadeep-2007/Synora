"""Atomic removal of project-owned data, including loose ownership columns."""

import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    AuditLog, CandidateKnowledge, ContextFeedback, Evidence, ExcalidrawArtifact,
    Meeting, MemoryIndex, MemoryTerm, PossibleProjectMatch, SourceArtifact,
    SourceEvent, Transcript, TranscriptEntry, UnknownCluster, UnknownContextItem,
    VisualOperation, VisualRevision, VisualWorkspace,
)
from app.models.project import Project, SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
from app.services.vexa_sarvam_service import get_capture_metadata
from app.services.visual_sync_service import _is_agent_managed
from app.services.workspace_atlas_service import WorkspaceAtlasService


class ProjectDeletionBusy(ValueError):
    pass


def _load(value, default):
    try:
        result = json.loads(value or "null")
        return result if isinstance(result, type(default)) else default
    except (TypeError, ValueError):
        return default


def _prune_project(value, project_id, removed_ids=frozenset()):
    """Remove structured project references from shared derived snapshots."""
    if isinstance(value, dict):
        if value.get("project_id") == project_id or value.get("candidate_project_id") == project_id or any(
            value.get(key) in removed_ids for key in ("item_id", "unknown_item_id", "evidence_id") if isinstance(value.get(key), str)
        ):
            return None
        custom = value.get("customData")
        if isinstance(custom, dict) and any(
            isinstance(meta, dict) and (
                meta.get("project_id") == project_id or any(
                    meta.get(key) in removed_ids for key in ("item_id", "unknown_item_id", "evidence_id") if isinstance(meta.get(key), str)
                )
            ) for meta in custom.values()
        ):
            return None
        return {key: cleaned for key, item in value.items()
                if key != project_id and item != project_id
                and (cleaned := _prune_project(item, project_id, removed_ids)) is not None}
    if isinstance(value, list):
        return [cleaned for item in value if item != project_id
                and not (isinstance(item, str) and item in removed_ids)
                and (cleaned := _prune_project(item, project_id, removed_ids)) is not None]
    return value


def purge_project_data(db: Session, project: Project) -> dict:
    """Use caller's transaction; never commits or calls external services.

    Shared meetings remain when another project uses them. Only transcript
    entries exclusively backed by the deleted project's evidence are removed.
    Their derived meeting canvas is invalidated so it cannot quote old text.
    """
    project_id = project.id
    evidence = db.query(Evidence).filter(Evidence.project_id == project_id).all()
    evidence_ids = [row.id for row in evidence]
    entry_ids = {row.transcript_entry_id for row in evidence if row.transcript_entry_id}
    owned_meetings = db.query(Meeting).filter(Meeting.project_id == project_id).all()
    affected_ids = {row.meeting_id for row in evidence if row.meeting_id} | {row.id for row in owned_meetings}
    affected = db.query(Meeting).filter(Meeting.id.in_(affected_ids)).all() if affected_ids else []
    active = {"starting", "joining", "waiting_for_recording", "recording_ready", "transcribing", "transcribing_sarvam", "transcribing_whisper", "ingesting", "stopping"}
    for meeting in affected:
        if get_capture_metadata(meeting).get("status") in active:
            raise ProjectDeletionBusy("Stop the related meeting capture and wait for processing to finish before deleting this project.")

    foreign_meetings = set()
    if affected_ids:
        for model in (Evidence, CandidateKnowledge):
            foreign_meetings.update(row[0] for row in db.query(model.meeting_id).filter(
                model.meeting_id.in_(affected_ids), model.project_id != project_id,
            ).distinct().all())
    delete_meeting_ids = {row.id for row in owned_meetings} - foreign_meetings
    shared_ids = affected_ids - delete_meeting_ids

    # Do not cascade another project's evidence through a shared source event.
    shared_events = db.query(Evidence.source_event_id).filter(Evidence.project_id != project_id)
    db.query(SourceEvent).filter(SourceEvent.project_id == project_id, SourceEvent.event_id.in_(shared_events)).update(
        {SourceEvent.project_id: SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID}, synchronize_session=False,
    )

    unknown_ids = [row[0] for row in db.query(UnknownContextItem.id).filter(or_(
        UnknownContextItem.project_id == project_id,
        UnknownContextItem.assigned_project_id == project_id,
        UnknownContextItem.evidence_id.in_(evidence_ids),
    )).all()]
    db.query(PossibleProjectMatch).filter(or_(
        PossibleProjectMatch.candidate_project_id == project_id,
        PossibleProjectMatch.unknown_item_id.in_(unknown_ids),
    )).delete(synchronize_session=False)
    db.query(UnknownContextItem).filter(UnknownContextItem.id.in_(unknown_ids)).delete(synchronize_session=False)
    db.query(ContextFeedback).filter(or_(
        ContextFeedback.selected_project_id == project_id,
        ContextFeedback.evidence_id.in_(evidence_ids),
    )).delete(synchronize_session=False)
    db.query(ContextFeedback).filter(ContextFeedback.original_predicted_project_id == project_id).update(
        {ContextFeedback.original_predicted_project_id: None}, synchronize_session=False,
    )
    db.query(UnknownCluster).filter(UnknownCluster.assigned_project_id == project_id).delete(synchronize_session=False)
    removed_unknown_ids = set(unknown_ids)
    for cluster in db.query(UnknownCluster).filter(UnknownCluster.workspace_id == project.workspace_id).all():
        if cluster.suggested_project_id == project_id:
            cluster.suggested_project_id = None
            cluster.suggested_project_name = None
        items = cluster.get_item_ids()
        remaining = [item for item in items if item not in removed_unknown_ids]
        if items and not remaining:
            db.delete(cluster)
        elif remaining != items:
            cluster.set_item_ids(remaining)
            cluster.centroid_vector_json = "[]"
            cluster.title = "Context awaiting review"
            cluster.summary = ""

    if entry_ids:
        foreign_entries = {row[0] for row in db.query(Evidence.transcript_entry_id).filter(
            Evidence.transcript_entry_id.in_(entry_ids), Evidence.project_id != project_id,
        ).all()}
        remove_entries = entry_ids - foreign_entries
        # Explicitly unlink first: also works with SQLite foreign keys disabled.
        db.query(Evidence).filter(Evidence.project_id == project_id).update(
            {Evidence.transcript_entry_id: None}, synchronize_session=False,
        )
        db.query(TranscriptEntry).filter(TranscriptEntry.id.in_(remove_entries)).delete(synchronize_session=False)

    for meeting in affected:
        if meeting.id not in shared_ids:
            continue
        if meeting.project_id == project_id:
            meeting.project_id = SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID
        metadata = _load(meeting.metadata_json, {})
        metadata.pop("session_intelligence", None)
        meeting.metadata_json = json.dumps(_prune_project(metadata, project_id), ensure_ascii=False)

    # Meeting canvases use synthetic ownership IDs rather than real project IDs.
    # Invalidate these derived views for every touched meeting; surviving
    # meeting transcripts can generate a fresh view without deleted entries.
    scopes = [project_id] + [f"meeting_canvas:{mid}" for mid in delete_meeting_ids]
    shared_canvas_keys = [f"meeting_canvas:{mid}" for mid in shared_ids]
    for artifact in db.query(ExcalidrawArtifact).filter(ExcalidrawArtifact.project_id.in_(shared_canvas_keys)).all():
        scene = _load(artifact.elements_json, [])
        artifact.elements_json = json.dumps([element for element in scene if isinstance(element, dict) and not _is_agent_managed(element)], ensure_ascii=False)
        artifact.app_state_json = "{}"
        artifact.extracted_nodes_json = "[]"
        artifact.version += 1
    for revision in db.query(VisualRevision).filter(VisualRevision.project_id.in_(shared_canvas_keys)).all():
        scene = _load(revision.scene_json, [])
        revision.scene_json = json.dumps([element for element in scene if isinstance(element, dict) and not _is_agent_managed(element)], ensure_ascii=False)
        revision.app_state_json = "{}"
        revision.operations_json = "[]"
        revision.evidence_ids_json = "[]"
    shared_revisions = db.query(VisualRevision.id).filter(VisualRevision.project_id.in_(shared_canvas_keys))
    db.query(VisualOperation).filter(VisualOperation.revision_id.in_(shared_revisions)).delete(synchronize_session=False)
    indexes = db.query(MemoryIndex.id).filter(MemoryIndex.project_id.in_(scopes))
    db.query(MemoryTerm).filter(MemoryTerm.record_id.in_(indexes)).delete(synchronize_session=False)
    revision_ids = db.query(VisualRevision.id).filter(VisualRevision.project_id.in_(scopes))
    db.query(VisualOperation).filter(VisualOperation.revision_id.in_(revision_ids)).delete(synchronize_session=False)
    db.query(SourceArtifact).filter(SourceArtifact.evidence_id.in_(evidence_ids)).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.resource_id == project_id).delete(synchronize_session=False)
    db.flush()

    # All registered project-owned tables participate, including new memory,
    # profile, patch and job tables. Dependents are removed before parents.
    counts = {}
    excluded = {"meetings", "unknown_context_items"}
    for table in reversed(Base.metadata.sorted_tables):
        if "project_id" not in table.c or table.name in excluded:
            continue
        result = db.execute(table.delete().where(table.c.project_id.in_(scopes)))
        counts[table.name] = result.rowcount

    # Bulk SQL above intentionally avoids memory outbox hooks which would
    # enqueue new indexing work for records being permanently erased.
    for meeting in owned_meetings:
        if meeting.id in delete_meeting_ids:
            db.delete(meeting)

    # Scrub the deleted column from current AND historical shared atlas
    # snapshots, so undo/reload cannot resurrect the project visually.
    removed_refs = set(evidence_ids) | removed_unknown_ids
    shared_boards = ["proj_workspace_atlas", SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID]
    for artifact in db.query(ExcalidrawArtifact).filter(ExcalidrawArtifact.project_id.in_(shared_boards)).all():
        frame_id = WorkspaceAtlasService._id(project_id, "frame")
        scene = [element for element in _load(artifact.elements_json, []) if element.get("id") != frame_id]
        artifact.elements_json = json.dumps(_prune_project(scene, project_id, removed_refs), ensure_ascii=False)
        artifact.app_state_json = json.dumps(_prune_project(_load(artifact.app_state_json, {}), project_id, removed_refs), ensure_ascii=False)
        artifact.extracted_nodes_json = "[]"
        artifact.version += 1
    for revision in db.query(VisualRevision).filter(VisualRevision.project_id.in_(shared_boards)).all():
        for field, default in (("scene_json", []), ("app_state_json", {}), ("operations_json", [])):
            setattr(revision, field, json.dumps(_prune_project(_load(getattr(revision, field), default), project_id, removed_refs), ensure_ascii=False))
        revision.scene_json = json.dumps([element for element in _load(revision.scene_json, []) if element.get("id") != WorkspaceAtlasService._id(project_id, "frame")], ensure_ascii=False)
        revision.evidence_ids_json = json.dumps([item for item in _load(revision.evidence_ids_json, []) if item not in removed_refs])
    board_revisions = db.query(VisualRevision.id).filter(VisualRevision.project_id.in_(shared_boards))
    for operation in db.query(VisualOperation).filter(VisualOperation.revision_id.in_(board_revisions)).all():
        operation.payload_json = json.dumps(_prune_project(_load(operation.payload_json, {}), project_id, removed_refs), ensure_ascii=False)
        operation.source_evidence_ids_json = json.dumps([item for item in _load(operation.source_evidence_ids_json, []) if item not in removed_refs])

    db.flush()
    db.delete(project)
    db.flush()
    return {"deleted_records": counts, "deleted_meetings": len(delete_meeting_ids), "preserved_shared_meetings": len(shared_ids)}
