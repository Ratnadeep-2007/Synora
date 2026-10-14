"""Dedicated 30-second memory-to-canvas worker for Synora."""

import asyncio
import logging
import time

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.services.visual_sync_service import VisualSyncService

logger = logging.getLogger(__name__)


async def run() -> None:
    init_db()
    service = VisualSyncService()
    interval = settings.VISUAL_SYNC_INTERVAL_SECONDS or 30
    from app.services.memory_jobs import MemoryJobWorker
    memory_worker = MemoryJobWorker()
    next_visual = 0.0
    while True:
        try:
            db = SessionLocal()
            try:
                if settings.MEMORY_WORKER_ENABLED:
                    memory_worker.process_batch(db, limit=settings.MEMORY_JOBS_PER_TICK)
                if time.monotonic() >= next_visual:
                    service.sync_all(db=db, actor_id="visual_sync_worker")
                    next_visual = time.monotonic() + interval
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Visual sync worker error: %s", exc, exc_info=True)
        await asyncio.sleep(min(interval, settings.MEMORY_JOB_INTERVAL_SECONDS))


if __name__ == "__main__":
    asyncio.run(run())
