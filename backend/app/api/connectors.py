import json
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.connectors.registry import registry
from app.connectors.slack import SlackConnector
from app.connectors.baileys import WhatsAppBaileysConnector
from app.core.rbac import Permission, enforce_permission
from app.models.evidence import Evidence
from app.models.source_event import SourceEvent
from app.models.user import User
from app.services.ingestion_service import IngestionService
from app.services.whatsapp_service import WhatsAppIntelligenceService
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors", tags=["Connectors"])
ingestion_service = IngestionService()
whatsapp_service = WhatsAppIntelligenceService()


@router.get("", summary="List All External Connectors and Status")
def list_connectors() -> List[Dict[str, Any]]:
    """
    Returns all registered external source connectors and real-time health.
    """
    health_map = registry.check_all_health()
    results = []
    for provider in registry.list_providers():
        health = health_map.get(provider)
        results.append({
            "provider": provider,
            "status": health.status.value if health else "unknown",
            "latency_ms": health.latency_ms if health else 0.0,
            "error": health.error_message if health else None,
            "details": health.details if health else {},
        })
    return results


@router.post("/slack/events", summary="Slack Events API Webhook Receiver")
async def slack_events_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_slack_signature: Optional[str] = Header(None),
    x_slack_request_timestamp: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """
    Slack Events API webhook endpoint.
    1. Verifies HMAC-SHA256 signature and validates timestamp against replay attacks
    2. Handles Slack url_verification challenge
    3. Normalizes message events into standard SourceEvents
    4. Idempotently ingests events into the database
    """
    raw_body = await request.body()
    headers = dict(request.headers)

    connector: Optional[SlackConnector] = registry.get("slack")  # type: ignore
    if not connector:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Slack connector not registered.")

    # 1. Signature Verification
    is_valid = connector.verify_webhook(payload=raw_body, headers=headers)
    if not is_valid:
        metrics.increment("connector_api_errors_total", labels={"provider": "slack", "error": "invalid_signature"})
        logger.warning("Rejected unauthenticated Slack webhook: invalid signature or expired timestamp.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Slack webhook signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Malformed JSON: {exc}")

    # 2. URL Verification Challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    # 3. Normalize & Ingest
    normalized_events = connector.handle_webhook(payload=payload, headers=headers)
    ingested_events = []
    for event_in in normalized_events:
        ingested = ingestion_service.ingest_event(event_in, db)
        ingested_events.append(ingested.event_id)
        metrics.increment("ingestion_events_total", labels={"source": "slack"})

    return {
        "ok": True,
        "events_received": len(normalized_events),
        "ingested_event_ids": ingested_events,
    }


@router.post("/slack/sync", summary="Synchronize Slack Channel Messages")
def sync_slack_channel(
    channel: str = Query(..., description="Slack Channel ID (e.g. C012345678)"),
    project_id: str = Query("proj_default", description="Associated Synesis Project ID"),
    cursor: Optional[str] = Query(None, description="Optional pagination cursor"),
    limit: int = Query(50, ge=1, le=200, description="Max messages to fetch"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Fetches real conversation history from a Slack channel using the Bot OAuth Token,
    normalizes all messages into SourceEvents, and ingests them into the Project Evidence store.
    """
    connector: Optional[SlackConnector] = registry.get("slack")  # type: ignore
    if not connector:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Slack connector not registered.")

    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    try:
        fetch_result = connector.fetch_events(
            connection_id="slack_default",
            cursor=cursor,
            limit=limit,
            channel=channel,
            project_id=project_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error(f"Slack channel sync failed: {exc}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    ingested_events = []
    for event_in in fetch_result.events:
        ingested = ingestion_service.ingest_event(event_in, db)
        ingested_events.append(ingested.event_id)
        ingestion_service.create_evidence_from_event(
            event=ingested,
            db=db,
            content=f"Slack [{channel}] {event_in.actor_id}: {event_in.payload.get('text', '')}",
            metadata={"channel": channel, "slack_ts": event_in.payload.get("ts")},
        )
        metrics.increment("ingestion_events_total", labels={"source": "slack"})

    return {
        "ok": True,
        "channel": channel,
        "messages_fetched": len(fetch_result.events),
        "ingested_event_ids": ingested_events,
        "has_more": fetch_result.has_more,
        "next_cursor": fetch_result.next_cursor,
    }


# =========================================================================
# WHATSAPP BAILEYS GROUP CHAT CONNECTOR ENDPOINTS
# =========================================================================

@router.get("/whatsapp/status", summary="WhatsApp Baileys Integration Status")
def get_whatsapp_status(
    connection_id: Optional[str] = Query(None, description="Optional connection/session ID"),
) -> Dict[str, Any]:
    """
    Returns real-time health, connection state, and active groups for the WhatsApp Baileys connector.
    """
    connector: Optional[WhatsAppBaileysConnector] = registry.get("whatsapp")  # type: ignore
    if not connector:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="WhatsApp connector not registered.")

    health = connector.health_check(connection_id)
    return {
        "provider": "whatsapp",
        "status": health.status.value,
        "latency_ms": health.latency_ms,
        "details": health.details,
    }


@router.post("/whatsapp/webhook", summary="WhatsApp Baileys Webhook Receiver")
async def whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Webhook endpoint called by the Baileys daemon when a new WhatsApp group message is received.
    Automatically:
    1. Understands which project people are talking about across the workspace portfolio.
    2. Ingests the message as immutable Evidence.
    3. Extracts candidate decisions / requirements.
    4. Applies visual updates directly to the target project's Excalidraw whiteboard!
    """
    raw_body = await request.body()
    headers = dict(request.headers)

    connector: Optional[WhatsAppBaileysConnector] = registry.get("whatsapp")  # type: ignore
    if not connector:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="WhatsApp connector not registered.")

    if not connector.verify_webhook(payload=raw_body, headers=headers):
        logger.warning("Rejected unauthenticated WhatsApp webhook.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid WhatsApp webhook authentication.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Malformed JSON: {exc}")

    if isinstance(payload, list):
        results = [whatsapp_service.process_incoming_message(msg, db) for msg in payload]
        return {"ok": True, "count": len(results), "results": results}
    elif isinstance(payload, dict) and "messages" in payload and isinstance(payload["messages"], list):
        results = [whatsapp_service.process_incoming_message(msg, db) for msg in payload["messages"]]
        return {"ok": True, "count": len(results), "results": results}
    else:
        result = whatsapp_service.process_incoming_message(payload, db)
        return result


@router.post("/whatsapp/simulate", summary="Simulate WhatsApp Group Chat Message")
def simulate_whatsapp_message(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Simulates receiving a WhatsApp group chat message.
    Used for testing autonomous project understanding and real-time Excalidraw whiteboard updates.
    """
    if "text" not in payload or not str(payload["text"]).strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message 'text' is required.")

    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    result = whatsapp_service.process_incoming_message(payload, db, tenant_id=tenant_id)
    metrics.increment("ingestion_events_total", labels={"source": "whatsapp"})
    return result


@router.get("/whatsapp/history", summary="Recent WhatsApp Ingested Messages")
def get_whatsapp_history(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    limit: int = Query(20, ge=1, le=100, description="Max messages to fetch"),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Retrieves recent WhatsApp group chat messages ingested across the workspace,
    showing which project each message was classified to.
    """
    query = (
        db.query(Evidence)
        .join(SourceEvent, Evidence.source_event_id == SourceEvent.event_id)
        .filter(SourceEvent.source == "whatsapp")
    )

    if project_id:
        query = query.filter(Evidence.project_id == project_id)

    records = query.order_by(Evidence.created_at.desc()).limit(limit).all()
    results = []
    for ev in records:
        meta = json.loads(ev.metadata_json) if ev.metadata_json else {}
        results.append({
            "id": ev.id,
            "project_id": ev.project_id,
            "content": ev.content,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
            "group_name": meta.get("group_name", "WhatsApp Group"),
            "sender_jid": meta.get("sender_jid"),
            "confidence": meta.get("confidence", 1.0),
            "reasoning": meta.get("reasoning"),
        })
    return results


