from app.connectors.base import (
    BaseConnector,
    ConnectorHealth,
    ConnectorStatus,
    FetchEventsResult,
    ConnectorException,
    RateLimitException,
    AuthenticationRequiredException,
)
from app.connectors.google_meet import GoogleMeetConnector
from app.connectors.slack import SlackConnector
from app.connectors.excalidraw import ExcalidrawConnector
from app.connectors.baileys import WhatsAppBaileysConnector
from app.connectors.registry import ConnectorRegistry, registry
from app.core.config import settings

# Register standard connectors (Google Meet, Slack, Excalidraw, WhatsApp Baileys)
registry.register(GoogleMeetConnector())
registry.register(SlackConnector(signing_secret=settings.SLACK_SIGNING_SECRET))
registry.register(ExcalidrawConnector())
registry.register(WhatsAppBaileysConnector())

__all__ = [
    "BaseConnector",
    "ConnectorHealth",
    "ConnectorStatus",
    "FetchEventsResult",
    "ConnectorException",
    "RateLimitException",
    "AuthenticationRequiredException",
    "GoogleMeetConnector",
    "SlackConnector",
    "ExcalidrawConnector",
    "WhatsAppBaileysConnector",
    "ConnectorRegistry",
    "registry",
]
