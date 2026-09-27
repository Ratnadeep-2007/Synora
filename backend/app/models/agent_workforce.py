from datetime import datetime, timezone
from enum import Enum
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_agent_exec_id() -> str:
    return f"aex_{uuid.uuid4().hex[:12]}"


class AgentOutputType(str, Enum):
    ANALYSIS = "analysis"
    REQUIREMENT_PROPOSAL = "requirement_proposal"
    TECHNICAL_PROPOSAL = "technical_proposal"
    FUNCTIONAL_SPECIFICATION = "functional_specification"
    TASK_PROPOSAL = "task_proposal"


class AgentExecution(Base):
    """
    Detailed audit log for an individual AI Workforce agent run.
    Stores exact inputs, outputs, model provenance, and state version consumed.
    """
    __tablename__ = "agent_executions"

    id = Column(String(64), primary_key=True, default=generate_agent_exec_id)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    project_id = Column(String(64), ForeignKey("project_states.project_id", ondelete="CASCADE"), index=True, nullable=False)
    agent_id = Column(String(64), index=True, nullable=False)  # ba_agent, project_agent, functional_agent, tech_agent, frappe_agent
    project_state_version = Column(Integer, nullable=False)
    
    input_references_json = Column(Text, default="[]", nullable=False)  # JSON list of input IDs (state, evidence, prior runs)
    output_references_json = Column(Text, default="[]", nullable=False) # JSON list of output IDs (proposals, tickets)
    
    model = Column(String(64), default="synesis-worker-v1", nullable=False)
    prompt_version = Column(String(32), default="v1.0", nullable=False)
    status = Column(String(32), default="completed", nullable=False)  # queued, running, completed, failed
    
    output_type = Column(String(64), default=AgentOutputType.ANALYSIS.value, nullable=False)
    output_payload_json = Column(Text, default="{}", nullable=False)
    
    duration_ms = Column(Float, default=0.0, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    project_state = relationship("ProjectState")

    __table_args__ = (
        Index("ix_agent_exec_tenant_project_agent", "tenant_id", "project_id", "agent_id"),
        Index("ix_agent_exec_created", "project_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AgentExecution id={self.id} agent={self.agent_id} v={self.project_state_version} status={self.status}>"
