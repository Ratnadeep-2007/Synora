import base64
import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.connectors.registry import registry
from app.connectors.slack import SlackConnector
from app.connectors.baileys import WhatsAppBaileysConnector
from app.core.config import settings
from app.core.rbac import Permission, enforce_permission
from app.models.evidence import Evidence
from app.models.source_event import SourceEvent
from app.models.user import User
from app.services.ingestion_service import IngestionService
from app.services.whatsapp_service import WhatsAppIntelligenceService
from app.services.whatsapp_export_parser import WhatsAppZipParser
from app.services.whatsapp_batch_service import WhatsAppBatchService
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors", tags=["Connectors"])
ingestion_service = IngestionService()
whatsapp_service = WhatsAppIntelligenceService()
whatsapp_batch_service = WhatsAppBatchService()


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

    # 3. Normalize & Ingest (casual chit-chat never reaches the platform).
    normalized_events = connector.handle_webhook(payload=payload, headers=headers)
    from app.services.context_intelligence import ContextIntelligenceService

    ingested_events = []
    ignored_casual = 0
    for event_in in normalized_events:
        _text = (event_in.payload or {}).get("text", "") if isinstance(event_in.payload, dict) else ""
        if ContextIntelligenceService.is_casual_chatter(_text):
            ignored_casual += 1
            metrics.increment("ingestion_events_total", labels={"source": "slack", "status": "ignored_casual"})
            continue
        ingested = ingestion_service.ingest_event(event_in, db)
        ingested_events.append(ingested.event_id)
        metrics.increment("ingestion_events_total", labels={"source": "slack"})

    return {
        "ok": True,
        "events_received": len(normalized_events),
        "ingested_event_ids": ingested_events,
        "ignored_casual": ignored_casual,
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
    from app.services.context_intelligence import ContextIntelligenceService as _Ctx

    ignored_casual = 0
    for event_in in fetch_result.events:
        _text = event_in.payload.get("text", "") if isinstance(event_in.payload, dict) else ""
        if _Ctx.is_casual_chatter(_text):
            ignored_casual += 1
            metrics.increment("ingestion_events_total", labels={"source": "slack", "status": "ignored_casual"})
            continue
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
        "ignored_casual": ignored_casual,
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


@router.post("/whatsapp/session-status", summary="Update WhatsApp Baileys Session Status")
def update_whatsapp_session_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Endpoint called by the Baileys daemon to report real connection updates
    (connected, disconnected, reconnecting) and active group counts.
    """
    connector: Optional[WhatsAppBaileysConnector] = registry.get("whatsapp")  # type: ignore
    if not connector:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="WhatsApp connector not registered.")

    session_id = payload.get("session_id", "default")
    status_str = payload.get("status", "disconnected")
    groups_count = payload.get("active_groups_count")
    connected_at = payload.get("connected_at")
    last_seen = payload.get("last_seen")
    details = payload.get("details")

    result = connector.update_session_status(
        session_id=session_id,
        status=status_str,
        active_groups_count=groups_count,
        connected_at=connected_at,
        last_seen=last_seen,
        details=details,
    )
    return {"ok": True, "session": result}


@router.post("/whatsapp/webhook", summary="WhatsApp Baileys Webhook Receiver")
async def whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Durable WhatsApp ingestion boundary.

    The webhook only persists messages into a one-minute processing window.
    AI/context/knowledge processing and the Excalidraw update happen in the
    dedicated batch worker, keeping the connector responsive and contextual.
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

    if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        messages = [m for m in payload["messages"] if isinstance(m, dict)]
    elif isinstance(payload, list):
        messages = [m for m in payload if isinstance(m, dict)]
    elif isinstance(payload, dict):
        messages = [payload]
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported WhatsApp payload.")

    queued = []
    duplicates = 0
    for message in messages:
        try:
            result = whatsapp_batch_service.enqueue_message(
                payload=message,
                db=db,
                tenant_id="default_tenant",
            )
            if result.get("duplicate"):
                duplicates += 1
            else:
                queued.append(result)
        except Exception as exc:
            logger.exception("Failed to enqueue WhatsApp message")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"WhatsApp batch queue error: {exc}",
            )

    primary_matched = None
    primary_confidence = None
    primary_reasoning = None
    for item in queued:
        if item.get("matched_project"):
            primary_matched = item["matched_project"]
            primary_confidence = item.get("confidence")
            primary_reasoning = item.get("reasoning")
            break

    response_data: Dict[str, Any] = {
        "ok": True,
        "status": "queued",
        "enqueued": len(queued),
        "duplicates": duplicates,
        "items": queued,
    }
    if primary_matched:
        response_data["matched_project"] = primary_matched
        response_data["confidence"] = primary_confidence
        response_data["reasoning"] = primary_reasoning

    return response_data


@router.post("/whatsapp/simulate", summary="Simulate WhatsApp Group Chat Message")
def simulate_whatsapp_message(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Enqueue a simulated WhatsApp message through the same production batching path."""
    if "text" not in payload or not str(payload["text"]).strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message 'text' is required.")

    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    result = whatsapp_batch_service.enqueue_message(
        payload=payload,
        db=db,
        tenant_id=tenant_id,
    )
    res_payload = {
        "ok": True,
        "processed": False,
        "status": "queued",
        "batch_id": result["batch_id"],
        "message_id": result["message_id"],
        "processing_interval_seconds": settings.WHATSAPP_PROCESSING_INTERVAL_SECONDS,
        "message": "Simulated WhatsApp message queued for batch processing.",
    }
    if result.get("matched_project"):
        res_payload["matched_project"] = result["matched_project"]
        res_payload["confidence"] = result.get("confidence")
        res_payload["reasoning"] = result.get("reasoning")
    return res_payload


@router.post("/whatsapp/process-batches", summary="Process Due WhatsApp Batches")
def process_whatsapp_batches(
    force: bool = Query(
        False,
        description="Process queued batches immediately, even before their 60-second window expires.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Manual reconciliation endpoint for local/admin testing of the batch worker."""
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    return whatsapp_batch_service.process_due_batches(
        db=db,
        tenant_id=tenant_id,
        force=force,
    )


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


@router.post("/whatsapp/import-export", summary="Import WhatsApp Chat Export Archive (.zip)")
async def import_whatsapp_export(
    file: UploadFile = File(..., description="WhatsApp exported chat .zip archive"),
    target_project: Optional[str] = Query(None, description="Optional target project ID (e.g. proj_default)"),
    limit: Optional[int] = Query(None, ge=1, le=2000, description="Optional limit of messages to process"),
    include_media: bool = Query(True, description="Process voice notes (Whisper) and diagram images (Vision)"),
    db: Session = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
) -> Dict[str, Any]:
    """
    Bulk imports an exported WhatsApp chat archive (.zip) into Synora.
    Extracts text messages, parses timestamps and speakers, attaches referenced
    audio notes / diagrams, passes them through Context Intelligence and Knowledge Extraction,
    and creates Living Workspace (Excalidraw) proposals for human review.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .zip WhatsApp export files are supported.",
        )

    try:
        content_bytes = await file.read()
        parser = WhatsAppZipParser(content_bytes)
        parsed_messages = parser.parse_messages()
    except Exception as exc:
        logger.error(f"Failed to parse WhatsApp export zip: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid WhatsApp export zip: {exc}",
        )

    total_parsed = len(parsed_messages)
    if limit and limit > 0:
        parsed_messages = parsed_messages[:limit]

    tenant_id = "default_tenant"
    if x_user_id:
        user = db.query(User).filter(User.id == x_user_id).first()
        if user and hasattr(user, "tenant_id") and user.tenant_id:
            tenant_id = user.tenant_id

    matched_count = 0
    unknown_count = 0
    proposals_count = 0
    audio_transcriptions = 0
    images_analyzed = 0

    group_name = file.filename.replace(".zip", "")
    if "WhatsApp Chat with " in group_name:
        group_name = group_name.replace("WhatsApp Chat with ", "")

    t_start = time.time()

    for idx, msg in enumerate(parsed_messages, 1):
        sender = msg["sender"]
        text = msg["text"]
        attachment = msg["attachment"]

        if target_project:
            text = f"[{target_project}] {text}"

        sender_jid = f"{re.sub(r'[^a-zA-Z0-9]', '', sender).lower() or 'user'}@s.whatsapp.net"
        # Deterministic id so re-importing the same archive is idempotent
        # (a time-based id would duplicate evidence on every upload).
        message_id = "wamid_export_" + hashlib.sha256(
            f"{group_name}|{sender}|{msg.get('raw_timestamp','')}|{msg['text']}".encode("utf-8")
        ).hexdigest()[:24]

        payload: Dict[str, Any] = {
            "message_id": message_id,
            "sender_jid": sender_jid,
            "sender_name": sender,
            "group_jid": "120363025812345678@g.us",
            "group_name": group_name,
            "text": text,
        }

        if include_media and attachment:
            raw_media = parser.read_attachment_bytes(attachment)
            if raw_media:
                b64 = base64.b64encode(raw_media).decode("utf-8")
                if attachment.lower().endswith((".opus", ".ogg", ".mp3", ".m4a")):
                    payload["audio_base64"] = b64
                    payload["media_type"] = "audio"
                    payload["filename"] = attachment
                elif attachment.lower().endswith((".jpg", ".png", ".jpeg", ".webp")):
                    payload["image_base64"] = b64
                    payload["media_type"] = "image"
                    payload["filename"] = attachment

        try:
            res = whatsapp_service.process_incoming_message(payload, db, tenant_id=tenant_id)
            if res.get("status") == "unknown_context":
                unknown_count += 1
            elif res.get("matched_project"):
                matched_count += 1
            if res.get("visual_proposal_pending"):
                proposals_count += 1

            # Count media only when it was actually processed (never on attempt),
            # so the report cannot claim transcription/vision that did not happen.
            multimodal = res.get("multimodal") or {}
            if (multimodal.get("audio_transcription") or {}).get("processed"):
                audio_transcriptions += 1
            if (multimodal.get("vision_analysis") or {}).get("processed"):
                images_analyzed += 1
        except Exception as exc:
            logger.warning(f"Error processing export message {idx}: {exc}")

    elapsed = time.time() - t_start

    return {
        "ok": True,
        "filename": file.filename,
        "total_in_archive": total_parsed,
        "processed_count": len(parsed_messages),
        "target_project": target_project,
        "matched_count": matched_count,
        "unknown_context_count": unknown_count,
        "visual_proposals_created": proposals_count,
        "audio_transcriptions": audio_transcriptions,
        "images_analyzed": images_analyzed,
        "elapsed_seconds": round(elapsed, 2),
    }


@router.post("/excalidraw/ingest", summary="Ingest Excalidraw Diagram via Unified Context Intelligence")
def ingest_excalidraw_connector(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from app.schemas.excalidraw import ExcalidrawIngestRequest
    from app.services.excalidraw_service import ExcalidrawService

    req = ExcalidrawIngestRequest(
        name=payload.get("name") or "Imported Architecture Diagram",
        elements=payload.get("elements") or [],
        app_state=payload.get("app_state") or {},
    )
    excal_service = ExcalidrawService()
    tenant = getattr(current_user, "tenant_id", None) or "default_tenant"
    actor = getattr(current_user, "email", None) or "user"
    return excal_service.ingest_unassociated_diagram(req, db, tenant_id=tenant, actor_id=actor)



