from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, DateTime, Index, String, Text, UniqueConstraint

from app.core.database import Base


def generate_meet_event_id() -> str:
    return f"mev_{uuid.uuid4().hex[:12]}"


class MeetEventRecord(Base):
    """Durable record of a consumed Workspace Events transcript notification.

    Guarantees at-least-once Pub/Sub delivery never produces duplicate
    downstream work: retries look up this row by the stable provider event
    identifier before any retrieval or persistence runs.
    """

    __tablename__ = "meet_event_records"

    id = Column(String(64), primary_key=True, default=generate_meet_event_id)
    provider_event_id = Column(String(512), index=True, nullable=False)
    subscription_id = Column(String(64), index=True, nullable=True)
    workspace_id = Column(String(64), index=True, nullable=False, default="ws_default")
    project_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(64), index=True, nullable=False)
    event_type = Column(String(128), index=True, nullable=False)
    conference_record_id = Column(String(512), index=True, nullable=True)
    transcript_resource = Column(String(512), index=True, nullable=True)
    status = Column(String(32), default="received", index=True, nullable=False)
    attempts = Column(String(32), default="0", nullable=False)
    last_error = Column(Text, nullable=True)
    source_event_id = Column(String(64), nullable=True, index=True)
    meeting_id = Column(String(64), nullable=True, index=True)
    received_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    processed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("provider_event_id", name="uq_meet_event_provider_id"),
        Index("ix_meet_event_status_received", "status", "received_at"),
        Index("ix_meet_event_transcript", "transcript_resource"),
    )

    def __repr__(self) -> str:
        return (
            f"<MeetEventRecord id={self.id} provider_event={self.provider_event_id} "
            f"status={self.status}>"
        )
