---
name: Synora Reset Retest
description: Reset Synora test data with fresh randomized fixtures, verify project and meeting deletes wipe DB, and re-run end-to-end pipeline
---

# Synora Reset Retest

A testing processor for Synora that is intentionally **not the same every time**.
Each run generates a fresh randomized project + 4-speaker transcript, verifies
hard-delete semantics, and re-runs the full pipeline.

Use this when the user says things like:
- "delete MediQueue all versions and test with new project again"
- "UI delete should wipe it from DB"
- "keep delete option for meetings"
- "reset and retest"

## Safety first (do not skip)

1. **Never delete system projects.** Refuse `proj_unknown_context`, `proj_default`,
   or any project with `is_system=true`.
2. **Default to dry-run.** List what *would* be deleted first. Only delete after
   the user confirms the exact project IDs/names.
3. **Treat MediQueue as a pattern, not a constant.** Match
   `name ILIKE '%medique%'` to find all versions, then confirm each one.
4. **Evidence traceability is the core invariant.** Never copy-paste transcript
   text into the UI to fake a test. Always ingest through the API so
   `SourceEvent -> Evidence -> CandidateKnowledge -> ProjectMemory -> Excalidraw`
   is preserved.

## Workflow

### 0. Inspect before changing

Read these first — do not assume README matches implementation:

- `backend/app/api/projects.py` → `delete_project` (already hard-deletes)
- `backend/app/api/meetings.py` → **no `DELETE /{meeting_id}` yet** (see references/api-contracts.md)
- `frontend/src/lib/api.ts` → `deleteProject` exists, `deleteMeeting` missing
- `frontend/src/app/page.tsx` → `handleDeleteProject` exists
- `frontend/src/components/layout/Shell.tsx` → project delete dialog (type DELETE)
- `frontend/src/components/views/MeetingsView.tsx` + `MeetingDetailView.tsx` → no meeting delete UI yet
- `backend/app/models/` → see references/db-tables.md for full wipe matrix

### 1. Delete MediQueue all versions (dry-run first)

```powershell
# list candidates
python scripts/reset_retest.py --list-mediqueue --db E:\webstack\trikaal\Synora\synora.db
# dry-run wipe check for one project
python scripts/reset_retest.py --verify-wipe proj_XXXX --db E:\webstack\trikaal\Synora\synora.db --dry-run
```

Only after user confirms IDs, call:

```text
DELETE /projects/{project_id}?workspace_id=ws_default
Header: X-User-ID: <same user that owns the project>
```

### 2. Verify UI project delete wipes DB

After clicking Delete in UI (type DELETE to confirm):

1. `GET /projects` must no longer list the ID.
2. Run the wipe matrix in `references/db-tables.md` — every table must return
   zero rows for that `project_id`:
   `evidence, candidate_knowledge, agent_runs, agent_executions, conflicts,
   context_resolutions, source_events, task_jobs, meet_event_records,
   meet_subscriptions, project_domain_profiles, meetings (+cascade
   participants/transcripts/entries), visual_workspaces (+cascade revisions),
   excalidraw_artifacts (+cascade proposals), project_states (+cascade
   versions/changes)`.
3. Known gaps to check explicitly (not covered by current `delete_project`):
   `visual_patches, project_semantic_profiles, context_feedbacks,
   unknown_clusters, audit_logs, whatsapp_batches`. Report leftovers as P0.
4. `UnknownContextItem.assigned_project_id` must be cleared to NULL/PENDING,
   not deleted.
5. Refresh UI — project selector, Atlas, State must not reference the ID.

### 3. Test with a new project again (randomized every run)

Never reuse the same name/script twice:

```powershell
python scripts/reset_retest.py --new-fixture --speakers 4 --utterances 18
```

This prints a fresh `project JSON + transcript JSON` with:
- random project name (hospital, campus, cafe, logistics domains rotate)
- random 4 speaker labels (`SPEAKER_00..03`, never real names)
- random timestamps spanning ~30 min
- mixed content: decisions, requirements, questions, chit-chat, one unknown-context line

Then:

```text
POST /projects
POST /meetings/ingest-transcript { project_id, title, provider: google_meet, entries, auto_process: true }
```

Verify: 1 meeting → N entries → N evidence → candidates with `evidence_ids_json`
non-empty → memory version bump → Excalidraw revision with new nodes.

### 4. Keep delete option for meetings

If `DELETE /meetings/{meeting_id}` is still missing:

1. Add it following the project-delete pattern: user-scoped, hard delete one
   meeting + cascade participants/transcripts/entries, null out
   `evidence.meeting_id/transcript_id/transcript_entry_id` (do NOT delete
   evidence — it is immutable ground truth), delete `meeting_canvas:*`
   artifacts.
2. Add `api.deleteMeeting` in `frontend/src/lib/api.ts`.
3. Add Delete button in `MeetingsView` row + `MeetingDetailView` header with
   type-to-confirm, wire through `page.tsx`, refresh list after delete.
4. Add backend test: create → delete → assert 404 on re-get + zero child rows.

See `references/api-contracts.md` for exact shapes.

## Randomized-every-run rules

- Seed with current time + random suffix. Log the seed so a run is reproducible
  *after the fact* but never identical beforehand.
- Rotate domains, speaker counts (default 4), utterance counts, languages
  (en + occasional Hindi/Hinglish line to exercise Sarvam path later).
- Always include: 1 casual line (must route to Unknown Context), 1 ambiguous
  line (must NOT be guessed), 1 duplicate-safe re-ingest check.
- Never hardcode `MediQueue`, `Smart Campus`, or `HospitalityOS` as the only
  fixtures.

## Failure classification

- P0 = data corruption / leftover rows after delete / wrong-project memory write
- P1 = incorrect routing / Unknown Context mis-assigned
- P2 = endpoint missing / UI button missing / pipeline failure
- P3 = UX (no confirm, no refresh)
- P4 = performance

## References

- Read `references/db-tables.md` for the wipe matrix.
- Read `references/api-contracts.md` for current endpoint truth.
- Run `scripts/reset_retest.py --help` for the fixture generator.
