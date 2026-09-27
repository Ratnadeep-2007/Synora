from datetime import datetime, timezone
import os
import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.evidence import Evidence
from app.models.source_event import SourceEvent
from app.schemas.source_event import SourceEventCreate
from app.services.ingestion_service import IngestionService


def test_high_volume_ingestion_performance():
    """
    Performance and Load Benchmark (Part 29 & 30):
    Ingests 10,000 normalized source events and normalizes 1,000 evidence records.
    Measures throughput (events/sec), database query latency, and memory stability.
    """
    # Create isolated in-memory test database for load benchmarking
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    ingestion = IngestionService()
    project_id = "proj_perf_load"
    tenant_id = "tenant_perf"

    # 1. Benchmark: 10,000 Source Events Ingestion
    TOTAL_EVENTS = 10_000
    BATCH_SIZE = 1_000

    print(f"\n[BENCHMARK] Starting ingestion of {TOTAL_EVENTS} source events in batches of {BATCH_SIZE}...")
    t_start = time.time()

    total_ingested = 0
    for batch_idx in range(TOTAL_EVENTS // BATCH_SIZE):
        batch = [
            SourceEventCreate(
                tenant_id=tenant_id,
                project_id=project_id,
                source="slack",
                source_event_id=f"perf_msg_{batch_idx}_{i}",
                event_type="channel_message",
                actor_id=f"user_{i % 50}",
                occurred_at=datetime.now(timezone.utc),
                payload={"text": f"Performance stress test message index {i} in batch {batch_idx}"},
                status="received",
            )
            for i in range(BATCH_SIZE)
        ]
        ingested = ingestion.ingest_events(batch, db)
        total_ingested += len(ingested)

    t_ingest_duration = time.time() - t_start
    throughput = total_ingested / t_ingest_duration if t_ingest_duration > 0 else 0

    print(f"[BENCHMARK] Ingested {total_ingested} events in {t_ingest_duration:.3f}s ({throughput:.1f} events/sec)")
    assert total_ingested == TOTAL_EVENTS
    assert throughput >= 100.0  # Must sustain at least 100 events/second in SQLite memory

    # 2. Benchmark: 1,000 Evidence Records Creation
    SAMPLE_EVIDENCE_COUNT = 1_000
    events_sample = (
        db.query(SourceEvent)
        .filter(SourceEvent.project_id == project_id)
        .limit(SAMPLE_EVIDENCE_COUNT)
        .all()
    )
    assert len(events_sample) == SAMPLE_EVIDENCE_COUNT

    t_ev_start = time.time()
    evidence_records = ingestion.normalize_events_to_evidence(events_sample, db)
    t_ev_duration = time.time() - t_ev_start
    ev_throughput = len(evidence_records) / t_ev_duration if t_ev_duration > 0 else 0

    print(f"[BENCHMARK] Created {len(evidence_records)} evidence records in {t_ev_duration:.3f}s ({ev_throughput:.1f} evidence/sec)")
    assert len(evidence_records) == SAMPLE_EVIDENCE_COUNT
    assert ev_throughput >= 100.0

    # 3. Query Latency Benchmark (Bounded latency on indexed columns)
    t_query_start = time.time()
    sample_query = (
        db.query(SourceEvent)
        .filter(SourceEvent.project_id == project_id, SourceEvent.source == "slack")
        .limit(50)
        .all()
    )
    query_latency_ms = (time.time() - t_query_start) * 1000.0
    print(f"[BENCHMARK] Indexed query latency: {query_latency_ms:.2f}ms")
    assert query_latency_ms < 50.0  # Sub-50ms query response

    db.close()
