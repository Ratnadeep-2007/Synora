from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AgentDefinitionRead(BaseModel):
    agent_id: str
    name: str
    role: str
    description: str
    capabilities: List[str]
    permissions_read: List[str]
    permissions_write: List[str]
    permissions_prohibited: List[str]
    input_types: List[str]
    output_types: List[str]
    status: str = "idle"
    current_task: Optional[str] = None
    last_run_at: Optional[datetime] = None
    current_project_state_version: Optional[int] = None


class AgentExecutionRead(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    agent_id: str
    project_state_version: int
    input_references: List[str] = []
    output_references: List[str] = []
    model: str
    prompt_version: str
    status: str
    output_type: str
    output_payload: Dict[str, Any] = {}
    duration_ms: float
    error: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AgentRunTriggerRequest(BaseModel):
    task_description: Optional[str] = None
    custom_context_query: Optional[str] = None


class AgentRunTriggerResponse(BaseModel):
    execution: AgentExecutionRead
    message: str
