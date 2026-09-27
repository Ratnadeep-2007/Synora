from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ConflictRead(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    state_change_id: Optional[str] = None
    candidate_id: Optional[str] = None
    type: str
    severity: str
    title: str
    description: Optional[str] = None
    current_state_reference: str
    proposed_change_reference: str
    evidence_ids: List[str] = []
    status: str
    impact: Optional[str] = None
    risk_level: str
    source: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None

    class Config:
        from_attributes = True


class ConflictReviewRequest(BaseModel):
    action: Literal["approve", "reject", "mark_unresolved"]
    actor_id: str = "user"
    reason: Optional[str] = None
    note: Optional[str] = None


class ConflictReviewResponse(BaseModel):
    conflict: ConflictRead
    message: str
    project_state_version: Optional[int] = None
