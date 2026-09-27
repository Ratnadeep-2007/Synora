from datetime import datetime, timezone
from enum import Enum
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_artifact_id() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def generate_proposal_id() -> str:
    return f"diagprop_{uuid.uuid4().hex[:12]}"


class ExcalidrawProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExcalidrawArtifact(Base):
    """
    Excalidraw visual architecture artifact for a project.
    Role A (Input): Ingested visual architecture representation acting as project evidence.
    Role B (Output): Updatable visual architecture target updated ONLY after human approval.
    """
    __tablename__ = "excalidraw_artifacts"

    id = Column(String(64), primary_key=True, default=generate_artifact_id)
    project_id = Column(String(64), index=True, nullable=False)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    name = Column(String(255), default="System Architecture Diagram", nullable=False)
    version = Column(Integer, default=1, nullable=False)
    
    # Raw Excalidraw scene elements JSON (array of rectangles, texts, arrows, etc.)
    elements_json = Column(Text, default="[]", nullable=False)
    app_state_json = Column(Text, default="{}", nullable=True)
    
    # Extracted architectural node sequence / summary (e.g. ["User", "BA", "Project", "Functional"])
    extracted_nodes_json = Column(Text, default="[]", nullable=False)
    
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
    proposals = relationship("ExcalidrawProposal", back_populates="artifact", cascade="all, delete-orphan")
    revisions = relationship("ExcalidrawRevision", back_populates="artifact", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_excalidraw_project_tenant", "tenant_id", "project_id"),
    )

    def __repr__(self) -> str:
        return f"<ExcalidrawArtifact id={self.id} project={self.project_id} v={self.version}>"


class ExcalidrawProposal(Base):
    """
    Proposed visual architecture diagram modification derived from an approved Project State change.
    Guarantees Output Safety: Synesis NEVER directly mutates Excalidraw without human review.
    """
    __tablename__ = "excalidraw_proposals"

    id = Column(String(64), primary_key=True, default=generate_proposal_id)
    artifact_id = Column(String(64), ForeignKey("excalidraw_artifacts.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id = Column(String(64), index=True, nullable=False)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    
    # The authoritative Project State version that motivated this diagram proposal
    derived_from_state_version = Column(Integer, nullable=False)
    
    status = Column(String(32), default=ExcalidrawProposalStatus.PENDING.value, nullable=False)
    reason = Column(Text, nullable=False)
    
    # Proposed new Excalidraw elements JSON
    proposed_elements_json = Column(Text, default="[]", nullable=False)
    
    # Structured diff preview (nodes_added, nodes_removed, sequence_before, sequence_after)
    diff_preview_json = Column(Text, default="{}", nullable=False)
    evidence_ids_json = Column(Text, default="[]", nullable=False)
    
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(String(255), nullable=True)

    # Relationships
    artifact = relationship("ExcalidrawArtifact", back_populates="proposals")

    __table_args__ = (
        Index("ix_excalidraw_prop_proj_status", "project_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<ExcalidrawProposal id={self.id} artifact={self.artifact_id} status={self.status}>"


class ExcalidrawRevision(Base):
    """Immutable visual snapshot for a project workspace revision."""
    __tablename__ = "excalidraw_revisions"

    id = Column(String(64), primary_key=True, default=lambda: f"exrev_{uuid.uuid4().hex[:12]}")
    artifact_id = Column(String(64), ForeignKey("excalidraw_artifacts.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id = Column(String(64), index=True, nullable=False)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    revision_number = Column(Integer, nullable=False)
    parent_revision_id = Column(String(64), nullable=True)
    derived_from_state_version = Column(Integer, nullable=True)
    snapshot_json = Column(Text, nullable=False)
    change_summary_json = Column(Text, default="{}", nullable=False)
    source_event_ids_json = Column(Text, default="[]", nullable=False)
    proposal_id = Column(String(64), nullable=True)
    actor_id = Column(String(255), default="system", nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    artifact = relationship("ExcalidrawArtifact", back_populates="revisions")

    __table_args__ = (
        UniqueConstraint("artifact_id", "revision_number", name="uq_excalidraw_revision"),
        Index("ix_excalidraw_revision_project_order", "project_id", "revision_number"),
    )

    def __repr__(self) -> str:
        return f"<ExcalidrawRevision id={self.id} artifact={self.artifact_id} v={self.revision_number}>"