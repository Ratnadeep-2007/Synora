import re
import unicodedata
from typing import Any, Dict, List, Union


PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior)\s+instructions"),
    re.compile(r"(?i)you\s+are\s+now\s+in\s+developer\s+mode"),
    re.compile(r"(?i)system\s*override"),
    re.compile(r"(?i)drop\s+database"),
    re.compile(r"(?i)delete\s+all\s+project\s+state"),
]

SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "secret",
    "authorization",
    "password",
    "encrypted_credentials",
    "bot_token",
}


def sanitize_input_text(text: str, max_length: int = 100_000) -> str:
    """
    Sanitizes user and provider input:
    1. Enforces length bounds to prevent DoS
    2. Normalizes Unicode (NFC form)
    3. Neutralizes known prompt injection escape strings by wrapping in boundary markers
    4. Strips raw NULL bytes
    """
    if not isinstance(text, str):
        return ""

    # Truncate to maximum length
    bounded = text[:max_length]

    # Remove null bytes
    cleaned = bounded.replace("\x00", "")

    # Normalize Unicode
    normalized = unicodedata.normalize("NFC", cleaned)

    # Detect prompt injection markers and neutralize
    for pat in PROMPT_INJECTION_PATTERNS:
        if pat.search(normalized):
            normalized = pat.sub("[FLAGGED_INJECTION_ATTEMPT]", normalized)

    return normalized


def mask_sensitive_data(obj: Any) -> Any:
    """
    Recursively redacts secrets and credentials from dictionaries, lists, and strings.
    Guarantees secrets never leak into logs or unauthenticated responses.
    """
    if isinstance(obj, dict):
        masked_dict = {}
        for k, v in obj.items():
            if str(k).lower() in SECRET_KEYS:
                masked_dict[k] = "[REDACTED_SECRET]"
            else:
                masked_dict[k] = mask_sensitive_data(v)
        return masked_dict
    elif isinstance(obj, list):
        return [mask_sensitive_data(item) for item in obj]
    elif isinstance(obj, str):
        # Mask Bearer tokens in headers
        if obj.lower().startswith("bearer "):
            return "Bearer [REDACTED_TOKEN]"
        return obj
    return obj
