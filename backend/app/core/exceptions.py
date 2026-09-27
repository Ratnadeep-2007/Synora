"""Custom exceptions for Synesis OAuth, Authentication, and Google Meet integration."""

class SynesisException(Exception):
    """Base exception for Synesis application."""
    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or message


class ConfigurationError(SynesisException):
    """Raised when required environment or configuration variables are missing or invalid."""
    pass


class InvalidOAuthStateException(SynesisException):
    """Raised when an OAuth state token is missing, tampered, expired, or invalid."""
    pass


class OAuthAccessDeniedError(SynesisException):
    """Raised when the user denies authorization on the OAuth consent screen."""
    pass


class GoogleOAuthError(SynesisException):
    """Raised when an error occurs while communicating with Google OAuth APIs."""
    def __init__(self, message: str, error_code: str | None = None, status_code: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code


class CredentialsExpiredError(SynesisException):
    """Raised when stored credentials are expired and cannot be refreshed."""
    pass


class ConnectionNotFoundError(SynesisException):
    """Raised when a requested source connection does not exist."""
    pass


# ==============================================================================
# Google Meet API Exceptions (Phase 2)
# ==============================================================================

class GoogleMeetError(SynesisException):
    """Base exception for Google Meet API operations."""
    def __init__(self, message: str, status_code: int = 400, error_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class GoogleMeetPermissionError(GoogleMeetError):
    """Raised when Google returns 403 Forbidden (insufficient permissions/scopes)."""
    def __init__(self, message: str = "Insufficient permissions to access Google Meet resource."):
        super().__init__(message, status_code=403, error_code="permission_denied")


class GoogleMeetResourceNotFoundError(GoogleMeetError):
    """Raised when Google returns 404 (conference, participant, or transcript not found)."""
    def __init__(self, message: str = "Google Meet resource was not found."):
        super().__init__(message, status_code=404, error_code="not_found")


class GoogleMeetRateLimitError(GoogleMeetError):
    """Raised when Google returns 429 Too Many Requests."""
    def __init__(self, message: str = "Google Meet API rate limit exceeded.", retry_after: int | None = None):
        super().__init__(message, status_code=429, error_code="rate_limit_exceeded")
        self.retry_after = retry_after


class GoogleMeetTransientError(GoogleMeetError):
    """Raised when Google returns 5xx or a network timeout occurs."""
    def __init__(self, message: str = "Temporary Google Meet API service error."):
        super().__init__(message, status_code=502, error_code="service_unavailable")


class TranscriptUnavailableError(SynesisException):
    """Raised when a conference exists but no transcript is available or still processing."""
    pass
