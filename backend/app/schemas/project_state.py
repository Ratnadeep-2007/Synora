from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ProjectStateRead(BaseModel):
    project_id: str
    current_version: int
    title: str
    vision: str
    requirements: List[Dict[str, Any]] = []
    architecture: List[Dict[str, Any]] = []
    agent_workflow: List[str] = []
    decisions: List[Dict[str, Any]] = []
    constraints: List[str] = []
    assumptions: List[str] = []
    open_questions: List[str] = []
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectStateVersionRead(BaseModel):
    id: str
    project_id: str
    version_number: int
    snapshot: Dict[str, Any]
    reason: str
    change_summary: Dict[str, Any]
    actor_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StateChangeRead(BaseModel):
    id: str
    project_id: str
    candidate_id: Optional[str] = None
    state_version_before: int
    state_version_after: Optional[int] = None
    operation: str
    target_section: str
    value: Any
    reason: str
    actor_id: str
    evidence_ids: List[str] = []
    approval_status: str
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ProposalApprovalRequest(BaseModel):
    actor_id: str = Field("usr_approver", description="User or authority approving the change")
    note: Optional[str] = Field(None, description="Optional approval commentary")


class ProposalRejectRequest(BaseModel):
    actor_id: str = Field("usr_reviewer", description="User rejecting the change")
    reason: str = Field(..., description="Mandatory reason for rejection")


class RollbackRequest(BaseModel):
    target_version: int = Field(..., ge=1, description="Version number to restore")
    actor_id: str = Field("usr_admin", description="Admin performing the rollback")
    reason: str = Field("Rollback to earlier known good state", description="Reason for rollback")
