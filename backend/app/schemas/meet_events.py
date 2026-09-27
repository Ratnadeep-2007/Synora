from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class MeetSubscriptionCreate(BaseModel):
    target_resource: str = Field(description="Meeting space (spaces/...) or user (users/...) target")
    target_type: str = Field(default="meeting_space", description="meeting_space | user")
    project_id: Optional[str] = Field(default=None, description="Synesis project to map transcripts to")
    workspace_id: str = Field(default="ws_default")
    event_types: Optional[List[str]] = None
    pubsub_topic: Optional[str] = None


class MeetSubscriptionRead(BaseModel):
    id: str
    workspace_id: str
    project_id: Optional[str] = None
    user_id: str
    provider: str
    source_connection_id: Optional[str] = None
    target_resource: str
    target_type: str
    subscription_name: Optional[str] = None
    event_types: List[str] = []
    pubsub_topic: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    renewed_at: Optional[datetime] = None
    last_event_at: Optional[datetime] = None
    last_error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PubSubPushResponse(BaseModel):
    acknowledged: bool
    action: str
    event_record_id: Optional[str] = None
    reason: Optional[str] = None


class MeetEventRecordRead(BaseModel):
    id: str
    provider_event_id: str
    subscription_id: Optional[str] = None
    workspace_id: str
    project_id: Optional[str] = None
    user_id: str
    event_type: str
    conference_record_id: Optional[str] = None
    transcript_resource: Optional[str] = None
    status: str
    attempts: str = "0"
    last_error: Optional[str] = None
    meeting_id: Optional[str] = None
    received_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MeetReconcileResponse(BaseModel):
    success: bool = True
    message: str
    mode: str = "reconciliation"
    total_conferences_discovered: int = 0
    total_conferences_synced: int = 0
    total_transcripts_synced: int = 0
    total_entries_synced: int = 0
    total_events_processed: int = 0
    meetings: list = []
