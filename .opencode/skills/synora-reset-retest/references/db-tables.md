# Synora DB wipe matrix

Source of truth as of 2026-10-10, derived from `backend/app/models/` and
`backend/app/api/projects.py::delete_project`.

## Project delete (`DELETE /projects/{id}`) — what it covers

Covered today:

- `evidence` by `project_id`
- `candidate_knowledge` by `project_id`
- `agent_runs` by `project_id`
- `agent_executions` (`agent_workforce.py`) by `project_id`
- `conflicts` by `project_id`
- `context_resolutions` by `project_id`
- `source_events` by `project_id`
- `task_jobs` by `project_id`
- `meet_event_records` by `project_id`
- `meet_subscriptions` by `project_id`
- `project_domain_profiles` by `project_id`
- `meetings` by `project_id` via ORM delete (cascades `participants` →
  `transcripts` → `transcript_entries`)
- `visual_workspaces` by `project_id` via ORM delete (cascades
  `visual_revisions` → `visual_operations`)
- `excalidraw_artifacts` by `project_id` via ORM delete (cascades
  `excalidraw_proposals` via `artifact.proposals`)
- `project_states` single row via ORM delete (cascades
  `project_state_versions` + `state_changes`)
- `projects` row itself
- `project_agents.project_agent` via `Project.project_agent` cascade
- `PossibleProjectMatch` rows pointing at project: deleted
- `UnknownContextItem.assigned_project_id`: cleared to NULL + PENDING (not deleted)

## Known gaps — must verify explicitly after every delete

These tables carry `project_id` but are NOT deleted by current code:

- `visual_patches` (`visual_patch.py:25`, loose `project_id`, no FK cascade)
- `project_semantic_profiles` (`project_semantic_profile.py:25`, unique `project_id`)
- `context_feedbacks` (`context_feedback.py:34`, `selected_project_id`)
- `unknown_clusters` (`unknown_cluster.py:30,37`, suggested/assigned project)
- `audit_logs` (check model for project scoping)
- `whatsapp_batches` / `whatsapp_batch_items` (check project linkage)
- `meetings` owned by other projects but referencing deleted evidence: `evidence.meeting_id`
  uses `SET NULL` — verify no dangling FK errors.

Verification query pattern (SQLite):

```sql
SELECT 'evidence', COUNT(*) FROM evidence WHERE project_id='proj_XXX'
UNION ALL SELECT 'candidate_knowledge', COUNT(*) FROM candidate_knowledge WHERE project_id='proj_XXX'
UNION ALL SELECT 'source_events', COUNT(*) FROM source_events WHERE project_id='proj_XXX'
UNION ALL SELECT 'meetings', COUNT(*) FROM meetings WHERE project_id='proj_XXX'
UNION ALL SELECT 'visual_workspaces', COUNT(*) FROM visual_workspaces WHERE project_id='proj_XXX'
UNION ALL SELECT 'visual_patches', COUNT(*) FROM visual_patches WHERE project_id='proj_XXX'
UNION ALL SELECT 'project_states', COUNT(*) FROM project_states WHERE project_id='proj_XXX'
UNION ALL SELECT 'project_semantic_profiles', COUNT(*) FROM project_semantic_profiles WHERE project_id='proj_XXX'
UNION ALL SELECT 'excalidraw_artifacts', COUNT(*) FROM excalidraw_artifacts WHERE project_id='proj_XXX';
-- every count must be 0 after UI delete
```

## Meeting delete (to be implemented)

Target semantics:

- Scope: `Meeting.id + Meeting.user_id` (never delete another user's meeting).
- Delete: `transcript_entries` → `transcripts` → `participants` → `meetings`
  (ORM cascades already cover participants/transcripts/entries).
- Null out (do NOT delete — immutable): `evidence.meeting_id`,
  `evidence.transcript_id`, `evidence.transcript_entry_id`.
- Delete: `meeting_canvas:{meeting_id}` excalidraw artifacts.
- Keep: `source_events`, `evidence`, `candidate_knowledge` (provenance must survive).
- Return 404 on re-get.
