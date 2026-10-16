import pytest
from app.services.vexa_sarvam_service import VexaSarvamService, VexaSarvamError


@pytest.mark.asyncio
async def test_fallback_stage_is_reported_before_whisper_runs(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "WHISPER_ENABLED", True)
    service = VexaSarvamService(sarvam_api_key="test")
    stages = []

    async def fail_sarvam(*args):
        raise VexaSarvamError("HTTP 402: no credits")

    async def whisper(*args):
        assert stages == ["HTTP 402: no credits"]
        return {"segments": [{"id": "s1", "text": "Actual speech"}], "language_code": "en"}, "whisper:test"

    monkeypatch.setattr(service, "transcribe_with_sarvam", fail_sarvam)
    monkeypatch.setattr("app.services.vexa_sarvam_service.WhisperTranscriptionService.transcribe", whisper)
    result = await service._transcribe_with_fallback(b"audio", "meeting.webm", "audio/webm", "mtg_test", on_fallback=stages.append)
    assert result[1] == "whisper_faster_whisper"
    assert result[5] == "HTTP 402: no credits"


def test_project_resolution_preserves_actual_transcription_provider(monkeypatch):
    import json
    from types import SimpleNamespace
    captured = {}

    class Resolver:
        def resolve_context(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(project_id=None, decision="unknown", confidence=0)

    monkeypatch.setattr("app.services.vexa_sarvam_service.ContextResolutionService", Resolver)
    meeting = SimpleNamespace(id="mtg_test", provider_conference_id="abc-defg-hij", title="Test", workspace_id="ws_default", metadata_json=json.dumps({"vexa_capture":{"transcription_provider":"whisper_faster_whisper"}}))
    VexaSarvamService()._resolve_project("Actual speech", "Unknown Speaker", meeting, None, [SimpleNamespace(id="proj_test")])
    assert captured["meeting_metadata"]["transcription_provider"] == "whisper_faster_whisper"
