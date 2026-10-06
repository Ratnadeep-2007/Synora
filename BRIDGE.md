# Meet → Synora Bridge — Free Local Path (Vexa + Whisper)

**Status: IN PROGRESS — not yet working end to end.**

This document records what has been set up, what has been verified, and what is still
blocked. It is written to be honest about failures rather than to imply completion.

Nothing in the Synora application has been modified yet. The Vexa adapter, its tests
and the UI do not exist. See [Current state](#current-state).

---

## 1. The problem this solves

Google will not provide transcripts to this setup. The Google account in use is a
consumer account, where Meet's **Transcribe** control is disabled by account-level
"meeting restrictions". Consequences:

- The Google Meet REST API v2 (`meet.googleapis.com/v2`) returns **HTTP 200** for
  `conferenceRecords` and for `conferenceRecords/{id}/transcripts`, but the
  transcripts collection is **always empty**. All known conference records return
  `transcripts: []`.
- This is an **entitlement** limitation, not an integration defect. The existing
  `GoogleMeetService` client is complete and its OAuth scope
  (`meetings.space.readonly`) is valid and sufficient — the endpoint answers 200,
  not 403.

So the Meet ingestion path is built, authenticated, and starved of data.

## 2. The approach

Let a bot attend the meeting instead of relying on the platform to hand over a
transcript.

```text
Two people talk in an ordinary Google Meet
        │
        ▼
Vexa bot — joins as a normal participant, on THIS machine
        │
        ▼
Whisper — transcription (self-hosted, local)
        │
        ▼
Synora — Evidence → Context Resolution → Candidate Knowledge
                   → Project Memory → Excalidraw
```

The second participant needs only a browser and the meeting link. They install
nothing.

### Why a bot, and why Vexa

The hard part is not transcription — Whisper runs anywhere. The hard part is getting
a bot admitted into a live Meet and capturing the audio that arrives over the
network. Vexa (Apache-2.0) already solves that and runs self-hosted.

This is **additive**. The existing Google Meet REST path, the Workspace Events +
Pub/Sub path, the WhatsApp path, and all shared intelligence/memory/atlas code stay
exactly as they are.

### Ownership boundary

| Component | Responsibility |
|---|---|
| **Vexa** | meeting participation, audio capture, transcription |
| **Synora** | source normalisation, evidence, context, intelligence, memory, visualisation |

Synora never duplicates Vexa's responsibility. There is one intelligence
architecture and one memory engine, shared by all sources.

## 3. Why this survives a server deployment

The earlier local capture approach recorded **the operator's own microphone**
(`soundcard` + Windows MediaFoundation). That cannot run on a server: no audio
device, no desktop session, Windows-only.

The Vexa bot does not use the local machine's audio stack at all. It is a browser
inside a container that joins the Meet **as a remote participant** and captures
network audio. Therefore:

```text
Laptop-microphone capture  →  needs a physical machine  →  breaks on a server   ✗
Vexa bot                   →  captures network audio    →  works on a server    ✓
```

The Synora adapter reads the Vexa base URL from configuration, so pointing the same
code at a different host is a single environment variable, not a rewrite.

## 4. Host requirements (verified on this machine)

```text
OS              Windows 11 Home Single Language, 10.0.26200, 64-bit
CPU             Intel Core i7-13650HX — 14 cores / 20 threads
RAM             16 GB
Disk            ~29 GB free at time of writing
Docker Desktop  29.6.1        (engine ≥ v26 required by Vexa)
Docker Compose  v5.1.4
Node            v24.18.0
Python          3.11.15
WSL2            Ubuntu present, but WITHOUT make and WITHOUT Docker integration
```

**Windows-specific notes, verified rather than assumed:**

- The official instructions assume a Linux host and `make`. This machine has WSL2
  but no `make` installed and no Docker integration enabled in WSL. The whole
  install was therefore driven from **PowerShell using `docker compose` directly**,
  reproducing `make all` step for step.
- WSL2 invocation from PowerShell mangled line endings and failed on shebangs.
  Bash-based Vexa helper scripts (`mint-dev-env.sh`, `bin/provision-token`) cannot
  be run as-is from here. Their exact actions were performed natively in
  PowerShell instead — see §6.
- Docker Desktop's `host.docker.internal` is the correct way for containers to
  reach a service bound on the Windows host. Verified resolving to `192.168.65.254`
  from inside the Vexa stack.

## 5. What was actually run

Vexa is cloned **outside** this repository, at `E:\webstack\trikaal\vexa-local`, so
that its secrets, its ~12 GB of images, and its upstream source are never committed
here. See [Security notes](#11-security-notes).

Pinned version: commit `18e7ac1d6a0201d1489ce30b12b6f7138067a598` (v0.12 line).

### 5.1 Clone and seed

```powershell
git clone --depth 1 https://github.com/Vexa-ai/vexa.git E:\webstack\trikaal\vexa-local
```

### 5.2 Seed environment files and mint secrets

`make all` normally runs `mint-dev-env.sh`, which mints
`INTERNAL_API_SECRET`, `VEXA_FLOWS_API_KEY` and `VEXA_FLOWS_TIMELINE_KEY`. Performed
natively (see §4):

```powershell
cd E:\webstack\trikaal\vexa-local\deploy\compose
Copy-Item .env.example .env
# mint the three secrets with [System.Security.Cryptography.RandomNumberGenerator]
```

The transcription unit is configured separately:

```powershell
cd ..\transcription
Copy-Item .env.example .env
# MODEL_SIZE=small  (see §7)
# API_TOKEN=<same 32-byte secret as the stack's TRANSCRIPTION_SERVICE_TOKEN>
```

### 5.3 Transcription unit (CPU Whisper)

```powershell
cd E:\webstack\trikaal\vexa-local\deploy\transcription
docker compose -f docker-compose.cpu.yml up -d --build
```

### 5.4 Main stack

```powershell
cd E:\webstack\trikaal\vexa-local\deploy\compose
docker compose -p vexa-v012 -f docker-compose.yml pull
docker pull vexaai/v012-agent-worker:v012
docker pull vexaai/vexa-bot:v012
docker compose -p vexa-v012 -f docker-compose.yml up -d --no-build
```

### 5.5 Mint the API key

```powershell
$H  = @{ 'X-Admin-API-Key' = 'dev-admin-token' }
$u  = Invoke-RestMethod -Uri 'http://127.0.0.1:18057/admin/users' -Method Post `
      -Headers ($H + @{ 'Content-Type' = 'application/json' }) `
      -Body '{"email":"self-host@vexa.ai","max_concurrent_bots":5}'
$t  = Invoke-RestMethod -Uri "http://127.0.0.1:18057/admin/users/$($u.id)/tokens?scopes=bot,tx" `
      -Method Post -Headers $H
$t.token     # -> vxa_bot_...
```

The key is written to `E:\webstack\trikaal\vexa-local\.api_key_local`, which is
**outside the repository**.

### 5.6 Useful endpoints

```text
API gateway     http://localhost:18056
Terminal UI     http://localhost:13000
admin-api       http://localhost:18057
meeting-api     http://localhost:18080
Transcription   http://localhost:8083        (when built)
```

## 6. Verified health report

```text
Docker engine             OK   29.6.1
Vexa gateway :18056       OK   key auth validates
meeting-api :18080        OK   /health 200, object storage configured
postgres / redis          OK   healthy
Bot image                 OK   vexaai/vexa-bot:v012, registry digest confirmed
agent-worker image        OK   vexaai/v012-agent-worker:v012
Local Whisper (STT)       BLOCKED — build failing, see §8
Bot joins a real Meet     NOT TESTED
Synora adapter            NOT WRITTEN
```

## 7. Design decisions and why

**`MODEL_SIZE=small` for CPU transcription.** Vexa's own documentation for the CPU
variant states that `medium` cannot keep pace with real-time meeting audio on CPU
and sheds load with `503 Service busy`, which results in *no transcript at all*;
`small` is the size witnessed to hold pace on roughly 4–6 vCPU. Accuracy is traded
deliberately, because an unusable transcript is worse than a less accurate one.
This machine has 20 threads, so `medium` may become viable — measured, not assumed.

**`TRANSCRIPTION_SERVICE_URL` points at the host gateway.** The bot container must
reach the STT unit, so `http://host.docker.internal:8083` is used rather than
`localhost`.

**Vexa is not vendored into this repository.** It is upstream Apache-2.0 software
that this project *runs*, not code it owns. Keeping it separate avoids committing
secrets and large image layers, and keeps `git pull` possible.

## 8. Blockers encountered, and what they actually were

Recorded because they cost significant time and because two of them were
initially misdiagnosed.

### 8.1 Local Whisper build — unresolved

Five build attempts. All died at the same dependency step, downloading Python
wheels (first `uvloop`). Diagnoses, in order:

1. Initially believed to be a slow download. `UV_HTTP_TIMEOUT=300` was added to
   `core/meetings/services/transcription/Dockerfile.cpu` as a **local-only** change.
   This did not resolve it.
2. The true blocker then surfaced: `docker pull python:3.10-slim` failed with
   `TLS handshake timeout` against Docker Hub. **Docker Hub connectivity from this
   machine is intermittent.** Later it succeeded, and a rebuild was launched.

Every stage before the dependency install succeeded, including a 44-minute
`apt-get` install of ffmpeg and X11 libraries. Only wheel download fails.

### 8.2 Vexa's per-user transcription override silently wins

Even with `TRANSCRIPTION_SERVICE_URL` and `TRANSCRIPTION_SERVICE_TOKEN` correctly
set in `deploy/compose/.env`, `POST /bots` answered **503**:

```json
{"detail":"the configured transcription backend is not working: unauthorized —
 the configured token was REJECTED by the endpoint"}
```

This message is misleading. Investigation found:

```text
GET /user/transcription  ->  {"url":null,"token_set":false,"token":null}
```

The per-user setting takes precedence over the deployment environment, and it was
empty. Fix, once working credentials exist:

```bash
PUT /user/transcription
{"url": "...", "token": "...", "model": "..."}
```

### 8.3 Groq is unreachable from Docker bridge networking

Groq was evaluated as a temporary transcription backend because it exposes the same
OpenAI-compatible `/v1/audio/transcriptions` interface that local Whisper does.
It was **rejected on evidence**:

```text
host network   → HTTP 401   (Groq reached; 401 = auth required, correct)
bridge network → HTTP 403   Cloudflare "error code: 1010", before authentication
```

The key itself was proven valid — identical SHA-256 inside and outside the
container, and `GET /models` returned 200 from the host. Groq's Cloudflare blocks
Docker bridge egress from this network. Local Whisper has no Cloudflare in its path,
which is one reason it remains the correct target despite the build problems.

### 8.4 Docker daemon flaked under combined load

During simultaneous image pulls, an image build and stack bring-up, the Docker
daemon returned a transient API-version error and the gateway container failed its
first start. A retry succeeded and it has been healthy since. Noted because the
same flake could recur when the 6.5 GB bot container spawns.

### 8.5 WSL2 is not usable as documented for this host

`make` is not installed and Docker Desktop's WSL integration is disabled, so the
documented `git clone && make all` path cannot be followed verbatim here. Every step
was reproduced in PowerShell. This is a deviation from upstream instructions and is
recorded rather than hidden.

## 9. What is not done

```text
Local Whisper image                       blocked
Bot joining a real Google Meet            never attempted
Transcript retrieved from Vexa            never attempted
Synora Vexa adapter                       not written
Evidence / project routing / memory       never exercised with Vexa output
Excalidraw update from Vexa evidence      never exercised
Unit / integration / isolation tests      not written
docs/VEXA_GOOGLE_MEET_LOCAL_SETUP.md      not written (this file precedes it)
.env.example VEXA_* entries               not added
Frontend UI                               not added
```

No Synora application code has been modified. The existing Google Meet,
Google Workspace Events / Pub/Sub, WhatsApp, shared intelligence, shared memory and
Excalidraw paths are untouched.

## 10. Planned shape of the integration

Not implemented. Recorded so the intent is reviewable before code is written.

```text
backend/app/services/vexa_google_meet_service.py   Vexa API client (spawn, poll, stop)
backend/app/connectors/vexa_google_meet.py         segments → SourceEventCreate
backend/app/api/vexa_meetings.py                   POST /vexa/meetings/start, status, stop
backend/app/core/config.py                         VEXA_* settings
backend/tests/vexa/                                unit, idempotency, isolation, failure
docs/VEXA_GOOGLE_MEET_LOCAL_SETUP.md               reproducible setup guide
```

### Source semantics — Vexa is not a new platform

The platform remains `google_meet`. Vexa is a capture and transcription provider.

```text
source                  = google_meet
capture_provider        = vexa
transcription_provider  = whisper
ingestion_mode          = self_hosted_vexa
```

No redundant enum values; existing `Meeting.provider = "google"` is reused so the
Vexa path and the REST path converge on the same domain model.

### Required properties

- **Idempotency.** Repeated retrieval of the same Vexa transcript must not create
  duplicate `Meeting`, `Participant`, `Transcript`, `TranscriptEntry`,
  `SourceEvent`, `Evidence`, `CandidateKnowledge`, memory entries or visual
  operations. The existing unique constraints — `(provider, provider_conference_id)`,
  `(meeting_id, provider_participant_id)`, `(transcript_id, provider_entry_id)`,
  `(project_id, source, source_event_id)` — are the mechanism. Ingestion must use
  upstream Vexa segment ids as `provider_entry_id`.
- **Asynchronous.** The HTTP request that starts a capture must not stay open while
  the bot joins, the meeting runs, and transcription completes. A bounded background
  poller, matching the existing in-process worker pattern, is the intent.
- **No guessing at project.** Segment-level routing uses the existing Context
  Resolution service, including its Unknown Context behaviour. A Vexa transcript is
  never force-filed into a project.
- **No credential exposure.** The Vexa API key stays server-side. It is never sent
  to the browser, and it is never logged.

### Configuration to be added to `.env.example`

```env
VEXA_BASE_URL=http://localhost:18056
VEXA_API_KEY=
VEXA_ENABLED=false
VEXA_BOT_NAME=Vexa
VEXA_POLL_INTERVAL_SECONDS=15
VEXA_MAX_WAIT_SECONDS=14400
```

Credentials are never committed; `.env` is already gitignored via `**/.env`.

## 11. Security notes

- No API key, OAuth secret, token or meeting link has been written into this
  repository or this document.
- The Vexa API key lives in `E:\webstack\trikaal\vexa-local\.api_key_local`, outside
  the repository, and is never committed.
- `TRANSCRIPTION_SERVICE_TOKEN` and `ADMIN_TOKEN` live in Vexa's own `.env` files
  outside the repository.
- `.env` in this repository is gitignored (confirmed: `git check-ignore -v .env`
  matches `**/.env`).
- The Synora endpoints that will be added must require the existing authenticated
  user context; no unauthenticated public route for capture control.

## 12. How to resume

1. Confirm Docker Hub is reachable: `docker pull python:3.10-slim`
2. Build the transcription unit and wait for the model to load:
   ```powershell
   cd E:\webstack\trikaal\vexa-local\deploy\transcription
   docker compose -f docker-compose.cpu.yml up -d --build
   curl.exe http://localhost:8083/health
   ```
3. Point the stack back at the local unit — it is currently pointed at Groq, which
   is blocked from bridge networking:
   ```powershell
   cd ..\compose
   # TRANSCRIPTION_SERVICE_URL=http://host.docker.internal:8083
   # TRANSCRIPTION_SERVICE_TOKEN=<the STT API_TOKEN>
   # Clear the per-user override, or it keeps winning:
   #   PUT /user/transcription  {"url":null,"token":null,"model":null}
   docker compose -p vexa-v012 -f docker-compose.yml up -d --force-recreate meeting-api
   curl.exe "http://localhost:18080/health?force=1"
   ```
   Expect `capabilities.stt.state` to become `configured`.
4. Only then run the first real meeting test (§13).

## 13. Planned first real meeting test

Deliberately **before** any Synora code is written.

```text
1. Create a Google Meet, two human participants
2. POST /bots  (platform=google_meet, native_meeting_id=<code>, transcribe_enabled=true)
3. Confirm the bot joins; admit it if Meet shows a lobby prompt
4. Hold a short conversation naming one project and its requirements
5. End the meeting, stop the bot
6. Poll GET /transcripts/google_meet/<code> and inspect segments, speakers, timestamps
7. Only then write the Synora adapter against real output
```

Then, in the Synora repository: real transcript → `SourceEvent` → `Evidence` →
project classification → `CandidateKnowledge` → `ProjectMemory` → Excalidraw,
followed by project-isolation, unknown-context, evidence-traceability and
idempotency tests, and a regression run of the existing suite.

## 14. Reference

- Vexa repository — <https://github.com/Vexa-ai/vexa>
- Vexa self-hosting — <https://docs.vexa.ai/self-hosting>
- Vexa Meetings API — <https://docs.vexa.ai/api/meetings>
- Vexa send-a-bot — <https://docs.vexa.ai/how-to/send-a-bot>
