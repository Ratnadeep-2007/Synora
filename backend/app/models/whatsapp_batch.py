from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_batch_id() -> str:
    return f"wbatch_{uuid.uuid4().hex[:12]}"


def generate_batch_item_id() -> str:
    return f"wbi_{uuid.uuid4().hex[:12]}"


class WhatsAppBatch(Base):
    """Durable one-minute processing window for WhatsApp messages."""

    __tablename__ = "whatsapp_batches"

    id = Column(String(64), primary_key=True, default=generate_batch_id)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    group_jid = Column(String(255), default="unknown@g.us", index=True, nullable=False)
    group_name = Column(String(255), default="WhatsApp Group", nullable=False)
    status = Column(String(32), default="queued", index=True, nullable=False)
    window_started_at = Column(DateTime(timezone=True), nullable=False)
    due_at = Column(DateTime(timezone=True), index=True, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    items = relationship("WhatsAppBatchItem", back_populates="batch", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_whatsapp_batches_due", "tenant_id", "status", "due_at"),
        Index("ix_whatsapp_batches_group", "tenant_id", "group_jid", "status"),
    )


class WhatsAppBatchItem(Base):
    """One original WhatsApp message waiting inside a durable batch."""

    __tablename__ = "whatsapp_batch_items"

    id = Column(String(64), primary_key=True, default=generate_batch_item_id)
    batch_id = Column(String(64), ForeignKey("whatsapp_batches.id", ondelete="CASCADE"), index=True, nullable=False)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    group_jid = Column(String(255), default="unknown@g.us", nullable=False)
    message_id = Column(String(255), nullable=False)
    payload_json = Column(Text, nullable=False)
    received_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    status = Column(String(32), default="queued", index=True, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)

    batch = relationship("WhatsAppBatch", back_populates="items")

    __table_args__ = (
        UniqueConstraint("tenant_id", "group_jid", "message_id", name="uq_whatsapp_batch_message"),
        Index("ix_whatsapp_batch_items_batch_status", "batch_id", "status"),
    )
