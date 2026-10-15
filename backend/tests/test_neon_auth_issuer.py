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
