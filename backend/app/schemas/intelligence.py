from datetime import datetime
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    category: str = Field(
        ...,
        description=(
            "Exactly one of: decision, requirement, question, action_item, "
            "constraint, assumption, proposal. Free-form values here are "
            "silently dropped downstream, so do not invent variants."
        ),
    )
    classification: ClassificationEnum
    title: str
    content: str
    confidence: float = Field(0.85, ge=0.0, le=1.0)
    evidence_ids: List[str] = Field(..., min_length=1, description="Must reference at least one evidence ID")

    @field_validator("classification", mode="before")
    @classmethod
    def normalize_classification(cls, v: Any) -> Any:
        if isinstance(v, ClassificationEnum):
            return v
        s = str(v).strip().upper().replace(" ", "_").replace("-", "_")
        lookup = {
            "IDEA": ClassificationEnum.IDEA,
            "PROPOSAL": ClassificationEnum.PROPOSAL,
            "DISCUSSION": ClassificationEnum.DISCUSSION,
            "DECISION": ClassificationEnum.DECISION,
            "REJECTED": ClassificationEnum.REJECTED,
            "SUPERSEDED": ClassificationEnum.SUPERSEDED,
            "QUESTION": ClassificationEnum.QUESTION,
            "REQUIREMENT": ClassificationEnum.REQUIREMENT,
            "ASSUMPTION": ClassificationEnum.ASSUMPTION,
            "ACTION_ITEM": ClassificationEnum.ACTION_ITEM,
            "ACTIONITEM": ClassificationEnum.ACTION_ITEM,
            "INFORMATIONAL": ClassificationEnum.DISCUSSION,
            "INFO": ClassificationEnum.DISCUSSION,
        }
        return lookup.get(s, ClassificationEnum.DISCUSSION)


class ExtractionBatchResult(BaseModel):
    items: List[CandidateItemDTO] = []
    agent_run_id: Optional[str] = None
    model: str = "synesis-intelligence-v1"
    prompt_version: str = "v1.0"


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
