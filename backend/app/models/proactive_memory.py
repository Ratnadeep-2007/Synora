"""Proactive memory (Mem0 proactive patterns, plan.md): precomputed hints
surfaced at session start, and an idempotency/cooldown log for proactive
operations. Canonical claims/evidence stay in their existing tables; these
rows are derived, disposable, and always traceable to source refs."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.core.database import Base


def _now():
    return datetime.now(timezone.utc)


class ProactiveHint(Base):
    __tablename__ = "proactive_hints"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="default_tenant", index=True)
    project_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(255), nullable=True, index=True)
    kind = Column(String(32), nullable=False, default="proactive_hint")
    text = Column(Text, nullable=False)
    dedupe_hash = Column(String(64), nullable=False)
    source_refs_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_surfaced_at = Column(DateTime(timezone=True), nullable=True)
    surface_count = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_proactive_hint_scope", "tenant_id", "project_id", "dedupe_hash", unique=True),
    )


class ProactiveEvent(Base):
    """Dedupe + cooldown log: one row per proactive operation key."""

    __tablename__ = "proactive_events"

    id = Column(String(64), primary_key=True)
    event_key = Column(String(64), nullable=False, unique=True, index=True)
    kind = Column(String(48), nullable=False)
    tenant_id = Column(String(64), nullable=False, default="default_tenant")
    project_id = Column(String(64), nullable=True, index=True)
    user_id = Column(String(255), nullable=True)
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
