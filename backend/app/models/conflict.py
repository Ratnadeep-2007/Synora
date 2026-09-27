from datetime import datetime, timezone
from enum import Enum
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_conflict_id() -> str:
    return f"conf_{uuid.uuid4().hex[:12]}"


class ConflictType(str, Enum):
    ARCHITECTURE = "architecture"
    REQUIREMENT = "requirement"
    SCOPE = "scope"
    DECISION = "decision"
    WORKFLOW = "workflow"
    DEPENDENCY = "dependency"


class ConflictSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConflictStatus(str, Enum):
    OPEN = "open"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    SUPERSEDED = "superseded"


class Conflict(Base):
    """
    First-class Conflict domain entity.
    Represents an inconsistency or divergence between candidate project knowledge
    and the authoritative Project State.
    """
    __tablename__ = "conflicts"

    id = Column(String(64), primary_key=True, default=generate_conflict_id)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    project_id = Column(String(64), ForeignKey("project_states.project_id", ondelete="CASCADE"), index=True, nullable=False)
    state_change_id = Column(String(64), ForeignKey("state_changes.id", ondelete="SET NULL"), nullable=True, index=True)
    candidate_id = Column(String(64), ForeignKey("candidate_knowledge.id", ondelete="SET NULL"), nullable=True, index=True)
    
    type = Column(String(32), default=ConflictType.DECISION.value, nullable=False)
    severity = Column(String(16), default=ConflictSeverity.MEDIUM.value, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    current_state_reference = Column(Text, nullable=False)  # Current state snippet / representation
    proposed_change_reference = Column(Text, nullable=False)  # Proposed state snippet / representation
    evidence_ids_json = Column(Text, default="[]", nullable=False)
    
    status = Column(String(32), default=ConflictStatus.OPEN.value, nullable=False)
    impact = Column(Text, nullable=True)
    risk_level = Column(String(32), default="medium", nullable=False)
    source = Column(String(128), default="google_meet", nullable=False)
    
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(255), nullable=True)

    # Relationships
    project_state = relationship("ProjectState")
    state_change = relationship("StateChange")
    candidate = relationship("CandidateKnowledge")

    __table_args__ = (
        Index("ix_conflicts_tenant_project", "tenant_id", "project_id"),
        Index("ix_conflicts_status", "project_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Conflict id={self.id} type={self.type} status={self.status} severity={self.severity}>"
