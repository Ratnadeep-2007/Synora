from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base


def generate_source_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


class SourceEvent(Base):
    """
    Provider-independent raw event model representing an external interaction
    (e.g., spoken transcript entry, chat message, document edit).
    Decoupled from Google- or provider-specific structures.
    """
    __tablename__ = "source_events"

    event_id = Column(String(64), primary_key=True, default=generate_source_event_id)
    tenant_id = Column(String(64), default="tenant_default", index=True, nullable=False)
    project_id = Column(String(64), default="proj_default", index=True, nullable=False)
    source = Column(String(64), index=True, nullable=False)  # google_meet, slack, zoom, github, etc.
    source_event_id = Column(String(255), index=True, nullable=False)  # upstream provider unique ID
    event_type = Column(String(64), default="transcript_entry", nullable=False)  # transcript_entry, message, etc.
    actor_id = Column(String(255), nullable=True)  # speaker or actor identifier
    occurred_at = Column(DateTime(timezone=True), index=True, nullable=True)
    payload_json = Column(Text, nullable=False)  # normalized structured payload
    ingested_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    status = Column(String(32), default="received", nullable=False)  # received, processing, processed, failed
    error = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("project_id", "source", "source_event_id", name="uq_source_event_proj_source_id"),
        Index("ix_source_events_tenant_proj", "tenant_id", "project_id"),
        Index("ix_source_events_occurred", "occurred_at"),
    )

    def __repr__(self) -> str:
        return f"<SourceEvent id={self.event_id} source={self.source} type={self.event_type} status={self.status}>"
