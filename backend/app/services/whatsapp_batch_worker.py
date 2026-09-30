"""Dedicated durable WhatsApp batch worker."""

import logging
import time

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.services.whatsapp_batch_service import WhatsAppBatchService

logger = logging.getLogger(__name__)


def run_forever() -> None:
    # Keep the dedicated worker safe when it starts independently from the API.
    # This also reconciles the legacy SQLite WhatsApp batch schema.
    init_db()
    service = WhatsAppBatchService()
    logger.info(
        "whatsapp_batch_worker_started interval=%ss poll=%ss",
        settings.WHATSAPP_PROCESSING_INTERVAL_SECONDS,
        settings.WHATSAPP_BATCH_POLL_SECONDS,
    )
    while True:
        db = SessionLocal()
        try:
            service.process_due_batches(db=db)
        except Exception:
            logger.exception("whatsapp_batch_worker_cycle_failed")
        finally:
            db.close()
        time.sleep(settings.WHATSAPP_BATCH_POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
