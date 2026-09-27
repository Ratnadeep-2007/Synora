from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class ContextCandidate(BaseModel):
    project_id: str
    project_name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)


class ContextResolutionResult(BaseModel):
    status: Literal["resolved", "ambiguous", "unknown"]
    selected_project_id: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    candidates: List[ContextCandidate] = Field(default_factory=list)
    model: str = "deterministic-context-v1"
    prompt_version: str = "context-v1"
