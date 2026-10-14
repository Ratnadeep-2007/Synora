"""Additive tables for durable retrieval, provenance, and proactive processing."""

from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text
from app.core.database import Base


def now():
    return datetime.now(timezone.utc)


class MemoryIndex(Base):
    __tablename__ = "memory_indexes"
    id = Column(String(100), primary_key=True)
    entity_id = Column(String(64), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    tenant_id = Column(String(64), nullable=False)
    project_id = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    content = Column(Text, nullable=False)
    offset_start = Column(Integer, nullable=False, default=0)
    offset_end = Column(Integer, nullable=False, default=0)
    vector_json = Column(Text, nullable=False, default="[]")
    provider = Column(String(32), nullable=False)
    model = Column(String(128), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (Index("ix_memory_index_scope", "tenant_id", "project_id", "kind"),)


class MemoryTerm(Base):
    __tablename__ = "memory_terms"
    record_id = Column(String(100), ForeignKey("memory_indexes.id", ondelete="CASCADE"), primary_key=True)
    term = Column(String(128), primary_key=True)
    weight = Column(Integer, nullable=False, default=1)
    __table_args__ = (Index("ix_memory_term_lookup", "term", "record_id"),)


class MemoryClaimRevision(Base):
    __tablename__ = "memory_claim_revisions"
    id = Column(String(64), primary_key=True)
    candidate_id = Column(String(64), ForeignKey("candidate_knowledge.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id = Column(String(64), index=True, nullable=False)
    status = Column(String(32), nullable=False)
    support_type = Column(String(16), nullable=False, default="explicit")
    snapshot_json = Column(Text, nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=False, default=now)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    superseded_by = Column(String(64), nullable=True)


class SourceArtifact(Base):
    __tablename__ = "source_artifacts"
    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    project_id = Column(String(64), nullable=False, index=True)
    evidence_id = Column(String(64), nullable=True, index=True)
    source = Column(String(64), nullable=False)
    filename = Column(String(255), nullable=False)
    mime_type = Column(String(128), nullable=False)
    sha256 = Column(String(64), nullable=False)
    data = Column(LargeBinary, nullable=False)
    status = Column(String(32), nullable=False, default="received")
    error = Column(Text, nullable=True)
    extraction_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)


class TopicWindow(Base):
    __tablename__ = "topic_windows"
    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    stream_id = Column(String(255), nullable=False, index=True)
    project_id = Column(String(64), nullable=True)
    topic_terms_json = Column(Text, nullable=False, default="[]")
    evidence_ids_json = Column(Text, nullable=False, default="[]")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)
