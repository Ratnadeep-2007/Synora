# Synesis — Event-Driven Google Meet Transcript Pipeline

**Status:** Canonical production architecture
**Scope:** Google Meet native transcription ingestion only

---

## 1. Canonical architecture

```text
Google Meet
→ native transcription
→ Google Workspace Events API (notification only)
→ Pub/Sub (delivery only)
→ Synesis event worker
→ Google Meet REST API (transcript + entries + participants)
→ PostgreSQL persistence (Meeting, Transcript, TranscriptEntry)
→ SourceEvent (transcript_ready + transcript entries)
→ Evidence
→ Shared Context Intelligence
→ Candidate Knowledge
→ Project Memory (automatic, project-bounded)
→ Meet Session Intelligence (speakers, timestamps, windows, actions)
→ Excalidraw Project Atlas (visual projection)
```

Rules:

- Workspace Events API is **notification infrastructure**. It never carries
  transcript content.
- Meet REST API retrieves the actual transcript resources.
- Pub/Sub is the **notification delivery layer**.
- Synesis persists transcripts internally. Google retains transcript entries
  for ~30 days after the conference ends, so persistence is mandatory.
- Manual sync is a **reconciliation/recovery mechanism**, not primary ingestion.
- Native Meet transcription is required.
- No Vexa. No meeting bot. No browser automation. No raw audio capture.
- No custom Google Meet speech-to-text.

## 2. OAuth scopes

Meet REST transcript retrieval uses exactly:

```text
https://www.googleapis.com/auth/meetings.space.readonly
```

plus `openid`, `userinfo.email`, `userinfo.profile`.

Never request:

- `https://www.googleapis.com/auth/meetings.conference.readonly` (obsolete)
- Drive scopes (only if transcript file download is explicitly implemented)
- `meetings.space.settings`

`Settings.GOOGLE_OAUTH_SCOPES` is validated at startup: obsolete or Drive
scopes raise `ValueError` immediately.

## 3. Workspace Events subscriptions

Event type:

```text
google.workspace.meet.transcript.v2.fileGenerated
```

Supported target-resource model:

1. `spaces/...` meeting-space subscriptions (per-space monitoring).
2. `users/...` user-target subscriptions (authorized Meet monitoring model).

Subscriptions are stored in PostgreSQL (`meet_subscriptions`):

```text
workspace_id, project_id, user_id, provider, target_resource,
subscription_name, event_types, pubsub_topic, status,
created_at, expires_at, renewed_at, last_event_at, last_error
```

Endpoints (`/meet/subscriptions`):

- `POST /meet/subscriptions` — create (idempotent per user+target; suspended
  subscriptions are reactivated, failed/expired raise a duplicate error
  directing the caller to renew)
- `GET /meet/subscriptions` — list (filter by project/status)
- `GET /meet/subscriptions/expiring` — expiring + expired
- `POST /meet/subscriptions/refresh-expirations` — scan and mark
- `POST /meet/subscriptions/{id}/renew` — renew for 7 more days
- `POST /meet/subscriptions/{id}/suspend` — suspend

Subscriptions expire after 7 days; the scanner marks `expiring` within 2 days
of expiry. Never create duplicate subscriptions per user+target (DB unique
constraint `uq_meet_sub_user_target`).

## 4. Pub/Sub ingestion boundary

Push endpoint: `POST /pubsub/meet-events`

- Verifies the `Authorization: Bearer <PUBSUB_VERIFICATION_TOKEN>` header.
- Parses the Pub/Sub push envelope (base64 `message.data`).
- Extracts `conferenceRecords/...` and `.../transcripts/...` references.
- Records the notification durably in `meet_event_records` keyed by the
  stable provider event id (`uq_meet_event_provider_id`).
- Returns `acknowledged=true` for duplicates and unsupported event types
  (safe to ack), `acknowledged=false` after recording (worker processes next).
- Never runs AI processing inside the handler.
- Malformed envelopes and failed verification raise 400 (do NOT ack).

Redelivery is expected: the worker treats `processed` records as duplicates.

## 5. Event normalization

Each notification becomes a Synesis source event:

```json
{
  "workspace_id": "...",
  "project_id": "...",
  "source": "google_meet",
  "source_event_id": "meet-event:<provider_event_id>",
  "event_type": "transcript_ready",
  "actor_id": "google_workspace_events",
  "occurred_at": "...",
  "content": null,
  "source_reference": {
    "conference_record_id": "...",
    "transcript_resource": "..."
  },
  "metadata": {}
}
```

Provider structures never reach the intelligence layer. Transcript utterances
become `transcript_entry` source events through the existing ingestion path.

## 6. Idempotency

Stable identifiers + DB uniqueness constraints:

- `uq_meet_event_provider_id` — one row per provider event
- `uq_source_event_proj_source_id` — one source event per notification
- `uq_meeting_provider_conf_id` — one meeting per conference record
- `uq_transcript_provider_trsc_id` — one transcript per transcript resource
- `uq_entry_transcript_provider_entry_id` — one row per transcript entry
- Evidence creation deduplicates on `(project_id, source_event_id)`

Redelivery never duplicates meetings, transcripts, entries, evidence,
knowledge, or state changes.

## 7. Meet REST retrieval

Per `transcript_ready` event (`MeetEventWorker.process_event_record`):

1. Resolve the active Google connection for the bound user.
2. `GET /v2/{transcript}` — transcript metadata; `ENDED`/`AVAILABLE`/
   `FILE_MUTATED` proceed, anything else becomes `awaiting_transcript`.
3. `GET /v2/{conferenceRecord}` — conference metadata (best effort).
4. `GET /v2/{conferenceRecord}/participants` — paginated; failures degrade
   to unlinked speakers, never fail the pipeline.
5. `GET /v2/{transcript}/entries` — paginated transcript entries ordered by
   start time (`meetings.space.readonly`).
6. Upsert Meeting → Transcript → Participants → TranscriptEntries.
7. Emit the `transcript_ready` source event.

`401` triggers one token refresh + retry; `403` surfaces
`insufficient_permissions`; `429` honors `Retry-After` with bounded backoff;
`5xx`/network errors become `pending_retry`; missing resources become
`awaiting_transcript` (transcript still generating).

## 8. Project mapping

Resolution order:

1. Subscription's `project_id` (explicit operator mapping).
2. Existing meeting row for the same conference + user (stable ownership).
3. Otherwise `proj_unassigned` — controlled "unassigned / requires project
   mapping" state. Never guesses.

`GET /meet/unassigned` lists them; `POST /meet/unassigned/{id}/assign`
maps one to a real project. Evidence created under `proj_unassigned`
moves with the meeting on assignment (project_id carried on new records).

## 9. Evidence → Shared Intelligence → Project Memory → Meet Session Intelligence → Excalidraw

```text
TranscriptEntry → SourceEvent → Evidence → Intelligence →
Candidate Knowledge → Validation → Proposal/State Change →
Project State → Excalidraw
```

- Every decision/requirement/proposal/conflict references evidence ids.
- The same project-scoped Synora Agent and Context Intelligence used by
  WhatsApp process Meet Evidence. Meet does not create a specialist agent
  or a separate memory store.
- `ProjectMemoryService` automatically promotes routine evidence-backed
  requirements, confirmed decisions, architecture updates, questions,
  assumptions, and supported knowledge into the resolved project's memory.
  Project boundaries are enforced deterministically; unknown/ambiguous
  routing goes to Unknown Context instead of guessing.
- `MeetingSessionIntelligenceService` adds only Meet-specific session structure
  over those shared records: ordered speakers, timestamps, topic labels derived
  from extracted knowledge, action-item owner/due hints, key
  decision/requirement/question lists, routing/timeline windows, and per-project
  memory version deltas. It is persisted inside the existing
  `Meeting.metadata_json` projection, not a second memory database.
- Meet uses **one completed-meeting synchronization phase** to retrieve and persist
  the transcript, conference metadata, participants, and transcript entries. After
  persistence, session intelligence and project-memory processing read Synora's DB
  only; they perform **zero additional Google API calls**.
- Excalidraw updates use structured visual operations (architecture
  diagrams, flows, dependency graphs, decision/requirement cards, small
  evidence labels). No transcript dumps, no raw LLM output injection.
- `process_meeting_with_context` rebuilds the visual workspace only after
  shared memory processing and Meet session intelligence; visualization
  failures defer with a warning, never fail the core evidence pipeline.

## 10. Meeting Session Intelligence

After a completed transcript is persisted, Meet receives a source-specific session
projection on top of the common Synora pipeline:

```text
Meeting ends
   ↓
One synchronization phase
   ├─ transcript metadata
   ├─ conference metadata
   ├─ participants
   └─ complete transcript entries (paged by Google as required)
   ↓
Persist complete transcript + Evidence
   ↓
Project routing
   └─ bounded 45s / 12-entry windows only when multi-project routing is needed
   ↓
Shared intelligence per resolved project
   └─ full persisted transcript/evidence for that project
   ↓
Shared Project Memory
   ↓
Meeting.metadata_json.session_intelligence
```

The 45-second/bounded windows are **not separate intelligence passes**. They are a
routing/timeline aid. A long meeting remains a single intelligence context per
resolved project, preserving relationships across window boundaries.

After the transcript and evidence are persisted, no Meet REST call is required for
intelligence. This is recorded in the meeting session projection as
`google_api_calls_after_persistence: 0`.

Available through `GET /meetings/{meeting_id}/intelligence` and included in
`MeetingDetailRead`. The projection is read-only from the user's perspective;
editing project truth still occurs through the shared project-memory/governance
mechanisms.

### 11. Reconciliation

`POST /meet/reconcile` (and the legacy `POST /meetings/sync`, now labeled
reconciliation):

1. Processes recorded-but-unprocessed event records first.
2. Optionally runs bounded REST discovery (`max_conferences`) into an
   explicitly scoped project.
3. Never blindly rescans everything on every click.

## 11. Error states

| Condition | Behavior |
|---|---|
| No Google connection | 404/401 `connection_not_found` with re-auth hint |
| Expired token | Refresh once, retry; else 401 `credentials_expired` |
| Revoked token | Status → revoked, 401 with re-auth hint |
| Insufficient permission | 403 `insufficient_permissions`, never "no meetings found" |
| No transcript yet | 202 `transcript_pending` / `awaiting_transcript` |
| Transcript ready | `meet_transcript_ready` → fetch → persist |
| Retrieval failure | 502 `retrieval_failure`, event → `failed` |
| Participant lookup failure | Degraded: entries persist without speaker links |
| Pub/Sub delivery failure | 400, do not ack; redelivery replays safely |
| Duplicate event | Ack immediately, no duplicate writes |
| Subscription expired | `expired` status, surfaced in expiring list |
| Renewal failure | `failed` status with `last_error` |
| Rate limit | Bounded backoff, `pending_retry` |
| API outage | `pending_retry` → `failed` after retries → DLQ semantics |

## 12. Observability

Structured log events (never log tokens):

```text
google_oauth_started / google_oauth_completed
meet_subscription_created / meet_subscription_renewed
meet_event_received / meet_event_duplicate
meet_transcript_ready
meet_transcript_fetch_started / meet_transcript_fetch_completed
meet_transcript_persisted
meet_transcript_processing_started / meet_transcript_processing_completed
meet_sync_failed
```

Each carries workspace_id, project_id, correlation_id (event record id),
source_event_id, conference_record_id, transcript_id where available.
Counters are exposed in `GET /metrics` (`meet_*` summary keys).

## 13. Meetings UI terminology

- "Native Google Meet transcription"
- "Automatic transcript synchronization"
- Status block: Connected / Automatic sync Active / Last event / Transcript
  processing N pending / [Sync now]
- "Sync now" = manual reconciliation action.
- Never "live caption streams", never "Zero Quota".
- Retained paste path is labeled "Manual transcript import" and is visually
  distinct from automatic sync.
- `manual_*` conference ids render a "Developer / Seeded Data" badge.
