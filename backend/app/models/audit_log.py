from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    String,
    Text,
)

from app.core.database import Base


def generate_audit_id() -> str:
    return f"aud_{uuid.uuid4().hex[:12]}"


class AuditLog(Base):
    """
    Immutable audit trail recording high-impact governance and administrative operations.
    Captures actor, action, tenant, timestamps, before/after states, and results.
    """
    __tablename__ = "audit_logs"

    id = Column(String(64), primary_key=True, default=generate_audit_id)
    tenant_id = Column(String(64), index=True, nullable=False, default="default_tenant")
    actor_id = Column(String(64), index=True, nullable=False)
    actor_role = Column(String(32), nullable=True)
    action = Column(String(64), index=True, nullable=False)
    resource_type = Column(String(64), index=True, nullable=False)
    resource_id = Column(String(64), index=True, nullable=True)
    before_state_json = Column(Text, nullable=True)
    after_state_json = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
    status = Column(String(32), default="success", nullable=False)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_logs_tenant_timestamp", "tenant_id", "timestamp"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action} actor={self.actor_id} resource={self.resource_type}:{self.resource_id}>"
