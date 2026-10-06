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
