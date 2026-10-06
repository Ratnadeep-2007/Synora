import pytest

from app.services.vexa_sarvam_service import (
    VexaSarvamError,
    VexaSarvamService,
    parse_google_meet_code,
)


def test_parse_google_meet_code():
    assert parse_google_meet_code("https://meet.google.com/abc-defg-hij") == "abc-defg-hij"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://meet.google.com/abc-defg",
        "https://example.com/abc-defg-hij",
        "meet.google.com/abc-defg-hij",
    ],
)
def test_parse_google_meet_code_rejects_invalid_urls(value):
    with pytest.raises(VexaSarvamError):
        parse_google_meet_code(value)


def test_extract_sarvam_diarized_entries():
    result = {
        "language_code": "en-IN",
        "diarized_transcript": {
            "entries": [
                {
                    "speaker_id": "SPEAKER_00",
                    "transcript": "We need the attendance feature.",
                    "start_time_seconds": 1.2,
                    "end_time_seconds": 3.8,
                },
                {
                    "speaker_id": "SPEAKER_01",
                    "transcript": "Let's target Friday.",
                    "start_time_seconds": 4.0,
                    "end_time_seconds": 5.5,
                },
            ]
        },
    }
    entries = VexaSarvamService.extract_sarvam_entries(result)
    assert len(entries) == 2
    assert entries[0]["speaker"] == "SPEAKER_00"
    assert entries[0]["start_seconds"] == 1.2
    assert entries[1]["text"] == "Let's target Friday."


def test_extract_sarvam_plain_transcript_fallback():
    entries = VexaSarvamService.extract_sarvam_entries({"transcript": "Hello world"})
    assert entries == [
        {
            "id": "seg_000000",
            "text": "Hello world",
            "speaker": "Unknown Speaker",
            "start_seconds": 0.0,
            "end_seconds": 0.0,
        }
    ]


@pytest.mark.asyncio
async def test_wait_for_completed_recording_accepts_completed_at(monkeypatch):
    service = VexaSarvamService(vexa_api_key="test")
    responses = iter([
        {"recordings": [{"id": 41, "status": "recording"}]},
        {"recordings": [{"id": 41, "status": "completed", "completed_at": "2026-10-06T10:00:00Z"}]},
    ])

    async def fake_get_meeting_artifacts(_meeting_code):
        return next(responses)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(service, "get_meeting_artifacts", fake_get_meeting_artifacts)
    monkeypatch.setattr("app.services.vexa_sarvam_service.asyncio.sleep", fake_sleep)

    recording = await service.wait_for_completed_recording(
        "abc-defg-hij", poll_seconds=2, max_wait_seconds=10
    )
    assert recording["id"] == 41


@pytest.mark.asyncio
async def test_resolve_audio_url_uses_vexa_raw_url_without_media_id():
    service = VexaSarvamService(vexa_base_url="http://localhost:18056", vexa_api_key="test")
    recording_id, raw_url = await service._resolve_audio_url({
        "id": 42,
        "status": "completed",
        "raw_url": "/recordings/42/media/7/raw?type=audio",
    })
    assert recording_id == "42"
    assert raw_url == "http://localhost:18056/recordings/42/media/7/raw?type=audio"


@pytest.mark.asyncio
async def test_resolve_audio_url_rejects_recording_without_audio_locator():
    service = VexaSarvamService(vexa_api_key="test")
    with pytest.raises(VexaSarvamError, match="media file ID or raw URL"):
        await service._resolve_audio_url({"id": 42, "status": "completed"})

@pytest.mark.asyncio
async def test_transcribe_with_fallback_does_not_call_whisper_when_sarvam_succeeds(monkeypatch):
    service = VexaSarvamService(sarvam_api_key="test")

    async def fake_sarvam(*_args, **_kwargs):
        return (
            {
                "language_code": "hi-IN",
                "diarized_transcript": {
                    "entries": [
                        {
                            "speaker_id": "SPEAKER_00",
                            "transcript": "Sarvam success",
                            "start_time_seconds": 0,
                            "end_time_seconds": 1,
                        }
                    ]
                },
            },
            "sarvam-job-1",
        )

    async def fail_whisper(*_args, **_kwargs):
        raise AssertionError("Whisper must not run when Sarvam succeeds.")

    monkeypatch.setattr(service, "transcribe_with_sarvam", fake_sarvam)
    monkeypatch.setattr(
        "app.services.vexa_sarvam_service.WhisperTranscriptionService.transcribe",
        fail_whisper,
    )

    result = await service._transcribe_with_fallback(
        b"audio",
        "meeting.webm",
        "audio/webm",
        "meeting-1",
    )
    assert result[1] == "sarvam_saaras"
    assert result[3] == "sarvam-job-1"


@pytest.mark.asyncio
async def test_transcribe_with_fallback_uses_whisper_when_sarvam_fails(monkeypatch):
    service = VexaSarvamService(sarvam_api_key="test")

    async def fail_sarvam(*_args, **_kwargs):
        raise VexaSarvamError("HTTP 429 quota exceeded")

    async def fake_whisper(*_args, **_kwargs):
        return (
            {
                "language_code": "hi-IN",
                "segments": [
                    {
                        "id": "whisper-1",
                        "text": "Whisper fallback",
                        "speaker": "Unknown Speaker",
                        "start_seconds": 1.0,
                        "end_seconds": 2.0,
                    }
                ],
            },
            "whisper:large-v3-turbo",
        )

    monkeypatch.setattr(service, "transcribe_with_sarvam", fail_sarvam)
    monkeypatch.setattr(
        "app.services.vexa_sarvam_service.WhisperTranscriptionService.transcribe",
        fake_whisper,
    )

    result = await service._transcribe_with_fallback(
        b"audio",
        "meeting.webm",
        "audio/webm",
        "meeting-2",
    )
    assert result[1] == "whisper_faster_whisper"
    assert result[2] == "large-v3-turbo"
    assert result[3] == "whisper:large-v3-turbo"
    assert result[4] == "hi-IN"
    assert result[5] == "HTTP 429 quota exceeded"


@pytest.mark.asyncio
async def test_transcribe_with_fallback_uses_whisper_without_sarvam_key(monkeypatch):
    service = VexaSarvamService(sarvam_api_key="")

    async def fake_whisper(*_args, **_kwargs):
        return (
            {
                "language_code": "hi-IN",
                "segments": [
                    {
                        "id": "whisper-1",
                        "text": "Local transcription",
                        "speaker": "Unknown Speaker",
                        "start_seconds": 0.0,
                        "end_seconds": 1.0,
                    }
                ],
            },
            "whisper:large-v3-turbo",
        )

    monkeypatch.setattr(
        "app.services.vexa_sarvam_service.WhisperTranscriptionService.transcribe",
        fake_whisper,
    )

    result = await service._transcribe_with_fallback(
        b"audio",
        "meeting.webm",
        "audio/webm",
        "meeting-3",
    )
    assert result[1] == "whisper_faster_whisper"
    assert result[5] == "SARVAM_API_KEY is not configured."


@pytest.mark.asyncio
async def test_transcribe_with_fallback_reports_both_failures(monkeypatch):
    service = VexaSarvamService(sarvam_api_key="test")

    async def fail_sarvam(*_args, **_kwargs):
        raise VexaSarvamError("Sarvam unavailable")

    async def fail_whisper(*_args, **_kwargs):
        raise WhisperFallbackError("Whisper unavailable")

    monkeypatch.setattr(service, "transcribe_with_sarvam", fail_sarvam)
    monkeypatch.setattr(
        "app.services.vexa_sarvam_service.WhisperTranscriptionService.transcribe",
        fail_whisper,
    )

    with pytest.raises(VexaSarvamError, match="Whisper fallback failed"):
        await service._transcribe_with_fallback(
            b"audio",
            "meeting.webm",
            "audio/webm",
            "meeting-4",
        )
