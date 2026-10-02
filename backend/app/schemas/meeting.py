from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ParticipantRead(BaseModel):
    id: str
    meeting_id: str
    provider_participant_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TranscriptEntryRead(BaseModel):
    id: str
    transcript_id: str
    provider_entry_id: str
    participant_id: Optional[str] = None
    participant_display_name: Optional[str] = None
    text: str
    language_code: Optional[str] = "en-US"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TranscriptRead(BaseModel):
    id: str
    meeting_id: str
    provider: str
    provider_transcript_id: str
    state: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    docs_destination_url: Optional[str] = None
    created_at: datetime
    entries: List[TranscriptEntryRead] = []

    model_config = ConfigDict(from_attributes=True)


class MeetingRead(BaseModel):
    id: str
    project_id: str
    user_id: str
    provider: str
    provider_conference_id: str
    meeting_space_id: Optional[str] = None
    title: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MeetingDetailRead(MeetingRead):
    participants: List[ParticipantRead] = []
    transcripts: List[TranscriptRead] = []
    # Meet-only session projection over shared Evidence/Candidate/Project Memory.
    session_intelligence: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class MeetingSyncResponse(BaseModel):
    success: bool = True
    message: str = "Meeting synchronization completed successfully"
    total_conferences_discovered: int = 0
    total_conferences_synced: int = 0
    total_transcripts_synced: int = 0
    total_entries_synced: int = 0
    meetings: List[MeetingRead] = []


class TranscriptEntryInput(BaseModel):
    speaker: str = "Unknown Speaker"
    text: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class TranscriptIngestRequest(BaseModel):
    project_id: str = "proj_default"
    title: str = "Imported Meeting Transcript"
    provider: str = "manual_transcript"
    raw_transcript: Optional[str] = None
    entries: Optional[List[TranscriptEntryInput]] = None
    auto_process: bool = True


class TranscriptIngestResponse(BaseModel):
    success: bool = True
    message: str = "Transcript ingested successfully"
    meeting_id: str
    project_id: str
    title: str
    entries_count: int
    pipeline_result: Optional[dict] = None

