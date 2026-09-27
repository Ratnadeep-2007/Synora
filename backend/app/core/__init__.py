"""Core module containing config, database, security, and exceptions."""
from app.core.config import settings
from app.core.exceptions import (
    ConfigurationError,
    InvalidOAuthStateException,
    OAuthAccessDeniedError,
    GoogleOAuthError,
    CredentialsExpiredError,
    ConnectionNotFoundError,
    GoogleMeetError,
    GoogleMeetPermissionError,
    GoogleMeetResourceNotFoundError,
    GoogleMeetRateLimitError,
    GoogleMeetTransientError,
    TranscriptUnavailableError,
)

__all__ = [
    "settings",
    "ConfigurationError",
    "InvalidOAuthStateException",
    "OAuthAccessDeniedError",
    "GoogleOAuthError",
    "CredentialsExpiredError",
    "ConnectionNotFoundError",
    "GoogleMeetError",
    "GoogleMeetPermissionError",
    "GoogleMeetResourceNotFoundError",
    "GoogleMeetRateLimitError",
    "GoogleMeetTransientError",
    "TranscriptUnavailableError",
]
