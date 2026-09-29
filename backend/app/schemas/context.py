from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ContextSignal(BaseModel):
    """One piece of evidence supporting a context decision."""

    kind: str = Field(description="deterministic | semantic | continuity | visual | authorization")
    name: str
    detail: Optional[str] = None
    weight: float = 0.0


class CandidateProject(BaseModel):
    project_id: str
    project_name: str
    confidence: float = 0.0
    reasons: List[str] = []
    supporting_evidence_ids: List[str] = []
    supporting_state_sections: List[str] = []
    conflicts: List[str] = []


class ContextResolutionResult(BaseModel):
    """Structured output of the Context Intelligence resolver."""

    decision: str = Field(description="resolved | ambiguous | unknown | casual_ignored")
    project_id: Optional[str] = None
    confidence: float = 0.0
    margin: float = 0.0
    is_casual: bool = False
    signals: List[ContextSignal] = []
    candidate_projects: List[CandidateProject] = []
    reason: str = ""
    requires_human_review: bool = True
    evidence_ids: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    model_version: Optional[str] = None

    @property
    def context_status(self) -> str:
        return self.decision

    @property
    def explanation(self) -> str:
        return self.reason

    @property
    def candidates(self) -> List[Dict[str, Any]]:
        return [
            {"project_id": c.project_id, "score": c.confidence, "reasons": c.reasons}
            for c in self.candidate_projects
        ]

    @property
    def deterministic_signals(self) -> List[ContextSignal]:
        return [s for s in self.signals if s.kind in ("deterministic", "authorization")]

    @property
    def semantic_signals(self) -> List[ContextSignal]:
        return [s for s in self.signals if s.kind in ("semantic", "continuity", "visual")]


class ContextCandidateItem(BaseModel):
    """One ranked project suggestion returned by the semantic resolver."""

    project_id: str
    confidence: float = 0.0
    reasons: List[str] = []


class ContextCandidateBatch(BaseModel):
    """Structured semantic-resolver response (Groq + Llama / NVIDIA NIM + DeepSeek)."""

    items: List[ContextCandidateItem] = []
    is_casual: bool = Field(default=False, description="True if the message is casual chatter, personal banter, greetings, or non-project talk")
    model: str = ""
    prompt_version: str = ""


class PossibleMatchRead(BaseModel):
    id: str
    unknown_item_id: str
    candidate_project_id: str
    candidate_project_name: Optional[str] = None
    similarity_reason: List[str] = []
    supporting_evidence_ids: List[str] = []
    supporting_state_sections: List[str] = []
    conflicts: List[str] = []
    recommendation: str = "review"
    created_at: Optional[datetime] = None


class UnknownContextItemRead(BaseModel):
    id: str
    project_id: str
    tenant_id: str
    source: str
    source_event_id: Optional[str] = None
    evidence_id: Optional[str] = None
    meeting_id: Optional[str] = None
    actor_id: Optional[str] = None
    occurred_at: Optional[datetime] = None
    content: str = ""
    payload: Dict[str, Any] = {}
    status: str
    assigned_project_id: Optional[str] = None
    assigned_by: Optional[str] = None
    assigned_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    matches: List[PossibleMatchRead] = []

    model_config = ConfigDict(from_attributes=True)


class UnknownContextAssignRequest(BaseModel):
    project_id: str = Field(description="Destination project for this item")
    note: Optional[str] = None


class UnknownContextCreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None
    workspace_id: Optional[str] = "ws_default"


class UnknownContextActionResponse(BaseModel):
    success: bool = True
    message: str
    item: Optional[UnknownContextItemRead] = None
    created_project_id: Optional[str] = None
