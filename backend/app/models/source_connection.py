from datetime import datetime, timezone
from enum import Enum
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_connection_id() -> str:
    return f"conn_{uuid.uuid4().hex[:12]}"


class ConnectionStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class SourceConnection(Base):
    """
    Source connection model representing external provider connections (e.g. Google Meet).
    Stores server-side encrypted credentials and association with a Synesis user.
    """
    __tablename__ = "source_connections"

    id = Column(String(64), primary_key=True, default=generate_connection_id)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    provider = Column(String(64), index=True, nullable=False)  # e.g., "google"
    provider_account_id = Column(String(255), index=True, nullable=False)  # e.g., Google user id (sub)
    provider_account_email = Column(String(255), nullable=True)
    status = Column(String(32), default=ConnectionStatus.ACTIVE.value, index=True, nullable=False)
    encrypted_credentials = Column(Text, nullable=False)  # Fernet-encrypted JSON of tokens
    scopes = Column(Text, nullable=True)  # JSON or space-separated list of scopes
    expires_at = Column(DateTime(timezone=True), nullable=True)
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
    user = relationship("User", back_populates="connections")

    __table_args__ = (
        Index("ix_source_connections_user_provider", "user_id", "provider"),
        Index("ix_source_connections_provider_account", "provider", "provider_account_id"),
    )

    def __repr__(self) -> str:
        return f"<SourceConnection id={self.id} user_id={self.user_id} provider={self.provider} status={self.status}>"
