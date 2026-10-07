"""Dedicated 30-second memory-to-canvas worker for Synora."""

import asyncio
import logging

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.services.visual_sync_service import VisualSyncService

logger = logging.getLogger(__name__)


async def run() -> None:
    init_db()
    service = VisualSyncService()
    interval = settings.VISUAL_SYNC_INTERVAL_SECONDS or 30
    while True:
        try:
            db = SessionLocal()
            try:
                service.sync_all(db=db, actor_id="visual_sync_worker")
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Visual sync worker error: %s", exc, exc_info=True)
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run())
