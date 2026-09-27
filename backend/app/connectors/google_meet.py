from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional

from app.connectors.base import (
    BaseConnector,
    ConnectorHealth,
    ConnectorStatus,
    FetchEventsResult,
    RateLimitException,
    AuthenticationRequiredException,
    ConnectorException,
)
from app.core.config import settings
from app.schemas.source_event import SourceEventCreate
from app.services.google_meet import GoogleMeetService
from app.core.exceptions import GoogleMeetError

logger = logging.getLogger(__name__)


class GoogleMeetConnector(BaseConnector):
    """
    Google Meet Connector conforming to the provider-independent BaseConnector contract.
    Wraps GoogleMeetService for OAuth token validation, conference transcript discovery,
    cursor pagination, and normalization into standard SourceEvents.
    """

    provider_name: str = "google_meet"

    def __init__(self, service: Optional[GoogleMeetService] = None):
        self.service = service or GoogleMeetService()

    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """
        Validate Google OAuth credentials by checking required token fields.
        """
        if not credentials:
            return False
        access_token = credentials.get("access_token") or credentials.get("token")
        if not access_token:
            return False
        return True

    def disconnect(self, connection_id: str) -> bool:
        """
        Mark connection as disconnected.
        """
        logger.info(f"Google Meet connection {connection_id} disconnected.")
        return True

    def health_check(self, connection_id: Optional[str] = None) -> ConnectorHealth:
        """
        Check Google Meet API readiness and OAuth configuration.
        """
        start = time.time()
        configured = settings.is_google_oauth_configured
        latency = (time.time() - start) * 1000.0

        if not configured:
            return ConnectorHealth(
                provider=self.provider_name,
                status=ConnectorStatus.DEGRADED,
                latency_ms=latency,
                error_message="Google OAuth credentials are not fully configured in environment.",
                details={"configured": False, "redirect_uri": settings.GOOGLE_REDIRECT_URI},
            )

        return ConnectorHealth(
            provider=self.provider_name,
            status=ConnectorStatus.HEALTHY,
            latency_ms=latency,
            details={"configured": True, "redirect_uri": settings.GOOGLE_REDIRECT_URI},
        )

    def fetch_events(
        self,
        connection_id: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        **kwargs: Any,
    ) -> FetchEventsResult:
        """
        Fetch transcript events using pagination token (cursor).
        Keyword args may supply conference_id or raw entries directly.
        """
        entries = kwargs.get("entries", [])
        project_id = kwargs.get("project_id", "default_project")
        tenant_id = kwargs.get("tenant_id", "default_tenant")
        conference_id = kwargs.get("conference_id", "conf_unknown")

        events: List[SourceEventCreate] = []
        for entry in entries:
            ev = self.normalize(
                entry,
                event_type="transcript_entry",
                project_id=project_id,
                tenant_id=tenant_id,
                conference_id=conference_id,
            )
            events.append(ev)

        next_cursor = kwargs.get("next_page_token")
        return FetchEventsResult(
            events=events,
            next_cursor=next_cursor,
            has_more=bool(next_cursor),
        )

    def normalize(self, raw_data: Any, event_type: str, **kwargs: Any) -> SourceEventCreate:
        """
        Transform a Google Meet transcript entry dictionary into a standard SourceEventCreate.
        """
        project_id = kwargs.get("project_id", "default_project")
        tenant_id = kwargs.get("tenant_id", "default_tenant")
        conference_id = kwargs.get("conference_id", "conf_unknown")

        # Handle both dict and object structures
        if isinstance(raw_data, dict):
            entry_id = raw_data.get("name") or raw_data.get("provider_entry_id") or raw_data.get("id") or "entry_unknown"
            text = raw_data.get("text", "")
            language_code = raw_data.get("languageCode") or raw_data.get("language_code", "en-US")
            start_time_raw = raw_data.get("startTime") or raw_data.get("start_time")
            actor = raw_data.get("speaker") or raw_data.get("participant", "Unknown Speaker")
        else:
            entry_id = getattr(raw_data, "provider_entry_id", getattr(raw_data, "id", "entry_unknown"))
            text = getattr(raw_data, "text", "")
            language_code = getattr(raw_data, "language_code", "en-US")
            start_time_raw = getattr(raw_data, "start_time", None)
            actor = getattr(raw_data, "speaker", "Unknown Speaker")

        occurred_at = datetime.now(timezone.utc)
        if isinstance(start_time_raw, datetime):
            occurred_at = start_time_raw
        elif isinstance(start_time_raw, str):
            try:
                occurred_at = datetime.fromisoformat(start_time_raw.replace("Z", "+00:00"))
            except Exception:
                pass

        return SourceEventCreate(
            tenant_id=tenant_id,
            project_id=project_id,
            source=self.provider_name,
            source_event_id=entry_id,
            event_type=event_type,
            actor_id=str(actor),
            occurred_at=occurred_at,
            payload={
                "text": text,
                "language_code": language_code,
                "conference_id": conference_id,
                "provider": "google_meet",
            },
            status="received",
        )
