# Synora API contracts for reset-retest (2026-10-10)

## Project delete — EXISTS

```text
DELETE /projects/{project_id}?workspace_id=ws_default
Header: X-User-ID: <owner>
200: { success, project_id, project_name, message }
400: reserved system project (proj_unknown_context)
404: Project not found (wrong id, wrong workspace, or system project)
500: deletion failed (rolled back)
```

Frontend: `api.deleteProject(projectId)` in `frontend/src/lib/api.ts:506`,
`handleDeleteProject` in `frontend/src/app/page.tsx:340`, type-DELETE dialog
in `frontend/src/components/layout/Shell.tsx:179`.

## Meeting delete — MISSING (implement per skill)

No `DELETE /meetings/{meeting_id}` in `backend/app/api/meetings.py` as of
2026-10-10. Existing meeting routes: `POST /sync`, `GET /`,
`GET /{id}/intelligence`, `GET /{id}/canvas`, `GET /{id}`,
`GET /{id}/transcript`, `POST /ingest-transcript`, `POST /{id}/route-evidence`.

No `deleteMeeting` in `frontend/src/lib/api.ts`. No delete UI in
`MeetingsView.tsx` or `MeetingDetailView.tsx`.

Required shape when implemented:

```text
DELETE /meetings/{meeting_id}
Header: X-User-ID: <owner>
200: { success, meeting_id, message }
404: Meeting not found for user
```

Frontend required:

```ts
deleteMeeting: (meetingId: string) => request(`/meetings/${meetingId}`, { method: "DELETE" })
```

## Ingest (for fresh fixtures)

```text
POST /projects { name, description, workspace_id } -> { id, ... }
POST /meetings/ingest-transcript
  { project_id, title, provider: "google_meet", entries: [{speaker, text, start_time?, end_time?}], auto_process: true }
  -> { success, meeting_id, entries_count, pipeline_result }
```

Auth everywhere: `X-User-ID` header or `user_id` query. Missing identity → 401.
