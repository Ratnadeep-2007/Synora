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


def generate_state_id() -> str:
    return f"pstate_{uuid.uuid4().hex[:12]}"


def generate_version_id() -> str:
    return f"pver_{uuid.uuid4().hex[:12]}"


def generate_change_id() -> str:
    return f"chg_{uuid.uuid4().hex[:12]}"


class ChangeOperation(str, Enum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    REORDER = "reorder"
    SUPERSEDE = "supersede"


class ApprovalStatus(str, Enum):
    CANDIDATE = "candidate"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ProjectState(Base):
    """
    Authoritative Project State model.
    Maintains the single source of truth for what a project is building.
    Supports: Vision, Requirements, Architecture, Agent Workflow, Decisions,
    Constraints, Assumptions, Open Questions.
    """
    __tablename__ = "project_states"

    id = Column(String(64), primary_key=True, default=generate_state_id)
    project_id = Column(String(64), unique=True, index=True, nullable=False)
    current_version = Column(Integer, default=1, nullable=False)
    title = Column(String(255), default="New Project", nullable=False)
    vision = Column(Text, default="", nullable=False)
    requirements_json = Column(Text, default="[]", nullable=False)
    architecture_json = Column(Text, default="[]", nullable=False)
    agent_workflow_json = Column(Text, default='["BA", "Project", "Functional", "Tech", "Frappe"]', nullable=False)
    decisions_json = Column(Text, default="[]", nullable=False)
    constraints_json = Column(Text, default="[]", nullable=False)
    assumptions_json = Column(Text, default="[]", nullable=False)
    open_questions_json = Column(Text, default="[]", nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    versions = relationship("ProjectStateVersion", back_populates="project_state", cascade="all, delete-orphan")
    changes = relationship("StateChange", back_populates="project_state", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ProjectState project={self.project_id} v={self.current_version}>"


class ProjectStateVersion(Base):
    """
    Immutable historical snapshot of Project State at a specific version.
    Guarantees that no state transition destroys project history.
    """
    __tablename__ = "project_state_versions"

    id = Column(String(64), primary_key=True, default=generate_version_id)
    project_id = Column(String(64), ForeignKey("project_states.project_id", ondelete="CASCADE"), index=True, nullable=False)
    version_number = Column(Integer, nullable=False)
    snapshot_json = Column(Text, nullable=False)  # Full serialized ProjectState dictionary
    reason = Column(Text, nullable=False)  # Why this version was created
    change_summary_json = Column(Text, default="{}", nullable=False)
    actor_id = Column(String(255), default="system", nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    project_state = relationship("ProjectState", back_populates="versions")

    __table_args__ = (
        UniqueConstraint("project_id", "version_number", name="uq_project_state_version"),
        Index("ix_project_versions_order", "project_id", "version_number"),
    )

    def __repr__(self) -> str:
        return f"<ProjectStateVersion project={self.project_id} v={self.version_number}>"


class StateChange(Base):
    """
    Explicit mutation or proposed change to Project State.
    Maintains the bridge between Candidate Knowledge and Authoritative State.
    High-impact changes remain in 'proposed' status until human approval.
    """
    __tablename__ = "state_changes"

    id = Column(String(64), primary_key=True, default=generate_change_id)
    project_id = Column(String(64), ForeignKey("project_states.project_id", ondelete="CASCADE"), index=True, nullable=False)
    candidate_id = Column(String(64), ForeignKey("candidate_knowledge.id", ondelete="SET NULL"), nullable=True, index=True)
    state_version_before = Column(Integer, nullable=False)
    state_version_after = Column(Integer, nullable=True)  # Populated upon approval
    operation = Column(String(32), default=ChangeOperation.INSERT.value, nullable=False)
    target_section = Column(String(64), nullable=False)  # vision, requirements, architecture, agent_workflow, decisions, etc.
    value_json = Column(Text, nullable=False)  # The proposed change value
    reason = Column(Text, nullable=False)
    actor_id = Column(String(255), default="system", nullable=False)
    evidence_ids_json = Column(Text, default="[]", nullable=False)  # Supporting evidence provenance
    approval_status = Column(String(32), default=ApprovalStatus.PROPOSED.value, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    project_state = relationship("ProjectState", back_populates="changes")
    candidate = relationship("CandidateKnowledge")

    __table_args__ = (
        Index("ix_state_changes_status", "project_id", "approval_status"),
    )

    def __repr__(self) -> str:
        return f"<StateChange id={self.id} target={self.target_section} op={self.operation} status={self.approval_status}>"
