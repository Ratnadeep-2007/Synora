# Meet → Synora Bridge

Google Meet capture via a self-hosted **Vexa** bot, transcription via **Sarvam**
(primary) with self-hosted **faster-whisper** (fallback), feeding the existing
Synora evidence → intelligence → memory → atlas pipeline.

**Status: infrastructure verified, end-to-end meeting not yet run.**
A real two-person Google Meet has not been captured yet, so no transcript has been
proven to reach Evidence, Project Memory or Excalidraw. See
[What is not proven](#8-what-is-not-proven).

---

## 1. Architecture

```text
                        ordinary Google Meet
                               │
                               │  second participant needs only a browser
                               ▼
                  ┌────────────────────────┐
                  │  Vexa bot (LOCAL)      │   joins as a normal participant,
                  │  browser in container  │   captures meeting audio only
                  └───────────┬────────────┘
                              │  completed recording
                              ▼
                  ┌────────────────────────┐
                  │  Sarvam Saaras v4      │   PRIMARY  · diarization,
                  │  api.sarvam.ai         │            Hindi / Hinglish
                  └───────────┬────────────┘
                              │  unavailable / failure / no usable transcript
                              ▼
                  ┌────────────────────────┐
                  │  faster-whisper        │   FALLBACK · self-hosted,
                  │  inside Synora backend │            no diarization
                  └───────────┬────────────┘
                              │  normalized segments (one shape)
                              ▼
                  ┌────────────────────────┐
                  │  Existing Synora       │
                  │  pipeline              │
                  └───────────┬────────────┘
                              ▼
        Context Resolution → Evidence → Candidate Knowledge
                              → Project Memory → Project Atlas / Excalidraw
```

### Responsibility split

| Component | Owns |
|---|---|
| **Vexa** | meeting participation, audio capture |
| **Synora** | normalisation, evidence, context, intelligence, memory, visualisation |

Synora never re-implements capture. There is exactly one intelligence architecture
and one memory engine; Sarvam and Whisper both normalise into the same segment
structure, so there is one downstream pipeline.

### Why this survives deployment on a server

The earlier approach recorded the operator's own microphone via `soundcard` +
Windows MediaFoundation. That cannot run on a server — no audio device, no desktop
session, Windows-only.

The Vexa bot does not touch the host audio stack. It is a browser in a container
that joins as a **remote participant** and captures network audio:

```text
laptop-microphone capture  →  needs a physical machine  →  breaks on server  ✗
Vexa bot                   →  captures network audio    →  works on server   ✓
```

`VEXA_BASE_URL` is configuration, so retargeting the same code at another host is
one environment variable.

## 2. API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/vexa/meetings/start` | parse link, spawn bot, queue processing |
| `GET` | `/api/v1/vexa/meetings/{meeting_id}` | capture status + provider metadata |
| `POST` | `/api/v1/vexa/meetings/{meeting_id}/stop` | request bot stop (async) |
| `POST` | `/api/v1/vexa/meetings/{meeting_id}/process` | re-run ingestion / recovery |

```bash
curl -X POST http://localhost:8000/api/v1/vexa/meetings/start \
  -H 'X-User-ID: usr_default' -H 'Content-Type: application/json' \
  -d '{"meeting_url":"https://meet.google.com/abc-defg-hij"}'
```

All routes require the existing authenticated user context. No public route, and
the Vexa API key is never sent to the browser.

## 3. Source semantics

Vexa is **not** a new meeting platform. The platform stays `google_meet`; Vexa is a
capture provider and Sarvam/Whisper are transcription providers. Recorded in
`Meeting.metadata_json` under `vexa_capture`:

```text
provider                    = "google"
capture_provider            = "vexa"
transcription_provider      = "sarvam_saaras" | "whisper_faster_whisper"
transcription_model         = provider model id
transcription_job_id        = provider job id
transcription_fallback_used = bool
transcription_fallback_reason = str
sarvam_job_id / whisper_job_id
```

Because `Meeting.provider` stays `google`, the Vexa path and the native Meet REST
path converge on the same domain model and the same pipeline.

## 4. Repository files

```text
backend/app/api/vexa_meetings.py                  start / status / stop / process
backend/app/services/vexa_sarvam_service.py       Vexa client, Sarvam STT, ingestion
backend/app/services/whisper_transcription_service.py   self-hosted fallback
backend/app/core/config.py                        VEXA_*, SARVAM_*, WHISPER_*
backend/tests/test_vexa_sarvam_service.py         unit coverage
doc/MEET_VEXA_SARVAM.md                           detailed design
```

## 5. Local requirements (verified)

```text
OS              Windows 11 Home Single Language, 10.0.26200, 64-bit
CPU             Intel Core i7-13650HX — 14 cores / 20 threads
RAM             16 GB
Docker Desktop  29.6.1        Vexa requires engine >= v26
Docker Compose  v5.1.4
Node            v24.18.0
Python          3.11.15
WSL2            present, but no make and no Docker integration
```

### Windows-specific deviations

The official Vexa install path assumes a Linux host and `make`. On this machine
WSL2 has neither `make` nor Docker integration, so the documented
`git clone && make all` route cannot be followed verbatim. Every step was
reproduced in **PowerShell using `docker compose` directly**. Vexa was cloned
**outside** this repository to keep its secrets and its ~12 GB of images out of git.

### Ports

| Port | Service |
|---|---|
| `18056` | Vexa API gateway |
| `18057` | admin-api (mints API keys) |
| `18080` | meeting-api |
| `13000` | Vexa terminal UI |
| `8000` | Synora backend |

## 6. Setup — commands that worked

### 6.1 Vexa

```powershell
git clone --depth 1 https://github.com/Vexa-ai/vexa.git E:\webstack\trikaal\vexa-local
cd E:\webstack\trikaal\vexa-local\deploy\compose
Copy-Item .env.example .env
# mint INTERNAL_API_SECRET, VEXA_FLOWS_API_KEY, VEXA_FLOWS_TIMELINE_KEY
docker compose -p vexa-v012 -f docker-compose.yml pull
docker pull vexaai/v012-agent-worker:v012
docker pull vexaai/vexa-bot:v012
docker compose -p vexa-v012 -f docker-compose.yml up -d --no-build
```

Mint a scoped API key (`scopes=bot,tx`) via `admin-api`, then store it in
Synora's `.env` as `VEXA_API_KEY`.

### 6.2 Synora

Append to `.env` (values below are the defaults that matter):

```env
VEXA_ENABLED="true"
VEXA_BASE_URL="http://localhost:18056"
VEXA_API_KEY="<minted locally; never committed>"
VEXA_BOT_NAME="Synora"
VEXA_POLL_INTERVAL_SECONDS="10"
VEXA_MAX_WAIT_SECONDS="14400"

SARVAM_API_KEY=""              # set to enable the primary provider
SARVAM_STT_MODEL="saaras:v4"
SARVAM_STT_MODE="codemix"
SARVAM_WITH_DIARIZATION="true"
SARVAM_KEYTERMS="Synora,Excalidraw,WhatsApp,Google Meet"

WHISPER_ENABLED="true"
WHISPER_MODEL="large-v3-turbo"
WHISPER_DEVICE="cpu"
WHISPER_COMPUTE_TYPE="int8"
WHISPER_CPU_THREADS="6"
```

`.env` is gitignored via `**/.env` (confirmed with `git check-ignore`).

### 6.3 User procedure

```text
1. Start Docker Desktop
2. cd vexa-local\deploy\compose ; docker compose -p vexa-v012 up -d
3. Start Synora (start.bat)
4. Open Synora → Meetings → paste Google Meet link → Start Capture
5. Other person joins the Meet from a browser
6. Admit the bot if Meet shows it in the waiting room
7. Talk, then end the meeting
8. Synora waits for the recording, transcribes, ingests automatically
9. Open the project → verify memory and Excalidraw
```

## 7. Verified

```text
Full backend suite                     374 passed, 0 failed
Vexa routes mounted                    POST/GET/POST/POST under /api/v1/vexa
Invalid Meet code shape                400
Wrong host                             400
Empty meeting_url                      422
Missing authentication                 401
Unknown meeting id                     404
Vexa gateway health                    200, key auth validates
Bot container spawn                    PROVEN — runtime spawned a browser container,
                                       navigated Meet, attempted join
Recording wait loop                    unit-covered with stubbed responses
Provider selection                     unit-covered: Whisper not called when
                                       Sarvam returns a usable transcript
```

### Bot spawn proven

`POST /vexa/meetings/start` with the placeholder code `abc-defg-hij` caused Vexa's
runtime to spawn bot container `vexa-mtg-1-933a50e2`, which launched a browser,
navigated to Meet, muted mic/camera, and then failed to find a join button across
all five selectors.

That failure is **correct**: the code is not a real meeting, so Meet served an
error page instead of a join screen. It confirms the whole chain executes —
Synora → Vexa gateway → runtime → bot container → browser automation.

## Speaker identity for 5+ person meetings

Sarvam remains the diarization backbone. Synora keeps raw Sarvam speaker IDs separate from human names and never maps speakers by participant order.

For better human-readable attribution, the bridge now:

1. Reads Vexa participant names best-effort when the deployed Vexa version exposes the participants endpoint.
2. Looks for explicit self-identification near the start of the meeting, such as: Hi, I'm Siddhi; My name is Neha; mera naam Ratnadeep hai; main Omesh hoon.
3. Maps the matching Sarvam speaker cluster to that name.
4. Marks roster-backed matches as confirmed, self-introduction-only matches as provisional, and conflicting claims as unresolved.
5. Retains raw speaker IDs, identity status, confidence, and identity source for auditability.

For a known five-person meeting, SARVAM_NUM_SPEAKERS=5 can be configured. Do not hard-code speaker order.

Whisper fallback remains conservative and does not claim diarization or human identity from the mixed recording; fallback segments stay Unknown Speaker.
## 8. What is not proven

```text
A real two-person Google Meet has not been captured.
No recording has been downloaded from Vexa.
No Sarvam transcription has run (no API key configured).
No Whisper transcription has run (model weights not yet downloaded).
No transcript has reached Evidence / Candidate Knowledge / Project Memory.
No Excalidraw update has been exercised through this path.
Project isolation, unknown-context behaviour and evidence traceability
    have not been tested against real Vexa output.
Idempotency across repeated ingestion of one Vexa transcript is not tested
    against a real recording.
```

The transcription branch most likely to work first depends on configuration:

| Provider | Needs | Status |
|---|---|---|
| Sarvam (primary) | `SARVAM_API_KEY` | key absent |
| Whisper (fallback) | ~1.5 GB model download | stalled on this network |

## 9. Environment notes from this machine

These cost real time and are recorded so they are not rediscovered.

**Docker Hub connectivity is intermittent.** Image pulls failed with
`TLS handshake timeout` more than once, and the faster-whisper image build needed
several attempts before succeeding. Large downloads are the common failure.

**Groq is unreachable from Docker bridge networking.** Groq exposes the same
OpenAI-compatible `/v1/audio/transcriptions` interface, so it was evaluated as a
transcription backend and rejected on evidence:

```text
host network    -> HTTP 401   (Groq reached; 401 = auth required, correct)
bridge network  -> HTTP 403   Cloudflare "error code: 1010", before authentication
```

The key was proven valid — identical SHA-256 inside and outside the container, and
`GET /models` returned 200 from the host. Any hosted STT behind Cloudflare will hit
the same wall from inside a container.

**Vexa's per-user transcription override silently wins.** With
`TRANSCRIPTION_SERVICE_URL`/`TOKEN` correctly set in `deploy/compose/.env`,
`POST /bots` still answered 503 "token was REJECTED", because
`GET /user/transcription` returned an empty override that takes precedence over
the deployment environment. That diagnostic message is misleading.

*(The Vexa-side STT sidecar is **not** used by this architecture — Whisper runs
inside the Synora backend. It is only relevant if Vexa itself is asked to
transcribe.)*

## 10. Test coverage added

- Google Meet code extraction, including rejection of truncated codes
- Recording wait loop accepting a completed recording
- Audio URL resolution via Vexa's `raw_url`, and via the master endpoint
- Rejection of a recording with no audio locator
- Sarvam diarized-entry extraction
- Fallback selection: Whisper not invoked when Sarvam succeeds
- Five-person identity resolution with explicit self-introduction
- Unknown-speaker and identity-collision safety

## 11. Security

- No API key, OAuth secret or meeting link is committed. The Vexa key lives in
  `vexa-local/.api_key_local`, outside the repository.
- `VEXA_API_KEY` and `SARVAM_API_KEY` ship **empty** in `.env.example`.
- Capture control requires the authenticated user context; every Vexa route
  resolves the current user and scopes meetings by `user_id`.
- Meeting codes are validated before any outbound Vexa call, so a malformed link
  cannot be used to probe arbitrary meetings.
- Transcripts are never logged in full.

## 12. Limitations

- The Vexa stack must be reachable by the Synora backend.
- Sarvam, when configured, is an external dependency and meeting audio leaves the
  machine.
- Whisper fallback needs enough CPU/RAM for the selected model; `large-v3-turbo` on
  CPU is slow and has no diarization, so those segments are `Unknown Speaker`.
- Post-meeting transcription only — not live.
- Whisper weights download on first use; on a constrained network that download may
  fail, in which case both providers are unavailable.
- The native Google Meet transcript path, Workspace Events / Pub/Sub path and
  WhatsApp path are unchanged. The Vexa path is additive.

## 13. References

- Vexa — <https://github.com/Vexa-ai/vexa>
- Vexa self-hosting — <https://docs.vexa.ai/self-hosting>
- Vexa Meetings API — <https://docs.vexa.ai/api/meetings>
- Internal design detail — [`doc/MEET_VEXA_SARVAM.md`](doc/MEET_VEXA_SARVAM.md)
