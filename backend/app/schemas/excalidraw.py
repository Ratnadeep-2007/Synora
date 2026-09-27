from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExcalidrawIngestRequest(BaseModel):
    name: str = Field(default="System Architecture Diagram", description="Name of the visual diagram")
    elements: List[Dict[str, Any]] = Field(default_factory=list, description="Raw Excalidraw element objects")
    app_state: Dict[str, Any] = Field(default_factory=dict, description="Excalidraw appState settings")
    tenant_id: str = Field(default="default_tenant", description="Tenant ID")


class ExcalidrawDiffPreview(BaseModel):
    nodes_before: List[str] = Field(default_factory=list)
    nodes_after: List[str] = Field(default_factory=list)
    nodes_added: List[str] = Field(default_factory=list)
    nodes_removed: List[str] = Field(default_factory=list)
    connections_before: List[str] = Field(default_factory=list)
    connections_after: List[str] = Field(default_factory=list)


class ExcalidrawArtifactRead(BaseModel):
    id: str
    project_id: str
    tenant_id: str
    name: str
    version: int
    elements: List[Dict[str, Any]]
    app_state: Dict[str, Any]
    extracted_nodes: List[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ExcalidrawProposalRead(BaseModel):
    id: str
    artifact_id: str
    project_id: str
    tenant_id: str
    derived_from_state_version: int
    status: str
    reason: str
    diff_preview: ExcalidrawDiffPreview
    proposed_elements: List[Dict[str, Any]]
    evidence_ids: List[str]
    created_at: datetime
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None

    class Config:
        from_attributes = True


class ExcalidrawProposalReviewRequest(BaseModel):
    action: str = Field(..., description="'approve' or 'reject'")
    reason: Optional[str] = Field(None, description="Optional explanation for review decision")


class AiGenerateDiagramRequest(BaseModel):
    focus_prompt: Optional[str] = Field(None, description="Optional focus or instructions for the AI visual generator")
    direct_apply: bool = Field(False, description="If True, directly updates the active canvas; if False, creates a reviewable proposal")

