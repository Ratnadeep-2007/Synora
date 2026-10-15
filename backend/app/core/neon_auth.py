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
