from datetime import datetime, timezone
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


def generate_workspace_id() -> str:
    return f"vws_{uuid.uuid4().hex[:12]}"


def generate_revision_id() -> str:
    return f"vrev_{uuid.uuid4().hex[:12]}"


def generate_operation_id() -> str:
    return f"vop_{uuid.uuid4().hex[:12]}"


class VisualWorkspace(Base):
    """The living visual workspace for a project.

    One workspace per project. ``current_revision_id`` points at the latest
    immutable revision; historical revisions are never overwritten.
    """

    __tablename__ = "visual_workspaces"

    id = Column(String(64), primary_key=True, default=generate_workspace_id)
    project_id = Column(String(64), unique=True, index=True, nullable=False)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    name = Column(String(255), default="Living Visual Workspace", nullable=False)
    current_revision_id = Column(String(64), nullable=True)
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

    revisions = relationship(
        "VisualRevision",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<VisualWorkspace id={self.id} project={self.project_id}>"


class VisualRevision(Base):
    """An immutable snapshot of the project's visual workspace.

    Revisions form an append-only chain. Every revision records what Project
    State version and evidence it derives from, so a visual change is fully
    traceable: revision -> state version -> state change -> evidence -> source.
    """

    __tablename__ = "visual_revisions"

    id = Column(String(64), primary_key=True, default=generate_revision_id)
    workspace_id = Column(
        String(64),
        ForeignKey("visual_workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    project_id = Column(String(64), index=True, nullable=False)
    revision_number = Column(Integer, nullable=False)
    parent_revision_id = Column(String(64), nullable=True)
    derived_from_project_state_version = Column(Integer, nullable=True)
    scene_json = Column(Text, default="[]", nullable=False)
    app_state_json = Column(Text, default="{}", nullable=True)
    operations_json = Column(Text, default="[]", nullable=False)
    evidence_ids_json = Column(Text, default="[]", nullable=False)
    proposal_id = Column(String(64), nullable=True, index=True)
    actor_id = Column(String(255), default="system", nullable=False)
    reason = Column(Text, default="", nullable=False)
    is_current = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    workspace = relationship("VisualWorkspace", back_populates="revisions")
    operations = relationship(
        "VisualOperation",
        back_populates="revision",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "revision_number", name="uq_visual_revision_number"),
        Index("ix_visual_revision_project_created", "project_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<VisualRevision id={self.id} workspace={self.workspace_id} "
            f"n={self.revision_number}>"
        )


class VisualOperation(Base):
    """A structured visual edit inside a revision.

    Operations are semantic (add/update/remove/relabel/regroup/reconnect/
    reorder) so history is explainable without diffing raw scene JSON.
    """

    __tablename__ = "visual_operations"

    id = Column(String(64), primary_key=True, default=generate_operation_id)
    revision_id = Column(
        String(64),
        ForeignKey("visual_revisions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    op_type = Column(String(32), nullable=False)
    target_element_id = Column(String(128), nullable=True)
    payload_json = Column(Text, default="{}", nullable=False)
    source_evidence_ids_json = Column(Text, default="[]", nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    revision = relationship("VisualRevision", back_populates="operations")

    __table_args__ = (
        Index("ix_visual_operation_revision", "revision_id", "op_type"),
    )

    def __repr__(self) -> str:
        return f"<VisualOperation id={self.id} type={self.op_type} rev={self.revision_id}>"
