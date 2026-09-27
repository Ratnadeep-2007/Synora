from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SpecialistCapabilityRead(BaseModel):
    id: str
    name: str
    role: str
    description: str
    capabilities: List[str]
    status: str = "ready"
    last_run_at: Optional[datetime] = None
    current_task: Optional[str] = None


class ProjectAgentRead(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    name: str
    status: str
    role: str
    identity: Dict[str, Any]
    memory_context: Dict[str, Any]
    capabilities: List[SpecialistCapabilityRead]
    connected_tools: List[str]
    excalidraw_workspace_id: Optional[str] = None
    current_project_state_version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectAgentDispatchRequest(BaseModel):
    capability_id: str = Field(..., description="Specialist capability to invoke (e.g. ba_agent, project_planner_agent, functional_agent, tech_agent, frappe_agent)")
    task_description: Optional[str] = Field(None, description="Optional task instructions")
    custom_query: Optional[str] = Field(None, description="Optional context search filter")


class ProjectAgentMemoryUpdate(BaseModel):
    notes: Optional[str] = None
    priorities: Optional[List[str]] = None
    milestones: Optional[List[str]] = None
    memory_updates: Optional[Dict[str, Any]] = None


#: Canonical source/provider IDs selectable during project creation.
#: google_meet and excalidraw are platform sources; whatsapp maps to the
#: existing WhatsApp/Baileys connector (provider_name "whatsapp").
PROJECT_SOURCE_IDS = ("google_meet", "whatsapp", "excalidraw")


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., description="Project name")
    description: Optional[str] = Field("", description="Project description")
    workspace_id: Optional[str] = Field("ws_default", description="Workspace ID")
    sources: Optional[List[str]] = Field(
        default=None,
        description="Source/provider IDs to enable for the project (google_meet, whatsapp, excalidraw)",
    )


class ProjectRead(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    project_agent_id: Optional[str] = None
    current_state_version: int = 1
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkspaceRead(BaseModel):
    id: str
    name: str
    description: str
    projects_count: int = 0
    workspace_agent_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WorkspaceAgentRead(BaseModel):
    id: str
    workspace_id: str
    name: str
    status: str
    role: str
    identity: Dict[str, Any]
    memory_context: Dict[str, Any]
    capabilities: List[SpecialistCapabilityRead]
    connected_tools: List[str]
    projects_count: int = 0
    managed_projects: List[Dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkspaceAgentDispatchRequest(BaseModel):
    capability_id: str = Field(..., description="Specialist capability to invoke")
    project_id: Optional[str] = Field(None, description="Optional target project to focus capability execution")
    task_description: Optional[str] = Field(None, description="Optional task instructions")
    custom_query: Optional[str] = Field(None, description="Optional context search filter")


class WorkspaceAgentMemoryUpdate(BaseModel):
    priorities: Optional[List[str]] = None
    milestones: Optional[List[str]] = None
    insights: Optional[List[str]] = None
    memory_updates: Optional[Dict[str, Any]] = None

