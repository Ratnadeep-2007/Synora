import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.whatsapp_batch import WhatsAppBatch, WhatsAppBatchItem

logger = logging.getLogger(__name__)


class WhatsAppBatchService:
    """Durable one-minute batching layer for live WhatsApp ingestion."""

    def enqueue_message(
        self,
        payload: Dict[str, Any],
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        message_id = str(
            payload.get("message_id")
            or payload.get("id")
            or f"wamid_{int(now.timestamp() * 1000)}"
        )
        group_jid = str(payload.get("group_jid") or "unknown@g.us")
        group_name = str(payload.get("group_name") or "WhatsApp Group")

        existing = (
            db.query(WhatsAppBatchItem)
            .filter(
                WhatsAppBatchItem.tenant_id == tenant_id,
                WhatsAppBatchItem.group_jid == group_jid,
                WhatsAppBatchItem.message_id == message_id,
            )
            .first()
        )
        if existing:
            return {
                "duplicate": True,
                "batch_id": existing.batch_id,
                "message_id": message_id,
            }

        batch = (
            db.query(WhatsAppBatch)
            .filter(
                WhatsAppBatch.tenant_id == tenant_id,
                WhatsAppBatch.group_jid == group_jid,
                WhatsAppBatch.status == "queued",
                WhatsAppBatch.due_at > now,
            )
            .order_by(WhatsAppBatch.created_at.desc())
            .first()
        )

        if batch is not None:
            queued_count = (
                db.query(WhatsAppBatchItem)
                .filter(
                    WhatsAppBatchItem.batch_id == batch.id,
                    WhatsAppBatchItem.status == "queued",
                )
                .count()
            )
            if queued_count >= settings.WHATSAPP_BATCH_MAX_MESSAGES:
                batch = None

        if batch is None:
            due_at = now + timedelta(
                seconds=settings.WHATSAPP_PROCESSING_INTERVAL_SECONDS
            )
            batch = WhatsAppBatch(
                tenant_id=tenant_id,
                group_jid=group_jid,
                group_name=group_name,
                status="queued",
                window_started_at=now,
                due_at=due_at,
            )
            db.add(batch)
            db.flush()

        item = WhatsAppBatchItem(
            batch_id=batch.id,
            tenant_id=tenant_id,
            group_jid=group_jid,
            message_id=message_id,
            payload_json=json.dumps(payload, default=str),
            received_at=now,
            status="queued",
        )
        db.add(item)
        db.commit()
        db.refresh(batch)

        # Pre-resolve project context so the ingestion log immediately reports which project is targeted
        matched_project = None
        confidence = None
        reasoning = None
        text = str(payload.get("text") or payload.get("caption") or "").strip()
        if text:
            try:
                from app.services.context_intelligence import ContextIntelligenceService
                from app.models.project import Project

                resolver = ContextIntelligenceService()
                res = resolver.resolve(
                    source="whatsapp",
                    payload=payload,
                    db=db,
                    tenant_id=tenant_id,
                    record=False,
                )
                if res.project_id:
                    proj = db.query(Project).filter(Project.id == res.project_id).first()
                    if proj:
                        matched_project = {"id": proj.id, "name": proj.name}
                        confidence = res.confidence
                        reasoning = res.reason
            except Exception as exc:
                logger.debug("WhatsApp enqueue project preview skipped: %s", exc)

        result_dict: Dict[str, Any] = {
            "duplicate": False,
            "batch_id": batch.id,
            "message_id": message_id,
            "due_at": batch.due_at.isoformat(),
            "group_jid": group_jid,
        }
        if matched_project:
            result_dict["matched_project"] = matched_project
            result_dict["confidence"] = confidence
            result_dict["reasoning"] = reasoning

        return result_dict

    def process_due_batches(
        self,
        db: Session,
        tenant_id: Optional[str] = None,
        force: bool = False,
        max_batches: int = 20,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        query = db.query(WhatsAppBatch).filter(WhatsAppBatch.status == "queued")
        if tenant_id:
            query = query.filter(WhatsAppBatch.tenant_id == tenant_id)
        if not force:
            query = query.filter(WhatsAppBatch.due_at <= now)

        batches = (
            query.order_by(WhatsAppBatch.due_at.asc())
            .limit(max_batches)
            .all()
        )

        processed = 0
        failed = 0
        summaries = []

        for batch in batches:
            batch.status = "processing"
            batch.attempts += 1
            batch.updated_at = datetime.now(timezone.utc)
            db.commit()

            items = (
                db.query(WhatsAppBatchItem)
                .filter(
                    WhatsAppBatchItem.batch_id == batch.id,
                    WhatsAppBatchItem.status == "queued",
                )
                .order_by(WhatsAppBatchItem.received_at.asc())
                .limit(settings.WHATSAPP_BATCH_MAX_MESSAGES)
                .all()
            )

            payloads: List[Dict[str, Any]] = []
            for item in items:
                try:
                    payloads.append(json.loads(item.payload_json))
                    item.status = "processing"
                except Exception as exc:
                    item.status = "failed"
                    item.error = str(exc)
            db.commit()

            try:
                from app.services.whatsapp_service import WhatsAppIntelligenceService

                result = WhatsAppIntelligenceService().process_incoming_batch(
                    payloads,
                    db=db,
                    tenant_id=batch.tenant_id,
                    batch_id=batch.id,
                )

                finished_at = datetime.now(timezone.utc)
                for item in items:
                    if item.status == "processing":
                        item.status = "completed"
                        item.processed_at = finished_at

                batch.status = "completed"
                batch.error = None
                batch.updated_at = finished_at
                db.commit()
                processed += 1
                summaries.append(result)

                # Explicitly log and report which projects were mapped and updated
                for r in result.get("results", []):
                    matched = r.get("matched_project")
                    if matched:
                        logger.info(
                            "🎯 [WhatsApp Batch %s] Message mapped to Project: %s (%s)",
                            batch.id,
                            matched.get("name"),
                            matched.get("id"),
                        )
                        print(
                            f"🎯 [WhatsApp Batch] Project Mapped: {matched.get('name')} ({matched.get('id')})"
                        )

                if result.get("visual_updates", 0) > 0:
                    for r in result.get("results", []):
                        matched = r.get("matched_project")
                        if matched:
                            logger.info(
                                "🎨 [WhatsApp Batch %s] Excalidraw updated for Project: %s (%s)",
                                batch.id,
                                matched.get("name"),
                                matched.get("id"),
                            )
                            print(
                                f"🎨 [WhatsApp Batch] Excalidraw updated for Project: {matched.get('name')} ({matched.get('id')})"
                            )
            except Exception as exc:
                failed += 1
                logger.exception("whatsapp_batch_failed batch=%s", batch.id)

                if batch.attempts >= settings.WHATSAPP_BATCH_MAX_RETRIES:
                    batch.status = "dead_letter"
                    batch.error = str(exc)
                    for item in items:
                        if item.status == "processing":
                            item.status = "failed"
                            item.error = str(exc)
                else:
                    batch.status = "queued"
                    batch.due_at = (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=settings.WHATSAPP_BATCH_RETRY_SECONDS)
                    )
                    batch.error = str(exc)
                    for item in items:
                        if item.status == "processing":
                            item.status = "queued"

                batch.updated_at = datetime.now(timezone.utc)
                db.commit()

        return {
            "ok": True,
            "processed_batches": processed,
            "failed_batches": failed,
            "batches": summaries,
            "next_poll_seconds": settings.WHATSAPP_BATCH_POLL_SECONDS,
        }
