import os
from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


from pathlib import Path

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_DB_FILE = _ROOT_DIR / "synesis.db"

class Settings(BaseSettings):
    PROJECT_NAME: str = "Synesis"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = Field(default="development", description="development | testing | production")

    # Security
    SECRET_KEY: str = Field(
        default="synesis-insecure-development-secret-key-change-in-production-12345",
        description="Key used for HMAC signing of OAuth CSRF state and sessions",
    )
    ENCRYPTION_KEY: str = Field(
        default="synesis-default-credential-encryption-key-passphrase-32bytes",
        description="Key used for symmetric encryption of credentials at rest (Fernet/AES)",
    )

    # Database
    DATABASE_URL: str = Field(
        default=f"sqlite:///{_DEFAULT_DB_FILE.as_posix()}",
        description="SQLAlchemy database URL (SQLite for local dev, PostgreSQL for production)",
    )

    # Google OAuth Configuration
    GOOGLE_CLIENT_ID: str = Field(
        default="",
        description="Google Cloud OAuth 2.0 Client ID",
    )
    GOOGLE_CLIENT_SECRET: str = Field(
        default="",
        description="Google Cloud OAuth 2.0 Client Secret",
    )
    GOOGLE_REDIRECT_URI: str = Field(
        default="http://localhost:8000/auth/google/callback",
        description="Authorized redirect URI registered in Google Cloud Console",
    )
    GOOGLE_OAUTH_SCOPES: List[str] = Field(
        default=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/meetings.space.readonly",
        ],
        description="OAuth scopes requested from Google",
    )

    # Google Workspace Events API (notification infrastructure only).
    # Workspace Events emits transcript notifications; the Meet REST API
    # retrieves the actual transcript resources.
    WORKSPACE_EVENTS_API_BASE: str = Field(
        default="https://workspaceevents.googleapis.com",
        description="Base URL for the Google Workspace Events API",
    )
    MEET_TRANSCRIPT_EVENT_TYPE: str = Field(
        default="google.workspace.meet.transcript.v2.fileGenerated",
        description="Workspace Events event type fired when a Meet transcript file is generated",
    )

    # Google Cloud Pub/Sub (notification delivery layer for Workspace Events).
    # Empty by default: Pub/Sub push delivery must be explicitly configured.
    PUBSUB_VERIFICATION_TOKEN: str = Field(
        default="",
        description="Shared secret used to verify Pub/Sub push requests ( Bearer token )",
    )

    # Slack Configuration
    SLACK_BOT_TOKEN: str = Field(
        default="",
        description="Slack Bot User OAuth Token (xoxb-...)",
    )
    SLACK_SIGNING_SECRET: str = Field(
        default="slack_signing_secret_synesis_default",
        description="Slack App Signing Secret for verifying Events API webhooks",
    )

    # Frontend Integration
    FRONTEND_URL: str = Field(
        default="http://localhost:3000",
        description="Base URL of the frontend web application",
    )

    # OAuth State Expiry (in seconds)
    OAUTH_STATE_EXPIRE_SECONDS: int = 600  # 10 minutes

    # Cookie security settings
    COOKIE_SECURE: bool = False  # Set to True in production (HTTPS)
    COOKIE_SAMESITE: str = "lax"

    # LLM & NVIDIA NIM Configuration
    LLM_PROVIDER: str = Field(
        default="nvidia",
        description="LLM Provider: nvidia | groq | deterministic",
    )
    NVIDIA_API_KEY: str = Field(
        default="",
        description="NVIDIA NIM API Key from build.nvidia.com (nvapi-...)",
    )
    NVIDIA_MODEL: str = Field(
        default="deepseek-ai/deepseek-v4.1-flash",
        description="Model identifier on NVIDIA NIM (e.g. deepseek-ai/deepseek-v4.1-flash, deepseek-ai/deepseek-r1)",
    )
    NVIDIA_BASE_URL: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="NVIDIA NIM API base URL",
    )

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_google_oauth_configured(self) -> bool:
        """Returns True if Google OAuth credentials have been populated."""
        return bool(
            self.GOOGLE_CLIENT_ID
            and self.GOOGLE_CLIENT_SECRET
            and not self.GOOGLE_CLIENT_ID.startswith("your-google-client-id")
            and not self.GOOGLE_CLIENT_SECRET.startswith("your-google-client-secret")
        )

    @property
    def is_nvidia_nim_configured(self) -> bool:
        """Returns True if NVIDIA NIM API key has been populated."""
        return bool(
            self.NVIDIA_API_KEY
            and self.NVIDIA_API_KEY.strip()
            and not self.NVIDIA_API_KEY.startswith("your-")
        )

    @field_validator("GOOGLE_OAUTH_SCOPES")
    @classmethod
    def validate_google_oauth_scopes(cls, scopes: List[str]) -> List[str]:
        """Reject obsolete/invalid Meet scopes and undeclared Drive scopes.

        Only meetings.space.readonly is valid for the Meet REST transcript
        retrieval path. The obsolete meetings.conference.readonly scope must
        never be requested, and Drive scopes require an explicit transcript
        file-download implementation before they may be added.
        """
        joined = " ".join(scopes)
        if "meetings.conference.readonly" in joined:
            raise ValueError(
                "Obsolete Google OAuth scope 'meetings.conference.readonly' must not be requested. "
                "Use 'meetings.space.readonly' for Meet REST transcript retrieval."
            )
        if "drive" in joined:
            raise ValueError(
                "Drive scopes must not be requested unless transcript file download "
                "is explicitly implemented."
            )
        return scopes


settings = Settings()
