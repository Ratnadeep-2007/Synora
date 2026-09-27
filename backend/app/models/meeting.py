from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_meeting_id() -> str:
    return f"mtg_{uuid.uuid4().hex[:12]}"


def generate_participant_id() -> str:
    return f"part_{uuid.uuid4().hex[:12]}"


def generate_transcript_id() -> str:
    return f"trsc_{uuid.uuid4().hex[:12]}"


def generate_transcript_entry_id() -> str:
    return f"tent_{uuid.uuid4().hex[:12]}"


class Meeting(Base):
    """
    Internal domain model representing a synchronized meeting / conference record.
    Decoupled from Google-specific response payloads.
    """
    __tablename__ = "meetings"

    id = Column(String(64), primary_key=True, default=generate_meeting_id)
    workspace_id = Column(String(64), default="ws_default", index=True, nullable=False)
    project_id = Column(String(64), default="proj_default", index=True, nullable=False)
    source_connection_id = Column(String(64), nullable=True, index=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    provider = Column(String(64), default="google", index=True, nullable=False)
    provider_conference_id = Column(String(255), index=True, nullable=False)
    meeting_space_id = Column(String(255), nullable=True)
    title = Column(String(255), nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), default="ENDED", nullable=False)
    metadata_json = Column(Text, nullable=True)
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

    # Relationships
    user = relationship("User")
    participants = relationship("Participant", back_populates="meeting", cascade="all, delete-orphan")
    transcripts = relationship("Transcript", back_populates="meeting", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("provider", "provider_conference_id", name="uq_meeting_provider_conf_id"),
        Index("ix_meetings_user_provider", "user_id", "provider"),
    )

    def __repr__(self) -> str:
        return f"<Meeting id={self.id} provider={self.provider} conf={self.provider_conference_id}>"


class Participant(Base):
    """
    Internal domain model representing a participant in a meeting.
    """
    __tablename__ = "participants"

    id = Column(String(64), primary_key=True, default=generate_participant_id)
    meeting_id = Column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=False)
    provider_participant_id = Column(String(255), index=True, nullable=False)
    display_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    metadata_json = Column(Text, nullable=True)
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

    # Relationships
    meeting = relationship("Meeting", back_populates="participants")
    entries = relationship("TranscriptEntry", back_populates="participant")

    __table_args__ = (
        UniqueConstraint("meeting_id", "provider_participant_id", name="uq_participant_meeting_provider_id"),
    )

    def __repr__(self) -> str:
        return f"<Participant id={self.id} name={self.display_name} meeting={self.meeting_id}>"


class Transcript(Base):
    """
    Internal domain model representing a transcript resource associated with a meeting.
    """
    __tablename__ = "transcripts"

    id = Column(String(64), primary_key=True, default=generate_transcript_id)
    meeting_id = Column(String(64), ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=False)
    provider = Column(String(64), default="google", index=True, nullable=False)
    provider_transcript_id = Column(String(255), index=True, nullable=False)
    state = Column(String(64), default="AVAILABLE", nullable=False)  # AVAILABLE, NOT_AVAILABLE, STARTED, ENDED
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    docs_destination_url = Column(String(1024), nullable=True)
    metadata_json = Column(Text, nullable=True)
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

    # Relationships
    meeting = relationship("Meeting", back_populates="transcripts")
    entries = relationship("TranscriptEntry", back_populates="transcript", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("provider", "provider_transcript_id", name="uq_transcript_provider_trsc_id"),
    )

    def __repr__(self) -> str:
        return f"<Transcript id={self.id} meeting={self.meeting_id} state={self.state}>"


class TranscriptEntry(Base):
    """
    Internal domain model representing an individual spoken utterance within a transcript.
    Maintains structured speech segment, speaker association, and timing.
    """
    __tablename__ = "transcript_entries"

    id = Column(String(64), primary_key=True, default=generate_transcript_entry_id)
    transcript_id = Column(String(64), ForeignKey("transcripts.id", ondelete="CASCADE"), index=True, nullable=False)
    provider = Column(String(64), default="google", index=True, nullable=False)
    provider_entry_id = Column(String(255), index=True, nullable=False)
    participant_id = Column(String(64), ForeignKey("participants.id", ondelete="SET NULL"), nullable=True, index=True)
    text = Column(Text, nullable=False)
    language_code = Column(String(32), default="en-US", nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(Text, nullable=True)
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

    # Relationships
    transcript = relationship("Transcript", back_populates="entries")
    participant = relationship("Participant", back_populates="entries")

    __table_args__ = (
        UniqueConstraint("transcript_id", "provider_entry_id", name="uq_entry_transcript_provider_entry_id"),
        Index("ix_entries_transcript_start_time", "transcript_id", "start_time"),
    )

    def __repr__(self) -> str:
        return f"<TranscriptEntry id={self.id} transcript={self.transcript_id} text={self.text[:20]}...>"
