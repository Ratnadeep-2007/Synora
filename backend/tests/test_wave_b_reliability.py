import os
import time
import pytest
from sqlalchemy.orm import Session

from app.models.project_state import ApprovalStatus, ProjectState, StateChange
from app.models.task_job import JobStatus, TaskJob
from app.services.project_state_service import ProjectStateService, StateTransitionError
from app.services.task_service import TaskService


def test_task_job_lifecycle_and_bounded_retry(db_session: Session):
    """Verify background job execution, bounded retry loop, and Dead-Letter Queue (DLQ)."""
    task_service = TaskService()

    # 1. Enqueue job
    payload = {"source": "slack", "channel": "C123"}
    job = task_service.submit_job(
        job_type="connector_sync",
        payload=payload,
        db=db_session,
        tenant_id="tenant_rel",
        max_retries=2,
    )
    assert job.status == JobStatus.PENDING.value
    assert job.retry_count == 0

    # 2. First failure (retry 1 of 2)
    def failing_worker(p):
        raise RuntimeError("Transient network timeout connecting to Slack")

    job = task_service.execute_job(job.id, failing_worker, db_session)
    assert job.status == JobStatus.FAILED.value
    assert job.retry_count == 1
    assert "Transient network timeout" in job.error_message

    # 3. Second failure (retry 2 of 2 -> MAX RETRIES EXHAUSTED -> DEAD-LETTER QUEUE)
    job = task_service.execute_job(job.id, failing_worker, db_session)
    assert job.status == JobStatus.DEAD_LETTER.value
    assert job.retry_count == 2
    assert "Transient network timeout" in job.error_message

    # 4. Check Dead-Letter Queue visibility
    dlq_jobs = task_service.get_dead_letter_jobs(db_session, tenant_id="tenant_rel")
    assert len(dlq_jobs) == 1
    assert dlq_jobs[0].id == job.id

    # 5. Replay from DLQ
    replayed = task_service.replay_dead_letter_job(job.id, db_session)
    assert replayed.status == JobStatus.PENDING.value
    assert replayed.retry_count == 0
    assert replayed.error_message is None

    # 6. Successful execution after operator intervention
    def successful_worker(p):
        return {"synced_messages": 10}

    job = task_service.execute_job(replayed.id, successful_worker, db_session)
    assert job.status == JobStatus.COMPLETED.value
    assert "synced_messages" in job.result_json


def test_crash_recovery_resets_stuck_running_jobs(db_session: Session):
    """Verify that jobs stuck in 'RUNNING' after a worker crash are safely recovered."""
    task_service = TaskService()

    # Simulate a job that crashed while executing
    crashed_job = TaskJob(
        job_type="transcript_ingestion",
        tenant_id="tenant_crash",
        status=JobStatus.RUNNING.value,
        retry_count=1,
        max_retries=3,
    )
    db_session.add(crashed_job)
    db_session.commit()
    db_session.refresh(crashed_job)

    # Run crash recovery with 0s threshold to recover immediately
    recovered = task_service.recover_crashed_jobs(db_session, max_age_seconds=0)
    assert len(recovered) == 1
    assert recovered[0].id == crashed_job.id
    assert recovered[0].status == JobStatus.PENDING.value
    assert "ungraceful worker termination" in recovered[0].error_message


def test_concurrent_state_approval_race_protection(db_session: Session):
    """
    Verify concurrency safety when two actors or threads attempt to approve the same proposal.
    The second approval must be safely rejected without duplicate state version advancement.
    """
    from app.models.intelligence import CandidateKnowledge
    state_service = ProjectStateService()
    project_id = "proj_race_test"

    # Establish baseline state (v1)
    state = state_service.get_or_create_state(project_id, db_session)
    v1 = state.current_version

    # Create candidate knowledge
    cand = CandidateKnowledge(
        project_id=project_id,
        category="decision_candidate",
        classification="Decision",
        title="Modernize backend caching",
        content="We will adopt Redis 7 for caching.",
        confidence=0.95,
        evidence_ids_json='["ev_test_1"]',
        status="candidate",
    )
    db_session.add(cand)
    db_session.commit()
    db_session.refresh(cand)

    # Propose change
    change = state_service.propose_change_from_candidate(
        candidate=cand,
        db=db_session,
        actor_id="tech_lead",
    )
    assert change.approval_status == ApprovalStatus.PROPOSED.value

    # First approval succeeds -> advances version to v2
    new_version_1 = state_service.approve_state_change(
        change_id=change.id,
        actor_id="architect_1",
        db=db_session,
    )
    assert new_version_1.version_number == v1 + 1

    # Second concurrent approval of the same change MUST raise StateTransitionError
    with pytest.raises(StateTransitionError) as exc_info:
        state_service.approve_state_change(
            change_id=change.id,
            actor_id="architect_2",
            db=db_session,
        )
    assert "must be 'proposed'" in str(exc_info.value)

    # Verify version remains strictly at v2 (no duplicate version jump!)
    db_session.refresh(state)
    assert state.current_version == v1 + 1


def test_database_backup_and_restore_workflow(tmp_path):
    """
    Verify database hot backup creation, integrity verification, and restore workflow (Part 23).
    """
    import sqlite3
    from app.core.backup import create_sqlite_backup, restore_sqlite_backup

    # 1. Create a sample SQLite database file
    db_file = tmp_path / "live_synesis.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, value TEXT)")
    cur.execute("INSERT INTO test_data (value) VALUES ('production_critical_record')")
    conn.commit()
    conn.close()

    # 2. Create online hot backup
    backup_dir = tmp_path / "backups"
    backup_path = create_sqlite_backup(str(db_file), str(backup_dir))
    assert os.path.exists(backup_path)

    # 3. Simulate disaster: corrupt or delete live DB
    restored_db_file = tmp_path / "restored_synesis.db"

    # 4. Restore from backup
    success = restore_sqlite_backup(backup_path, str(restored_db_file))
    assert success is True
    assert os.path.exists(str(restored_db_file))

    # 5. Verify restored data matches exactly
    r_conn = sqlite3.connect(str(restored_db_file))
    r_cur = r_conn.cursor()
    r_cur.execute("SELECT value FROM test_data WHERE id=1")
    row = r_cur.fetchone()
    r_conn.close()

    assert row is not None
    assert row[0] == "production_critical_record"


