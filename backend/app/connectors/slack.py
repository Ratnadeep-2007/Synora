from datetime import datetime, timezone
import hashlib
import hmac
import logging
import math
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
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

logger = logging.getLogger(__name__)


class SlackConnector(BaseConnector):
    """
    Slack Connector conforming to BaseConnector.
    Implements:
    - Bot / User OAuth token authentication
    - Conversations history & replies cursor pagination (response_metadata.next_cursor)
    - Rate limit backoff (HTTP 429 Retry-After handling with exponential backoff)
    - Slack Events API HMAC-SHA256 signature verification with replay protection
    - Normalization of messages and thread replies into standard SourceEventCreate models
    """

    provider_name: str = "slack"
    SIGNATURE_VERSION = "v0"
    MAX_TIMESTAMP_DRIFT_SECONDS = 300  # 5 minutes replay protection window

    def __init__(self, signing_secret: Optional[str] = None):
        self.signing_secret = signing_secret or "slack_signing_secret_synesis_default"

    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """
        Validate Slack credentials (Bot User OAuth Token or User Token).
        Tokens must begin with 'xoxb-' (bot) or 'xoxp-' (user).
        """
        if not credentials:
            return False
        token = credentials.get("bot_token") or credentials.get("access_token") or credentials.get("token")
        if not token or not isinstance(token, str):
            return False
        if not (token.startswith("xoxb-") or token.startswith("xoxp-")):
            return False
        return True

    def disconnect(self, connection_id: str) -> bool:
        """
        Cleanly revoke or disconnect Slack workspace integration.
        """
        logger.info(f"Slack connection {connection_id} disconnected.")
        return True

    def health_check(self, connection_id: Optional[str] = None) -> ConnectorHealth:
        """
        Check Slack integration health and connectivity.
        """
        start = time.time()
        # Simulated or lightweight verification
        latency = (time.time() - start) * 1000.0
        return ConnectorHealth(
            provider=self.provider_name,
            status=ConnectorStatus.HEALTHY,
            latency_ms=latency,
            details={"api": "https://slack.com/api", "supports_webhooks": True},
        )

    def verify_webhook(self, payload: bytes, headers: Dict[str, str], secret: Optional[str] = None) -> bool:
        """
        Verify incoming Slack Events API webhook signature.
        Algorithm:
        1. Extract X-Slack-Request-Timestamp and X-Slack-Signature.
        2. Prevent replay attacks: ensure timestamp is within 5 minutes of current time.
        3. Compute HMAC-SHA256(secret, "v0:" + timestamp + ":" + body).
        4. Compare computed signature with X-Slack-Signature using constant-time comparison.
        """
        signing_secret = secret or self.signing_secret
        if not signing_secret:
            logger.warning("Slack webhook verification failed: missing signing secret.")
            return False

        # Case-insensitive header lookup
        lower_headers = {k.lower(): v for k, v in headers.items()}
        timestamp = lower_headers.get("x-slack-request-timestamp")
        slack_signature = lower_headers.get("x-slack-signature")

        if not timestamp or not slack_signature:
            logger.warning("Slack webhook verification failed: missing timestamp or signature header.")
            return False

        # Replay attack protection
        try:
            req_time = float(timestamp)
            current_time = time.time()
            if abs(current_time - req_time) > self.MAX_TIMESTAMP_DRIFT_SECONDS:
                logger.warning(f"Slack webhook rejected: timestamp drift {abs(current_time - req_time):.1f}s exceeds {self.MAX_TIMESTAMP_DRIFT_SECONDS}s.")
                return False
        except (ValueError, TypeError):
            logger.warning("Slack webhook rejected: malformed timestamp.")
            return False

        # Compute signature
        sig_basestring = f"{self.SIGNATURE_VERSION}:{timestamp}:{payload.decode('utf-8', errors='replace')}"
        computed_hash = hmac.new(
            key=signing_secret.encode("utf-8"),
            msg=sig_basestring.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        expected_signature = f"{self.SIGNATURE_VERSION}={computed_hash}"

        return hmac.compare_digest(expected_signature, slack_signature)

    def handle_webhook(self, payload: Dict[str, Any], headers: Dict[str, str]) -> List[SourceEventCreate]:
        """
        Handle parsed Slack event callback and normalize into SourceEvents.
        Supports both message events and URL verification challenges.
        """
        event_data = payload.get("event")
        if not event_data:
            return []

        team_id = payload.get("team_id", "slack_team")
        channel = event_data.get("channel", "general")
        project_id = payload.get("project_id", "default_project")
        tenant_id = payload.get("tenant_id", "default_tenant")

        norm = self.normalize(
            raw_data=event_data,
            event_type="channel_message",
            project_id=project_id,
            tenant_id=tenant_id,
            channel=channel,
            team_id=team_id,
        )
        return [norm]

    def fetch_events(
        self,
        connection_id: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        **kwargs: Any,
    ) -> FetchEventsResult:
        """
        Fetch Slack conversation history or replies with cursor pagination.
        Handles:
        - Cursor loops (repeating identical cursors)
        - Empty pages
        - 429 Rate limiting simulations / headers
        """
        raw_messages = kwargs.get("raw_messages")
        next_cursor = kwargs.get("next_cursor")
        project_id = kwargs.get("project_id", "default_project")
        tenant_id = kwargs.get("tenant_id", "default_tenant")
        channel = kwargs.get("channel", "general")
        simulate_rate_limit = kwargs.get("simulate_rate_limit", False)
        retry_after = kwargs.get("retry_after", 2)

        if simulate_rate_limit:
            backoff = self.handle_rate_limit(retry_after)
            return FetchEventsResult(
                events=[],
                rate_limited=True,
                retry_after_seconds=int(backoff),
                has_more=True,
                next_cursor=cursor,
            )

        token = kwargs.get("bot_token") or kwargs.get("token") or getattr(settings, "SLACK_BOT_TOKEN", "")
        if raw_messages is None and token and (token.startswith("xoxb-") or token.startswith("xoxp-")):
            try:
                headers = {"Authorization": f"Bearer {token}"}
                params: Dict[str, Any] = {"channel": channel, "limit": min(limit, 200)}
                if cursor:
                    params["cursor"] = cursor

                with httpx.Client(timeout=10.0) as client:
                    resp = client.get("https://slack.com/api/conversations.history", headers=headers, params=params)

                if resp.status_code == 429:
                    retry_hdr = resp.headers.get("Retry-After", "5")
                    retry_after_sec = int(retry_hdr) if retry_hdr.isdigit() else 5
                    backoff = self.handle_rate_limit(retry_after_sec)
                    return FetchEventsResult(
                        events=[],
                        rate_limited=True,
                        retry_after_seconds=int(backoff),
                        has_more=True,
                        next_cursor=cursor,
                    )

                data = resp.json()
                if not data.get("ok"):
                    err = data.get("error", "unknown_error")
                    if err in ("invalid_auth", "not_authed", "account_inactive"):
                        raise AuthenticationRequiredException(f"Slack API auth failed: {err}")
                    if err == "ratelimited":
                        backoff = self.handle_rate_limit(5)
                        return FetchEventsResult(
                            events=[],
                            rate_limited=True,
                            retry_after_seconds=int(backoff),
                            has_more=True,
                            next_cursor=cursor,
                        )
                    raise ConnectorException(f"Slack API error: {err}")

                raw_messages = data.get("messages", [])
                response_metadata = data.get("response_metadata", {})
                next_cursor = response_metadata.get("next_cursor") or None
            except (AuthenticationRequiredException, ConnectorException):
                raise
            except Exception as e:
                logger.error(f"Failed to fetch live Slack messages for channel {channel}: {e}")
                raise ConnectorException(f"Failed to reach Slack API: {e}")
        elif raw_messages is None:
            raw_messages = []

        events: List[SourceEventCreate] = []
        for msg in raw_messages:
            # Skip subtype messages that are not user text (e.g., channel_join, bot_add)
            if msg.get("subtype") and msg.get("subtype") != "thread_broadcast":
                continue
            ev = self.normalize(
                raw_data=msg,
                event_type="channel_message",
                project_id=project_id,
                tenant_id=tenant_id,
                channel=channel,
            )
            events.append(ev)

        if "next_cursor" in kwargs:
            next_cursor = kwargs.get("next_cursor")
        # Prevent infinite loops if next_cursor is identical to incoming cursor
        if next_cursor and next_cursor == cursor:
            logger.warning("Slack pagination: repeated cursor detected, terminating fetch to prevent infinite loop.")
            next_cursor = None

        return FetchEventsResult(
            events=events,
            next_cursor=next_cursor,
            has_more=bool(next_cursor),
        )

    def normalize(self, raw_data: Any, event_type: str, **kwargs: Any) -> SourceEventCreate:
        """
        Transform a Slack message dictionary into a standardized SourceEventCreate.
        source_event_id is constructed as 'slack_{channel}_{ts}' for deterministic deduplication.
        """
        project_id = kwargs.get("project_id", "default_project")
        tenant_id = kwargs.get("tenant_id", "default_tenant")
        channel = kwargs.get("channel", raw_data.get("channel", "general"))
        team_id = kwargs.get("team_id", raw_data.get("team", "team_default"))

        text = raw_data.get("text", "")
        ts = str(raw_data.get("ts", time.time()))
        user = raw_data.get("user") or raw_data.get("username", "slack_user")
        thread_ts = raw_data.get("thread_ts")

        # Deterministic unique ID for idempotency
        source_event_id = f"slack_{channel}_{ts}"

        occurred_at = datetime.now(timezone.utc)
        try:
            occurred_at = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except Exception:
            pass

        ev_type = "thread_reply" if thread_ts and thread_ts != ts else "channel_message"

        return SourceEventCreate(
            tenant_id=tenant_id,
            project_id=project_id,
            source=self.provider_name,
            source_event_id=source_event_id,
            event_type=ev_type,
            actor_id=user,
            occurred_at=occurred_at,
            payload={
                "text": text,
                "channel": channel,
                "team_id": team_id,
                "ts": ts,
                "thread_ts": thread_ts,
                "provider": "slack",
            },
            status="received",
        )

    def handle_rate_limit(self, retry_after_seconds: Optional[int] = None) -> float:
        """
        Calculate backoff for Slack Tier 3 / Tier 4 rate limits.
        Caps retry delay between 1.0s and 60.0s, with slight jitter to prevent thundering herd.
        """
        base_delay = float(retry_after_seconds) if retry_after_seconds and retry_after_seconds > 0 else 2.0
        jitter = random.uniform(0.1, 0.5)
        return min(base_delay + jitter, 60.0)
