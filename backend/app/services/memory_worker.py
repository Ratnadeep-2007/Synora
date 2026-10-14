"""Standalone worker for installations that run canvas and memory separately."""
import asyncio
import logging
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.services.memory_jobs import MemoryJobWorker


async def run():
    init_db()
    worker = MemoryJobWorker()
    while True:
        try:
            with SessionLocal() as db:
                worker.process_batch(db, settings.MEMORY_JOBS_PER_TICK)
        except Exception:
            logging.exception("Memory worker tick failed")
        await asyncio.sleep(settings.MEMORY_JOB_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run())
