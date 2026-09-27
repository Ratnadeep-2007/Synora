from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


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


class CandidateItemDTO(BaseModel):
    category: str = Field(..., description="proposal, decision_candidate, requirement_candidate, etc.")
    classification: ClassificationEnum
    title: str
    content: str
    confidence: float = Field(0.85, ge=0.0, le=1.0)
    evidence_ids: List[str] = Field(..., min_length=1, description="Must reference at least one evidence ID")


class ExtractionBatchResult(BaseModel):
    items: List[CandidateItemDTO] = []
    agent_run_id: Optional[str] = None
    model: str = "synesis-intelligence-v1"
    prompt_version: str = "v1.0"
    source: Optional[str] = None
    context_project_id: Optional[str] = None
    context_status: Optional[str] = None


class CandidateKnowledgeRead(BaseModel):
    id: str
    project_id: str
    meeting_id: Optional[str] = None
    category: str
    classification: str
    title: str
    content: str
    confidence: float
    evidence_ids: List[str] = []
    status: str
    agent_run_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentRunRead(BaseModel):
    agent_run_id: str
    project_id: str
    meeting_id: Optional[str] = None
    model: str
    prompt_version: str
    status: str
    latency_ms: float
    error: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
