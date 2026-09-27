import hashlib
import hmac
import time
import pytest
from sqlalchemy.orm import Session

from app.connectors.base import (
    BaseConnector,
    ConnectorHealth,
    ConnectorStatus,
    FetchEventsResult,
)
from app.connectors.google_meet import GoogleMeetConnector
from app.connectors.registry import ConnectorRegistry, registry
from app.connectors.slack import SlackConnector
from app.models.source_event import SourceEvent
from app.models.evidence import Evidence
from app.services.ingestion_service import IngestionService


def test_connector_registry_registration():
    """Verify registry registers, retrieves, and lists connectors."""
    reg = ConnectorRegistry()
    meet = GoogleMeetConnector()
    slack = SlackConnector()

    reg.register(meet)
    reg.register(slack)

    assert "google_meet" in reg.list_providers()
    assert "slack" in reg.list_providers()
    assert reg.get("google_meet") is meet
    assert reg.get("slack") is slack
    assert reg.get("unknown_provider") is None


def test_connector_registry_health_checks():
    """Verify registry can check health across all registered connectors."""
    reg = ConnectorRegistry()
    meet = GoogleMeetConnector()
    slack = SlackConnector()
    reg.register(meet)
    reg.register(slack)

    health_map = reg.check_all_health()
    assert "google_meet" in health_map
    assert "slack" in health_map
    assert health_map["slack"].status == ConnectorStatus.HEALTHY
    assert health_map["slack"].latency_ms >= 0


def test_google_meet_connector_authenticate_and_normalize():
    """Verify Google Meet connector authentication check and normalization."""
    connector = GoogleMeetConnector()

    # Authenticate check
    assert connector.authenticate({"access_token": "ya29.valid_test_token"}) is True
    assert connector.authenticate({}) is False
    assert connector.authenticate({"token": ""}) is False

    # Normalization check
    raw_entry = {
        "name": "spaces/123/transcripts/t1/entries/e1",
        "text": "We should deploy our services using Docker and Kubernetes.",
        "languageCode": "en-US",
        "speaker": "Engineering Lead",
    }
    event = connector.normalize(
        raw_data=raw_entry,
        event_type="transcript_entry",
        project_id="proj_alpha",
        tenant_id="tenant_1",
        conference_id="conf_999",
    )

    assert event.source == "google_meet"
    assert event.source_event_id == "spaces/123/transcripts/t1/entries/e1"
    assert event.actor_id == "Engineering Lead"
    assert event.project_id == "proj_alpha"
    assert event.payload["text"] == "We should deploy our services using Docker and Kubernetes."
    assert event.payload["conference_id"] == "conf_999"


def test_slack_connector_authentication():
    """Verify Slack bot and user token validation."""
    connector = SlackConnector()

    assert connector.authenticate({"bot_token": "xoxb-12345-67890-abcdef"}) is True
    assert connector.authenticate({"access_token": "xoxp-98765-43210-fedcba"}) is True
    assert connector.authenticate({"token": "invalid-token-prefix"}) is False
    assert connector.authenticate({}) is False


def test_slack_connector_normalization():
    """Verify Slack message payload normalizes to standard SourceEventCreate."""
    connector = SlackConnector()
    raw_msg = {
        "text": "Let's standardize on PostgreSQL for all relational data storage.",
        "user": "U12345678",
        "ts": "1710000000.123456",
        "channel": "C98765432",
        "team": "T001",
    }

    event = connector.normalize(
        raw_data=raw_msg,
        event_type="channel_message",
        project_id="proj_slack",
        tenant_id="tenant_slack",
    )

    assert event.source == "slack"
    assert event.source_event_id == "slack_C98765432_1710000000.123456"
    assert event.actor_id == "U12345678"
    assert event.event_type == "channel_message"
    assert event.payload["channel"] == "C98765432"
    assert event.payload["text"] == "Let's standardize on PostgreSQL for all relational data storage."


def test_slack_connector_pagination():
    """Verify cursor-based pagination and loop prevention."""
    connector = SlackConnector()

    messages_page_1 = [
        {"text": "Msg 1", "user": "U1", "ts": "100.1", "channel": "C1"},
        {"text": "Msg 2", "user": "U2", "ts": "100.2", "channel": "C1"},
    ]

    res1 = connector.fetch_events(
        connection_id="conn_slack",
        cursor=None,
        raw_messages=messages_page_1,
        next_cursor="cursor_page_2",
    )

    assert len(res1.events) == 2
    assert res1.next_cursor == "cursor_page_2"
    assert res1.has_more is True

    # Test loop detection: if provider repeats identical cursor, connector breaks loop
    res2 = connector.fetch_events(
        connection_id="conn_slack",
        cursor="cursor_page_2",
        raw_messages=[],
        next_cursor="cursor_page_2",  # Provider bug: returning same cursor
    )
    assert res2.next_cursor is None
    assert res2.has_more is False


def test_slack_connector_rate_limiting():
    """Verify rate limit detection and bounded backoff calculation."""
    connector = SlackConnector()

    # Calculate backoff with explicit Retry-After
    delay = connector.handle_rate_limit(retry_after_seconds=5)
    assert 5.0 <= delay <= 5.5

    # Capped at 60s
    max_delay = connector.handle_rate_limit(retry_after_seconds=120)
    assert max_delay <= 60.0

    # Fetch result with rate limit flag
    res = connector.fetch_events(
        connection_id="conn_slack",
        simulate_rate_limit=True,
        retry_after=10,
    )
    assert res.rate_limited is True
    assert res.retry_after_seconds >= 10


def test_slack_webhook_hmac_verification():
    """Verify Slack HMAC-SHA256 signature verification and replay defense."""
    secret = "test_signing_secret_12345"
    connector = SlackConnector(signing_secret=secret)

    now = time.time()
    body = b'{"type":"event_callback","event":{"type":"message","text":"Approved architecture change"}}'
    timestamp_str = str(int(now))

    # Compute valid signature
    sig_basestring = f"v0:{timestamp_str}:{body.decode('utf-8')}"
    valid_hash = hmac.new(
        key=secret.encode("utf-8"),
        msg=sig_basestring.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    valid_signature = f"v0={valid_hash}"

    valid_headers = {
        "X-Slack-Request-Timestamp": timestamp_str,
        "X-Slack-Signature": valid_signature,
    }

    # 1. Valid signature passes
    assert connector.verify_webhook(payload=body, headers=valid_headers) is True

    # 2. Forged signature fails
    forged_headers = {
        "X-Slack-Request-Timestamp": timestamp_str,
        "X-Slack-Signature": "v0=invalid_forged_signature_hex",
    }
    assert connector.verify_webhook(payload=body, headers=forged_headers) is False

    # 3. Replay attack: timestamp older than 300 seconds fails
    old_timestamp_str = str(int(now - 305))
    old_basestring = f"v0:{old_timestamp_str}:{body.decode('utf-8')}"
    old_hash = hmac.new(
        key=secret.encode("utf-8"),
        msg=old_basestring.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    replay_headers = {
        "X-Slack-Request-Timestamp": old_timestamp_str,
        "X-Slack-Signature": f"v0={old_hash}",
    }
    assert connector.verify_webhook(payload=body, headers=replay_headers) is False


def test_connector_idempotency_duplicate_delivery(db_session: Session):
    """Verify duplicate event delivery produces only one logical event and evidence."""
    ingestion = IngestionService()
    connector = SlackConnector()

    raw_msg = {
        "text": "Decision confirmed: We will use Redis for session caching.",
        "user": "U_ARCH",
        "ts": "1715000000.000100",
        "channel": "C_DEV",
    }

    event_in_1 = connector.normalize(raw_msg, event_type="channel_message", project_id="proj_idemp")
    event_in_2 = connector.normalize(raw_msg, event_type="channel_message", project_id="proj_idemp")

    # Ingest duplicate deliveries
    ev1 = ingestion.ingest_event(event_in_1, db_session)
    ev2 = ingestion.ingest_event(event_in_2, db_session)

    # Must return the same database record
    assert ev1.event_id == ev2.event_id

    # Count database records
    count = (
        db_session.query(SourceEvent)
        .filter(
            SourceEvent.project_id == "proj_idemp",
            SourceEvent.source_event_id == event_in_1.source_event_id,
        )
        .count()
    )
    assert count == 1

    # Create evidence
    evidence1 = ingestion.create_evidence_from_event(ev1, db_session, content="Redis caching confirmed")
    evidence2 = ingestion.create_evidence_from_event(ev2, db_session, content="Redis caching confirmed")
    assert evidence1.id == evidence2.id

    evidence_count = (
        db_session.query(Evidence)
        .filter(Evidence.project_id == "proj_idemp", Evidence.source_event_id == ev1.event_id)
        .count()
    )
    assert evidence_count == 1

