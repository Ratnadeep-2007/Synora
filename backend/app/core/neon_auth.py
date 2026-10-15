"""Validate short-lived Neon Auth tokens before accessing Synora APIs."""

from functools import lru_cache
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient

from app.core.config import settings


def expected_issuer() -> str:
    """Issuer Neon Auth actually puts in its JWTs.

    Tokens are issued by the auth origin (scheme + host), NOT by the full
    API base URL: a token minted via ".../neondb/auth" carries
    iss="https://<host>". Verifying against the full base URL rejected
    every genuine login token with 401.
    """
    base = (settings.NEON_AUTH_BASE_URL or "").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return base


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    if not settings.NEON_AUTH_JWKS_URL:
        raise ValueError("NEON_AUTH_JWKS_URL is required when authentication is enabled")
    return PyJWKClient(settings.NEON_AUTH_JWKS_URL, cache_jwk_set=True, lifespan=300)


import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

_SESSION_CACHE: dict = {}
_SESSION_CACHE_TTL_SECONDS = 30


def verify_session_token(token: str, db) -> Optional[dict]:
    """Validate an opaque Better Auth session token against the DB.

    Fallback for browsers that block the cross-domain Neon Auth cookie on
    XHR: the SPA then cannot mint a JWT via /token, but it does hold the
    session token from getSession(). The token is the credential itself
    (same trust as the session cookie); we resolve it against
    neon_auth.session joined to neon_auth.user. Results are cached for
    30s per token hash to bound database hits.
    """
    if not token:
        return None
    cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cached = _SESSION_CACHE.get(cache_key)
    if cached and cached[1] > time.time():
        return cached[0]
    from sqlalchemy import text

    row = db.execute(
        text(
            'SELECT s."userId" AS user_id, u.email AS email, u.name AS name, '
            'u."emailVerified" AS verified, u.banned AS banned '
            'FROM neon_auth.session s JOIN neon_auth."user" u ON u.id = s."userId" '
            'WHERE s.token = :token AND s."expiresAt" > :now'
        ),
        {"token": token, "now": datetime.now(timezone.utc)},
    ).mappings().first()
    if not row or not row["verified"] or row["banned"]:
        return None
    claims = {
        "sub": row["user_id"],
        "email": row["email"],
        "name": row["name"],
        "emailVerified": True,
        "banned": False,
    }
    _SESSION_CACHE[cache_key] = (claims, time.time() + _SESSION_CACHE_TTL_SECONDS)
    return claims


def verify_neon_token(token: str) -> dict:
    """Return verified claims; the caller handles invalid-token errors."""
    if not settings.NEON_AUTH_BASE_URL:
        raise ValueError("NEON_AUTH_BASE_URL is required when authentication is enabled")
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["EdDSA"],
        issuer=expected_issuer(),
        options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
        leeway=30,
    )
    if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
        raise jwt.InvalidTokenError("Missing subject")
    return claims
