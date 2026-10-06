# Google Meet -> Vexa -> Sarvam -> Synora

## Purpose

This is Synora's fallback meeting-capture path for Google accounts that do not expose native Meet transcript resources.

~~~text
Google Meet
   ↓
self-hosted Vexa bot
   ↓
completed meeting recording
   ↓
Sarvam Saaras Batch STT + diarization
   ↓
Synora transcript entries
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

Vexa only joins the meeting and captures the audio.

Sarvam only performs post-meeting speech-to-text and diarization.

Synora owns transcript persistence, project routing, evidence, intelligence, memory and visualization.

The existing Google OAuth + Workspace Events + Google Meet REST path is unchanged.

## Configuration

Run the self-hosted Vexa stack outside this repository.

Set these values in the Synora backend environment:

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
SARVAM_NUM_SPEAKERS=
SARVAM_KEYTERMS=Synora,Excalidraw,WhatsApp,Google Meet
~~~

No additional Python STT SDK is required. Synora already depends on httpx.

## Usage

1. Start Vexa.
2. Start the Synora backend and frontend.
3. Open Meetings in Synora.
4. Paste a standard Google Meet URL.
5. Click Start capture.
6. Admit the Vexa bot if Google Meet puts it in the waiting room.
7. Hold the meeting normally.
8. End the meeting.
9. Vexa finishes the recording.
10. Synora resolves Vexa's completed audio recording and downloads the full audio once.
11. Synora submits the full recording to Sarvam Saaras Batch STT with diarization and timestamps.
12. Synora stores the returned speaker/timestamp segments as the meeting transcript.
13. The segments are routed through Synora's existing context resolver and Evidence model.
14. The existing shared intelligence pipeline processes the Evidence into project memory and Project Atlas updates.

Vexa is deliberately configured with `transcribe_enabled=false`: Vexa captures the meeting only. Sarvam is the
single transcription provider for this bridge. Synora does not run live STT or a second meeting-intelligence
pipeline during capture.

## Important behavior

- This is post-meeting transcription, not live transcription.
- Sarvam Batch is used because meeting recordings can be long and diarization is supported there.
- Speaker labels may initially be SPEAKER_00, SPEAKER_01, etc. The Vexa recording is mixed audio, so participant-name mapping is a later enhancement.
- Project routing is performed by Synora. Vexa and Sarvam do not select a project.
- Unresolved segments remain in Unknown Context and are not promoted into real project memory.
- Vexa and Sarvam credentials remain server-side.
- Capture state is stored in the existing Meeting.metadata_json; no new database table was added.
- Processing uses a bounded FastAPI background task. If the backend restarts during an active job, use POST /vexa/meetings/{meeting_id}/process to resume processing.

## API

Start:
POST /vexa/meetings/start

Status:
GET /vexa/meetings/{meeting_id}

Stop:
POST /vexa/meetings/{meeting_id}/stop

Resume/reprocess:
POST /vexa/meetings/{meeting_id}/process

## Current limitations

- The local Vexa stack must be running and reachable by Synora.
- The prototype uses Sarvam's external API, so audio leaves the local machine for transcription.
- Speaker diarization provides labels, but not guaranteed Google account names.
- This path does not replace the native Google Meet transcript path.
