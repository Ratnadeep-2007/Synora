"""Regression: Neon Auth JWT issuer is the auth ORIGIN, not the API base URL.

A token minted through ".../neondb/auth" carries iss="https://<host>".
Verifying against the full base URL rejected every genuine login (401).
"""
import time

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core import neon_auth
from app.core.config import settings


def test_expected_issuer_is_origin(monkeypatch):
    monkeypatch.setattr(settings, "NEON_AUTH_BASE_URL", "https://auth.example.com/neondb/auth")
    assert neon_auth.expected_issuer() == "https://auth.example.com"
    monkeypatch.setattr(settings, "NEON_AUTH_BASE_URL", "https://auth.example.com")
    assert neon_auth.expected_issuer() == "https://auth.example.com"


class _FakeMappings:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _FakeMappings(self._row)


class _FakeDb:
    def __init__(self, row):
        self._row = row

    def execute(self, statement, params):
        assert params["token"]
        return _FakeResult(self._row)


def test_verify_session_token_introspection():
    import uuid

    neon_auth._SESSION_CACHE.clear()
    # Postgres returns uuid columns as UUID objects; claims must be strings
    # or downstream sha256(subject.encode()) crashes with AttributeError.
    row = {"user_id": uuid.UUID("12345678-1234-5678-1234-567812345678"), "email": "a@example.com", "name": "A", "verified": True, "banned": False}
    claims = neon_auth.verify_session_token("opaque-session-token", _FakeDb(row))
    assert claims is not None
    assert claims["sub"] == "12345678-1234-5678-1234-567812345678"
    assert claims["email"] == "a@example.com"
    # Cached: a second call must not need the database.
    assert neon_auth.verify_session_token("opaque-session-token", _FakeDb(None)) is not None


def test_verify_session_token_rejects_unverified():
    neon_auth._SESSION_CACHE.clear()
    row = {"user_id": "neon-user-2", "email": "b@example.com", "name": "B", "verified": False, "banned": False}
    assert neon_auth.verify_session_token("other-token", _FakeDb(row)) is None


def test_verify_accepts_origin_issuer_token(monkeypatch):
    monkeypatch.setattr(settings, "NEON_AUTH_BASE_URL", "https://auth.example.com/neondb/auth")
    monkeypatch.setattr(settings, "NEON_AUTH_JWKS_URL", "https://auth.example.com/jwks.json")
    key = Ed25519PrivateKey.generate()

    class _FakeJwksClient:
        def get_signing_key_from_jwt(self, token):
            class _Key:
                pass

            signing_key = _Key()
            signing_key.key = key.public_key()
            return signing_key

    monkeypatch.setattr(neon_auth, "_jwks_client", lambda: _FakeJwksClient())
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user-1", "iss": "https://auth.example.com", "iat": now, "exp": now + 600},
        key, algorithm="EdDSA",
    )
    claims = neon_auth.verify_neon_token(token)
    assert claims["sub"] == "user-1"
