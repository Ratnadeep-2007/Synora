from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.source_event import SourceEventCreate


class ConnectorStatus(str, Enum):
    CONNECTED = "connected"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    AUTHENTICATION_REQUIRED = "authentication_required"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ConnectorHealth(BaseModel):
    provider: str
    status: ConnectorStatus
    latency_ms: float = 0.0
    error_message: Optional[str] = None
    last_checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = Field(default_factory=dict)


class FetchEventsResult(BaseModel):
    events: List[SourceEventCreate] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: bool = False
    rate_limited: bool = False
    retry_after_seconds: Optional[int] = None


class ConnectorException(Exception):
    """Base exception for connector errors."""
    def __init__(self, message: str, provider: str, error_code: Optional[str] = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.provider = provider
        self.error_code = error_code
        self.retry_after = retry_after


class RateLimitException(ConnectorException):
    """Raised when an external provider responds with HTTP 429."""
    pass


class AuthenticationRequiredException(ConnectorException):
    """Raised when credentials are expired, revoked, or missing."""
    pass


class BaseConnector(ABC):
    """
    Provider-independent connector contract for all Synesis external sources.
    
    Distinguishes:
    - AUTHENTICATION: Validating credentials and obtaining tokens
    - CONNECTION: Lifecycle management (connect, disconnect)
    - DATA DISCOVERY: Fetching events via pagination/cursor
    - EVENT INGESTION: Ingesting raw events
    - NORMALIZATION: Converting provider payload to standard SourceEventCreate
    - HEALTH: Reporting real-time integration status
    """

    provider_name: str = "base"

    @abstractmethod
    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """Validate credentials against the provider."""
        pass

    @abstractmethod
    def disconnect(self, connection_id: str) -> bool:
        """Cleanly revoke or disconnect an integration."""
        pass

    @abstractmethod
    def health_check(self, connection_id: Optional[str] = None) -> ConnectorHealth:
        """Check provider connectivity, responsiveness, and credential validity."""
        pass

    @abstractmethod
    def fetch_events(
        self,
        connection_id: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        **kwargs: Any,
    ) -> FetchEventsResult:
        """Fetch external events using cursor-based pagination."""
        pass

    @abstractmethod
    def normalize(self, raw_data: Any, event_type: str, **kwargs: Any) -> SourceEventCreate:
        """Transform provider-specific payload into standard SourceEventCreate."""
        pass

    def verify_webhook(self, payload: bytes, headers: Dict[str, str], secret: str) -> bool:
        """
        Verify incoming webhook authenticity using provider signature format.
        Default implementation returns False if not overridden.
        """
        return False

    def handle_webhook(self, payload: Dict[str, Any], headers: Dict[str, str]) -> List[SourceEventCreate]:
        """Parse and normalize incoming webhook payload into SourceEvents."""
        return []

    def handle_rate_limit(self, retry_after_seconds: Optional[int] = None) -> float:
        """
        Calculate bounded backoff delay.
        Default: retry_after or exponential backoff capped at 60 seconds.
        """
        if retry_after_seconds is not None and retry_after_seconds > 0:
            return min(float(retry_after_seconds), 60.0)
        return 5.0

    def handle_error(self, exc: Exception) -> ConnectorException:
        """Map generic exception to standard ConnectorException."""
        if isinstance(exc, ConnectorException):
            return exc
        return ConnectorException(message=str(exc), provider=self.provider_name)
