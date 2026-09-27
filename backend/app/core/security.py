import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.core.exceptions import InvalidOAuthStateException

OAUTH_NONCE_COOKIE_NAME = "synesis_oauth_nonce"


def _b64url_encode(data: bytes) -> str:
    """Encode bytes to URL-safe base64 string without trailing padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    """Decode URL-safe base64 string with missing padding restored."""
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def _sign(message: bytes, key: str) -> str:
    """Compute HMAC-SHA256 signature encoded as url-safe base64."""
    mac = hmac.new(key.encode("utf-8"), message, hashlib.sha256)
    return _b64url_encode(mac.digest())


class OAuthStateManager:
    """
    CSRF-safe OAuth state generator and validator.
    Uses cryptographically random nonces, signed payloads, and expiration checks.
    """

    @classmethod
    def generate_state(
        cls,
        user_id: str,
        return_to: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        expire_seconds: Optional[int] = None,
    ) -> Tuple[str, str]:
        """
        Generate a tamper-proof signed state parameter and a raw nonce for cookie storage.
        
        Returns:
            Tuple of (signed_state_string, raw_nonce)
        """
        nonce = secrets.token_urlsafe(32)
        ttl = expire_seconds if expire_seconds is not None else settings.OAUTH_STATE_EXPIRE_SECONDS
        now = int(time.time())

        payload = {
            "nonce": nonce,
            "user_id": user_id,
            "return_to": return_to or "",
            "iat": now,
            "exp": now + ttl,
        }
        if extra:
            payload["extra"] = extra

        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = _b64url_encode(payload_bytes)
        signature = _sign(payload_bytes, settings.SECRET_KEY)

        state_token = f"{payload_b64}.{signature}"
        return state_token, nonce

    @classmethod
    def verify_state(
        cls,
        state: Optional[str],
        cookie_nonce: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verify the signature, expiration, and optional cookie nonce of an OAuth state string.

        Raises:
            InvalidOAuthStateException if validation fails.
        """
        if not state:
            raise InvalidOAuthStateException("OAuth state parameter is missing.")

        parts = state.split(".")
        if len(parts) != 2:
            raise InvalidOAuthStateException("Invalid OAuth state structure.")

        payload_b64, signature = parts[0], parts[1]

        try:
            payload_bytes = _b64url_decode(payload_b64)
        except Exception as exc:
            raise InvalidOAuthStateException(f"Failed to decode OAuth state payload: {exc}") from exc

        # 1. Verify HMAC signature in constant time before parsing JSON
        expected_signature = _sign(payload_bytes, settings.SECRET_KEY)
        if not hmac.compare_digest(signature, expected_signature):
            raise InvalidOAuthStateException("OAuth state signature verification failed. Possible CSRF attack.")

        # 2. Parse JSON payload
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception as exc:
            raise InvalidOAuthStateException(f"Failed to parse OAuth state payload: {exc}") from exc

        # 3. Verify timestamp expiration
        exp = payload.get("exp")
        if not exp or not isinstance(exp, (int, float)):
            raise InvalidOAuthStateException("OAuth state missing expiration timestamp.")
        if time.time() > exp:
            raise InvalidOAuthStateException("OAuth state has expired. Please initiate the authorization request again.")

        # 4. Verify double-submit cookie nonce if provided
        expected_nonce = payload.get("nonce")
        if cookie_nonce is not None:
            if not hmac.compare_digest(cookie_nonce, expected_nonce):
                raise InvalidOAuthStateException("OAuth state nonce does not match session cookie.")

        return payload
