from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.task_job import JobStatus, TaskJob
from app.services.metrics import metrics

logger = logging.getLogger(__name__)


class TaskJobError(SynesisException):
    pass


class TaskService:
    """
    Service managing background tasks, bounded retry execution, crash recovery,
    and dead-letter queue (DLQ) handling.
    """

    def submit_job(
        self,
        job_type: str,
        payload: Dict[str, Any],
        db: Session,
        tenant_id: str = "default_tenant",
        project_id: Optional[str] = None,
        max_retries: int = 3,
    ) -> TaskJob:
        """
        Enqueues a new background job with unique ID and initial pending state.
        """
        job = TaskJob(
            job_type=job_type,
            tenant_id=tenant_id,
            project_id=project_id,
            status=JobStatus.PENDING.value,
            payload_json=json.dumps(payload),
            max_retries=max_retries,
            retry_count=0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        metrics.increment("processing_jobs_total", labels={"type": job_type, "status": "submitted"})
        logger.info(f"Submitted TaskJob '{job.id}' of type '{job_type}' for tenant '{tenant_id}'.")
        return job

    def execute_job(
        self,
        job_id: str,
        worker_func: Callable[[Dict[str, Any]], Dict[str, Any]],
        db: Session,
    ) -> TaskJob:
        """
        Executes a background job with bounded retry behavior.
        If execution fails and retries are exhausted, moves the job into DEAD_LETTER.
        """
        job = db.query(TaskJob).filter(TaskJob.id == job_id).first()
        if not job:
            raise TaskJobError(f"Job '{job_id}' not found.")

        # Transition to RUNNING
        job.status = JobStatus.RUNNING.value
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        payload = {}
        try:
            payload = json.loads(job.payload_json) if job.payload_json else {}
        except Exception:
            pass

        try:
            result = worker_func(payload)
            job.status = JobStatus.COMPLETED.value
            job.result_json = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = None
            db.commit()
            db.refresh(job)
            metrics.increment("processing_jobs_total", labels={"type": job.job_type, "status": "completed"})
            logger.info(f"TaskJob '{job.id}' completed successfully.")
            return job
        except Exception as exc:
            job.retry_count += 1
            job.error_message = str(exc)
            job.updated_at = datetime.now(timezone.utc)

            metrics.increment("processing_failures_total", labels={"type": job.job_type})

            if job.retry_count >= job.max_retries:
                # Retries exhausted -> Move to Dead-Letter Queue
                job.status = JobStatus.DEAD_LETTER.value
                logger.error(
                    f"TaskJob '{job.id}' exhausted all {job.max_retries} retries! "
                    f"Moved to DEAD-LETTER QUEUE. Error: {exc}"
                )
            else:
                job.status = JobStatus.FAILED.value
                logger.warning(
                    f"TaskJob '{job.id}' attempt {job.retry_count}/{job.max_retries} failed. "
                    f"Ready for bounded retry. Error: {exc}"
                )

            db.commit()
            db.refresh(job)
            return job

    def recover_crashed_jobs(self, db: Session, max_age_seconds: int = 300) -> List[TaskJob]:
        """
        Recovers jobs left in 'RUNNING' status following a worker crash or unexpected restart.
        Resets them to 'PENDING' if retries remain, or 'DEAD_LETTER' if exhausted.
        """
        now = datetime.now(timezone.utc)
        running_jobs = db.query(TaskJob).filter(TaskJob.status == JobStatus.RUNNING.value).all()
        recovered: List[TaskJob] = []

        for job in running_jobs:
            if job.updated_at:
                job_time = job.updated_at.replace(tzinfo=timezone.utc) if job.updated_at.tzinfo is None else job.updated_at
                elapsed = (now - job_time).total_seconds()
            else:
                elapsed = 9999

            if elapsed >= max_age_seconds:
                if job.retry_count >= job.max_retries:
                    job.status = JobStatus.DEAD_LETTER.value
                    job.error_message = "Recovered after crash: retries exhausted."
                else:
                    job.status = JobStatus.PENDING.value
                    job.error_message = "Recovered from ungraceful worker termination, re-queued."
                job.updated_at = now
                recovered.append(job)

        db.commit()
        logger.info(f"Crash recovery check: reset {len(recovered)} ungracefully terminated jobs.")
        return recovered

    def get_dead_letter_jobs(
        self,
        db: Session,
        tenant_id: Optional[str] = None,
    ) -> List[TaskJob]:
        """
        Fetch all jobs currently resting in the Dead-Letter Queue.
        """
        query = db.query(TaskJob).filter(TaskJob.status == JobStatus.DEAD_LETTER.value)
        if tenant_id:
            query = query.filter(TaskJob.tenant_id == tenant_id)
        return query.order_by(TaskJob.updated_at.desc()).all()

    def replay_dead_letter_job(self, job_id: str, db: Session) -> TaskJob:
        """
        Resets a dead-letter job for manual operator replay.
        """
        job = db.query(TaskJob).filter(TaskJob.id == job_id).first()
        if not job:
            raise TaskJobError(f"Job '{job_id}' not found.")
        if job.status != JobStatus.DEAD_LETTER.value:
            raise TaskJobError(f"Job '{job_id}' is not in dead_letter status (current: {job.status}).")

        job.status = JobStatus.PENDING.value
        job.retry_count = 0
        job.error_message = None
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        logger.info(f"Operator replayed dead-letter job '{job.id}'. Reset to PENDING.")
        return job
