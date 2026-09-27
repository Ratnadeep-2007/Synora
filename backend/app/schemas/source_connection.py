from datetime import datetime
from typing import List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class SourceConnectionBase(BaseModel):
    provider: str = Field(..., description="Provider name, e.g. google")
    provider_account_id: str = Field(..., description="Provider account identifier (sub)")
    provider_account_email: Optional[str] = Field(None, description="Email associated with provider account")
    status: str = Field(..., description="Connection status: active, expired, revoked, disconnected, error")
    scopes: Optional[Union[List[str], str]] = Field(None, description="Granted OAuth scopes")
    expires_at: Optional[datetime] = Field(None, description="Access token expiration timestamp")


class SourceConnectionRead(SourceConnectionBase):
    """
    Public safe schema for source connections.
    CRITICAL SECURITY INVARIANT:
    NEVER include access_token, refresh_token, client_secret, or encrypted_credentials here!
    """
    id: str = Field(..., description="Unique connection ID")
    user_id: str = Field(..., description="Associated Synesis user ID")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SourceConnectionSummary(BaseModel):
    id: str
    provider: str
    provider_account_email: Optional[str]
    status: str
    is_active: bool
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
