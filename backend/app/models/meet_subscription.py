from datetime import datetime, timezone
from enum import Enum
import uuid
from sqlalchemy import Column, DateTime, Index, String, Text, UniqueConstraint

from app.core.database import Base


def generate_subscription_id() -> str:
    return f"msub_{uuid.uuid4().hex[:12]}"


class MeetSubscriptionStatus(str, Enum):
    ACTIVE = "active"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    FAILED = "failed"
    SUSPENDED = "suspended"


class MeetSubscriptionTarget(str, Enum):
    MEETING_SPACE = "meeting_space"
    USER = "user"


class MeetSubscription(Base):
    """Google Workspace Events subscription for Meet transcript notifications.

    A subscription is notification infrastructure only: it tells Synesis
    *when* a transcript artifact becomes available. The actual transcript
    content is always retrieved through the Google Meet REST API.
    """

    __tablename__ = "meet_subscriptions"

    id = Column(String(64), primary_key=True, default=generate_subscription_id)
    workspace_id = Column(String(64), index=True, nullable=False, default="ws_default")
    project_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(64), index=True, nullable=False)
    provider = Column(String(64), default="google_meet", index=True, nullable=False)
    source_connection_id = Column(String(64), index=True, nullable=True)
    target_resource = Column(String(512), nullable=False)
    target_type = Column(String(32), nullable=False, default=MeetSubscriptionTarget.MEETING_SPACE.value)
    subscription_name = Column(String(512), nullable=True, index=True)
    event_types = Column(Text, nullable=False)
    pubsub_topic = Column(String(512), nullable=True)
    status = Column(String(32), default=MeetSubscriptionStatus.ACTIVE.value, index=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)
    renewed_at = Column(DateTime(timezone=True), nullable=True)
    last_event_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "target_resource", name="uq_meet_sub_user_target"),
        Index("ix_meet_subscriptions_status_expires", "status", "expires_at"),
        Index("ix_meet_subscriptions_project", "project_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<MeetSubscription id={self.id} target={self.target_resource} "
            f"status={self.status}>"
        )
