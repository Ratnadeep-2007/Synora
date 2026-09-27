from datetime import datetime, timezone
from enum import Enum
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    Index,
)

from app.core.database import Base


def generate_job_id() -> str:
    return f"job_{uuid.uuid4().hex[:12]}"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class TaskJob(Base):
    """
    Persistent background job entity supporting bounded retries and dead-letter queue (DLQ).
    Ensures that background tasks (e.g., connector sync, event ingestion, intelligence)
    have explicit execution states, bounded retries, and failure visibility.
    """
    __tablename__ = "task_jobs"

    id = Column(String(64), primary_key=True, default=generate_job_id)
    tenant_id = Column(String(64), index=True, nullable=False, default="default_tenant")
    project_id = Column(String(64), index=True, nullable=True)
    job_type = Column(String(64), index=True, nullable=False)
    status = Column(String(32), index=True, default=JobStatus.PENDING.value, nullable=False)
    payload_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_task_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_task_jobs_type_status", "job_type", "status"),
    )

    def __repr__(self) -> str:
        return f"<TaskJob id={self.id} type={self.job_type} status={self.status} retries={self.retry_count}/{self.max_retries}>"
