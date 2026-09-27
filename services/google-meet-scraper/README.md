# Synora Zero-Quota Meeting Ingestion Guide

This guide details the **zero-quota, zero-cost alternative paths** for capturing and streaming Google Meet (or any meeting) transcripts directly into Synora without relying on Google Cloud API quotas or paid Google Workspace subscriptions.

---

## Why Google Cloud API Has Quotas & Restrictions
- **Google Meet REST API v2** requires a paid **Google Workspace** subscription (Business Standard, Enterprise, or Google One Premium) to enable automated server-side cloud transcripts.
- Free `@gmail.com` accounts cannot record automated server-side transcripts via the Google Cloud API.
- Google Cloud projects enforce queries-per-minute quotas and OAuth consent verification screens.

---

## The 3 Zero-Quota Alternative Paths

### Path 1: Live Captions Browser Extension / Userscript (Recommended for Live Google Meet)
Google provides **free, real-time AI speech-to-text Closed Captions (`CC`)** to **every single Google user**, even on free personal `@gmail.com` accounts!

The [`synora-meet-captions.user.js`](file:///E:/webstack/trikaal/Synora/services/google-meet-scraper/synora-meet-captions.user.js) userscript intercepts Google Meet's live caption DOM stream:
1. Install **Tampermonkey** or **Violentmonkey** extension in your Chrome / Edge / Brave / Firefox browser.
2. Create a new script, paste the contents of `synora-meet-captions.user.js`, and save.
3. Open any Google Meet call and toggle **Turn on captions (`CC`)**.
4. A small floating badge will appear at the bottom-left:
   - Displays real-time captured lines.
   - Shows **Push to Synora** button: Click to send the transcript directly to `POST http://localhost:8000/meetings/ingest-transcript`.
   - Shows **Copy Text** button to copy all speaker dialogue with one click.
5. **Cost**: $0. **Google Cloud Quotas**: 0. **Workspace requirements**: None.

#### Quick DevTools Console Bookmarklet
If you prefer not to install Tampermonkey, you can open Chrome DevTools (`F12` -> Console) during any Google Meet call with CC turned on, paste the code from `synora-meet-captions.user.js`, and hit Enter.

---

### Path 2: Direct Paste / File Drop Ingestion inside Synora UI
In the Synora web dashboard:
1. Navigate to the **Meetings** tab in the sidebar.
2. Click the **Import / Paste Transcript** button (with the lightning badge).
3. Paste transcript text from any source:
   - Google Docs transcript export
   - Zoom / MS Teams / Otter / Fireflies exports
   - Raw notes in format `Speaker: Spoken text` or `[10:02 AM] Speaker: Spoken text`
   - Subtitle files (`.txt`, `.vtt`, `.srt`)
4. Click **Ingest & Extract Knowledge**.
5. Synora will:
   - Normalize the speakers and dialogue lines.
   - Create immutable Evidence.
   - Extract candidate decisions, requirements, and proposals.
   - Run conflict detection against existing architecture.
   - Update the Excalidraw living whiteboard automatically.

---

### Path 3: Local Offline Whisper AI (`faster-whisper`)
For 100% offline, private audio transcription without sending audio to any third party:
1. Record your meeting audio using **OBS Studio** or **Windows Voice Recorder**.
2. Run local transcription using Python `faster-whisper`:
   ```bash
   pip install faster-whisper
   ```
   ```python
   from faster_whisper import WhisperModel
   import requests

   model = WhisperModel("base.en", device="cpu", compute_type="int8")
   segments, info = model.transcribe("meeting_recording.mp3")

   entries = []
   for seg in segments:
       entries.append({"speaker": "Speaker", "text": seg.text.strip()})

   requests.post(
       "http://localhost:8000/meetings/ingest-transcript",
       json={
           "project_id": "proj_default",
           "title": "Local Whisper Meeting",
           "provider": "whisper_stt",
           "entries": entries,
           "auto_process": True,
       },
       headers={"X-User-ID": "usr_synesis_default"},
   )
   ```
3. 100% free, unlimited meeting hours, zero API limits.
