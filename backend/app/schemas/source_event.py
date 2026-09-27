from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class SourceEventCreate(BaseModel):
    tenant_id: str = "tenant_default"
    project_id: str = "proj_default"
    source: str = "google_meet"
    source_event_id: str
    event_type: str = "transcript_entry"
    actor_id: Optional[str] = None
    occurred_at: Optional[datetime] = None
    payload: Dict[str, Any]
    status: str = "received"


class SourceEventRead(BaseModel):
    event_id: str
    tenant_id: str
    project_id: str
    source: str
    source_event_id: str
    event_type: str
    actor_id: Optional[str] = None
    occurred_at: Optional[datetime] = None
    payload_json: str
    ingested_at: datetime
    status: str
    error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EvidenceRead(BaseModel):
    id: str
    project_id: str
    source: str
    source_event_id: str
    meeting_id: Optional[str] = None
    transcript_id: Optional[str] = None
    transcript_entry_id: Optional[str] = None
    actor_id: Optional[str] = None
    occurred_at: Optional[datetime] = None
    content: str
    metadata_json: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
