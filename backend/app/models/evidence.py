from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex[:12]}"


class Evidence(Base):
    """
    Immutable evidence record representing the exact ground-truth source artifact
    backing an extracted fact, proposal, requirement, or decision.
    Answers the core user question: "Why does Synesis believe this?"
    """
    __tablename__ = "evidence"

    id = Column(String(64), primary_key=True, default=generate_evidence_id)
    project_id = Column(String(64), index=True, nullable=False)
    source = Column(String(64), index=True, nullable=False)  # google_meet, slack, document, etc.
    source_event_id = Column(String(64), ForeignKey("source_events.event_id", ondelete="CASCADE"), index=True, nullable=False)
    meeting_id = Column(String(64), ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True, index=True)
    transcript_id = Column(String(64), ForeignKey("transcripts.id", ondelete="SET NULL"), nullable=True, index=True)
    transcript_entry_id = Column(String(64), ForeignKey("transcript_entries.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_id = Column(String(255), nullable=True)  # Speaker name or ID
    occurred_at = Column(DateTime(timezone=True), index=True, nullable=True)
    content = Column(Text, nullable=False)  # Verbatim speech utterance or text fragment
    metadata_json = Column(Text, nullable=True)  # Context: speaker title, surrounding dialogue, confidence
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    source_event = relationship("SourceEvent")
    meeting = relationship("Meeting")
    transcript_entry = relationship("TranscriptEntry")

    __table_args__ = (
        Index("ix_evidence_project_occurred", "project_id", "occurred_at"),
        Index("ix_evidence_source_meeting", "source", "meeting_id"),
    )

    def __repr__(self) -> str:
        return f"<Evidence id={self.id} source={self.source} actor={self.actor_id} meeting={self.meeting_id}>"
