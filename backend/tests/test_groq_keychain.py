"""Groq primary + fallback keychain.

Quotas are per-key, so a 429 on the primary must retry the fallback key
before degrading a provider tier. Never touches the network: _post stubbed.
"""

from unittest.mock import MagicMock

from pydantic import BaseModel

from app.services.llm import GroqLLMClient


class TinySchema(BaseModel):
    ok: bool


def _resp(status, payload=None):
    r = MagicMock()
    r.status_code = status
    if payload is not None:
        r.json.return_value = payload
    else:
        r.text = "Rate limit reached"
    return r


def _ok_payload():
    return {"choices": [{"message": {"content": '{"ok": true}'}}]}


def test_fallback_key_serves_after_primary_429():
    client = GroqLLMClient(api_key="gsk_primary", fallback_api_key="gsk_fallback")
    calls = []

    def fake_post(api_key, payload):
        calls.append(api_key)
        if len(calls) == 1:
            return _resp(429)
        return _resp(200, _ok_payload())

    client._post = fake_post
    out = client.generate_structured("hi", TinySchema)
    assert out.ok is True
    assert calls == ["gsk_primary", "gsk_fallback"]


def test_no_fallback_key_goes_straight_to_tier_fallback():
    fallback = MagicMock()
    fallback.generate_structured.return_value = TinySchema(ok=False)
    client = GroqLLMClient(api_key="gsk_primary", fallback_client=fallback)
    client._post = lambda api_key, payload: _resp(429)
    out = client.generate_structured("hi", TinySchema)
    assert out.ok is False
    fallback.generate_structured.assert_called_once()


def test_identical_keys_not_retried_twice():
    client = GroqLLMClient(api_key="gsk_same", fallback_api_key="gsk_same")
    calls = []

    def fake_post(api_key, payload):
        calls.append(api_key)
        return _resp(429)

    client._post = fake_post
    fallback = MagicMock()
    fallback.generate_structured.return_value = TinySchema(ok=False)
    client._fallback_client = fallback
    client.generate_structured("hi", TinySchema)
    assert calls == ["gsk_same"]
