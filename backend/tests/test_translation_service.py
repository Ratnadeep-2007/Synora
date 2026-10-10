"""Translation service: Hindi segments get English, failures keep originals."""

import json

import pytest

from app.services import translation_service as ts


def test_needs_translation_devanagari():
    assert ts.needs_translation("किचन डिस्प्ले समय पर होना चाहिए") is True


def test_needs_translation_english_and_roman_hindi():
    assert ts.needs_translation("Kitchen display must be on time") is False
    assert ts.needs_translation("kitchen display samay par hona chahiye") is False


def test_skipped_when_nothing_needs_it(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.SARVAM_API_KEY", "k")
    monkeypatch.setattr(
        "app.core.config.settings.SARVAM_TRANSLATE_ENABLED", True
    )
    out, status = ts.translate_texts(["hello world"])
    assert out == ["hello world"]
    assert status == "skipped"


def test_disabled_without_key(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.SARVAM_API_KEY", "  ")
    out, status = ts.translate_texts(["काम समय पर"])
    assert out == ["काम समय पर"]
    assert status == "disabled"


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None):
        _FakeClient.calls.append(json)
        # Echo back numbered English lines.
        lines = json["input"].split("\n")
        translated = "\n".join(
            f"{line.split(')')[0]}) TRANSLATED" for line in lines
        )
        return _FakeResponse({"translated_text": translated})


def test_translate_success(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.SARVAM_API_KEY", "k")
    monkeypatch.setattr(
        "app.core.config.settings.SARVAM_TRANSLATE_ENABLED", True
    )
    monkeypatch.setattr("httpx.Client", _FakeClient)
    _FakeClient.calls = []
    out, status = ts.translate_texts(["काम समय पर", "plain english"])
    assert out == ["TRANSLATED", "plain english"]
    assert status == "translated"
    # Only the Hindi segment was sent.
    assert len(_FakeClient.calls) == 1


def test_line_mismatch_keeps_originals(monkeypatch):
    class _BadClient(_FakeClient):
        def post(self, url, headers=None, json=None):
            return _FakeResponse({"translated_text": "merged into one line"})

    monkeypatch.setattr("app.core.config.settings.SARVAM_API_KEY", "k")
    monkeypatch.setattr(
        "app.core.config.settings.SARVAM_TRANSLATE_ENABLED", True
    )
    monkeypatch.setattr("httpx.Client", _BadClient)
    out, status = ts.translate_texts(["पहला वाक्य यहाँ है", "दूसरा वाक्य यहाँ है"])
    assert out == ["पहला वाक्य यहाँ है", "दूसरा वाक्य यहाँ है"]
    assert status == "unavailable"


def test_http_error_keeps_originals(monkeypatch):
    class _ErrClient(_FakeClient):
        def post(self, url, headers=None, json=None):
            return _FakeResponse({"error": "quota"}, status_code=429)

    monkeypatch.setattr("app.core.config.settings.SARVAM_API_KEY", "k")
    monkeypatch.setattr(
        "app.core.config.settings.SARVAM_TRANSLATE_ENABLED", True
    )
    monkeypatch.setattr("httpx.Client", _ErrClient)
    out, status = ts.translate_texts(["काम समय पर"])
    assert out == ["काम समय पर"]
    assert status == "unavailable"


def test_translate_segments_mapping(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.SARVAM_API_KEY", "k")
    monkeypatch.setattr(
        "app.core.config.settings.SARVAM_TRANSLATE_ENABLED", True
    )
    monkeypatch.setattr("httpx.Client", _FakeClient)
    _FakeClient.calls = []
    segments = [
        {"id": "s1", "text": "निर्णय हो गया है आज"},
        {"id": "s2", "text": "all good in english"},
    ]
    mapping, status = ts.translate_segments(segments)
    assert mapping == {"s1": "TRANSLATED", "s2": "all good in english"}
    assert status == "translated"
