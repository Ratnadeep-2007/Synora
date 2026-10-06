# Google Meet -> Vexa -> Sarvam -> Whisper fallback -> Synora

## Purpose

Synora uses a hybrid post-meeting transcription path for Google Meet.

Sarvam Saaras v4 is the primary STT provider. Self-hosted faster-whisper is the automatic
fallback when Sarvam is unavailable, rate-limited, out of quota, times out, fails, or
returns no usable transcript.

~~~text
Google Meet
   ↓
self-hosted Vexa bot
   ↓
completed meeting recording
   ↓
Sarvam Saaras v4 (PRIMARY)
   │
   └── unavailable / failure
              ↓
      self-hosted faster-whisper
              ↓
normalized transcript
   ↓
existing Synora pipeline
   ↓
Context Resolution
   ↓
Evidence
   ↓
Candidate Knowledge
   ↓
Project Memory
   ↓
Project Atlas / Excalidraw
~~~

## Responsibilities

Vexa only captures the completed meeting audio.

Sarvam is the preferred transcription provider. Synora uses its diarization and timestamp
output for the normal Hindi/Hinglish meeting path.

Whisper is a fully self-hosted fallback running inside the Synora backend server. It is
never called when Sarvam returns a usable transcript.

Both providers are normalized into the same Synora transcript segment structure, so there
is only one downstream persistence and intelligence pipeline.

Whisper fallback does not provide speaker diarization by itself, so Whisper-generated
segments use Unknown Speaker.

## Configuration

~~~env
VEXA_ENABLED=true
VEXA_BASE_URL=http://localhost:18056
VEXA_API_KEY=your_vexa_user_token
VEXA_BOT_NAME=Synora

SARVAM_API_KEY=your_sarvam_key
SARVAM_STT_MODEL=saaras:v4
SARVAM_STT_MODE=codemix
SARVAM_WITH_DIARIZATION=true
SARVAM_LANGUAGE_CODE=
SARVAM_KEYTERMS=Synora,Excalidraw,WhatsApp,Google Meet

WHISPER_ENABLED=true
WHISPER_MODEL=large-v3-turbo
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_LANGUAGE_CODE=
WHISPER_INITIAL_PROMPT=
WHISPER_BEAM_SIZE=5
WHISPER_VAD_FILTER=true
WHISPER_CPU_THREADS=4
WHISPER_MODEL_CACHE_DIR=/app/.cache/whisper
~~~

For a GPU server, configure:

~~~env
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
~~~

The backend loads Whisper lazily and Docker Compose persists the model cache in the
whisper_model_cache volume.

## Processing behavior

1. Vexa joins Google Meet and records the meeting.
2. After the meeting, Synora waits for Vexa to finalize the recording.
3. Synora downloads the recording once.
4. Synora attempts Sarvam first.
5. If Sarvam succeeds with usable segments, those segments are persisted and the normal
   Synora pipeline continues.
6. If Sarvam fails or is unavailable, Synora records the failure reason and passes the
   same audio bytes to local faster-whisper.
7. Whisper output is normalized into the same transcript segment structure.
8. Synora persists the transcript and continues through Context Resolution, Evidence,
   project memory and Project Atlas.
9. If both providers fail, the meeting is marked failed and the combined failure is recorded.

## Provider metadata

Meeting capture metadata records the final provider and fallback state:

- transcription_provider
- transcription_model
- transcription_job_id
- transcription_fallback_used
- transcription_fallback_reason
- sarvam_job_id
- whisper_job_id

## Deployment notes

The repository installs faster-whisper in the backend image. The default fallback is
large-v3-turbo with INT8 on CPU for broad server compatibility.

The Whisper model is downloaded only when the fallback is actually needed, then reused
from the persistent cache.

For GPU deployment, enable CUDA explicitly rather than making CUDA a requirement for all
Synora servers.

Whisper fallback is local and does not consume Sarvam API quota. Sarvam remains the
primary provider for better fit with Hindi/Hinglish meetings and diarization.

## API

Start:
POST /vexa/meetings/start

Status:
GET /vexa/meetings/{meeting_id}

Stop:
POST /vexa/meetings/{meeting_id}/stop

Resume:
POST /vexa/meetings/{meeting_id}/process

## Limitations

- The Vexa stack still needs to be reachable by the Synora backend.
- Sarvam remains an external dependency when configured.
- Whisper fallback requires enough CPU/RAM or GPU resources for the selected model.
- Whisper fallback does not provide speaker diarization.
- This is post-meeting transcription, not live transcription.
- The existing native Google Meet transcript path remains unchanged.
