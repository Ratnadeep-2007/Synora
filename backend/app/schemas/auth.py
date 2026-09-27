from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.source_connection import SourceConnectionRead


class OAuthInitResponse(BaseModel):
    """Returned when requesting OAuth authorization URL programmatically."""
    authorization_url: str = Field(..., description="Google OAuth authorization URL for user consent")
    provider: str = Field("google", description="OAuth provider")


class OAuthCallbackResponse(BaseModel):
    """Returned on successful OAuth callback without redirect."""
    success: bool = Field(True, description="Whether the connection was completed successfully")
    message: str = Field("Google account connected successfully", description="Status message")
    connection: SourceConnectionRead = Field(..., description="Safe source connection metadata")


class OAuthRefreshResponse(BaseModel):
    """Returned when token refresh is triggered."""
    success: bool = True
    message: str
    connection: SourceConnectionRead


class OAuthDisconnectResponse(BaseModel):
    """Returned when disconnecting / revoking a connection."""
    success: bool = True
    message: str = "Connection successfully disconnected and credentials revoked."
    connection_id: str
    status: str = "revoked"


class ErrorDetail(BaseModel):
    error: str
    message: str
    detail: Optional[str] = None
