from datetime import datetime, timezone
from enum import Enum
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_candidate_id() -> str:
    return f"cand_{uuid.uuid4().hex[:12]}"


def generate_agent_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


class ClassificationEnum(str, Enum):
    IDEA = "Idea"
    PROPOSAL = "Proposal"
    DISCUSSION = "Discussion"
    DECISION = "Decision"
    REJECTED = "Rejected"
    SUPERSEDED = "Superseded"
    QUESTION = "Question"
    REQUIREMENT = "Requirement"
    ASSUMPTION = "Assumption"
    ACTION_ITEM = "ActionItem"


class CandidateKnowledge(Base):
    """
    Extracted candidate knowledge produced by LLM intelligence.
    IMPORTANT: Candidate knowledge is NOT authoritative Project State.
    Every candidate item MUST reference one or more Evidence records.
    """
    __tablename__ = "candidate_knowledge"

    id = Column(String(64), primary_key=True, default=generate_candidate_id)
    project_id = Column(String(64), index=True, nullable=False)
    meeting_id = Column(String(64), ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True, index=True)
    category = Column(String(64), nullable=False)  # proposal, decision_candidate, requirement_candidate, etc.
    classification = Column(String(64), default=ClassificationEnum.PROPOSAL.value, nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    confidence = Column(Float, default=0.85, nullable=False)
    evidence_ids_json = Column(Text, nullable=False)  # JSON array of evidence IDs (provenance required)
    status = Column(String(32), default="candidate", nullable=False)  # candidate, proposed, approved, rejected, superseded
    agent_run_id = Column(String(64), ForeignKey("agent_runs.agent_run_id", ondelete="SET NULL"), nullable=True, index=True)
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
    meeting = relationship("Meeting")
    agent_run = relationship("AgentRun", back_populates="candidates")

    __table_args__ = (
        Index("ix_candidate_project_status", "project_id", "status"),
        Index("ix_candidate_category_status", "category", "status"),
    )

    def __repr__(self) -> str:
        return f"<CandidateKnowledge id={self.id} category={self.category} status={self.status}>"


class AgentRun(Base):
    """
    AI Processing Record capturing intelligence run metadata, model provenance,
    prompt version, latency, and status for observability.
    """
    __tablename__ = "agent_runs"

    agent_run_id = Column(String(64), primary_key=True, default=generate_agent_run_id)
    project_id = Column(String(64), index=True, nullable=False)
    meeting_id = Column(String(64), ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True, index=True)
    input_evidence_ids_json = Column(Text, nullable=False)  # JSON list of evidence IDs supplied as input
    model = Column(String(64), default="synesis-intelligence-v1", nullable=False)
    prompt_version = Column(String(32), default="v1.0", nullable=False)
    output_reference_json = Column(Text, nullable=True)  # JSON summary of extracted items
    status = Column(String(32), default="completed", nullable=False)  # running, completed, failed
    latency_ms = Column(Float, default=0.0, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    meeting = relationship("Meeting")
    candidates = relationship("CandidateKnowledge", back_populates="agent_run")

    __table_args__ = (
        Index("ix_agent_runs_project_created", "project_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AgentRun id={self.agent_run_id} model={self.model} status={self.status}>"
