from typing import List
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_DB_FILE = _ROOT_DIR / "synora.db"

class Settings(BaseSettings):
    PROJECT_NAME: str = "Synora"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = Field(default="development")

    SECRET_KEY: str = Field(default="change-me-in-development")
    ENCRYPTION_KEY: str = Field(default="change-me-in-development")

    # PostgreSQL is authoritative in production; SQLite is test/dev convenience.
    DATABASE_URL: str = Field(default=f"sqlite:///{_DEFAULT_DB_FILE.as_posix()}")

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"
    GOOGLE_OAUTH_SCOPES: List[str] = Field(default_factory=lambda: [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/meetings.space.readonly",
    ])

    WORKSPACE_EVENTS_API_BASE: str = "https://workspaceevents.googleapis.com"
    MEET_TRANSCRIPT_EVENT_TYPE: str = "google.workspace.meet.transcript.v2.fileGenerated"
    PUBSUB_VERIFICATION_TOKEN: str = ""

    SLACK_BOT_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""
    FRONTEND_URL: str = "http://localhost:3000"

    OAUTH_STATE_EXPIRE_SECONDS: int = 600
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # NVIDIA NIM is the required/default semantic inference provider.
    # The provider abstraction can host other adapters later, but product
    # operation and documentation target NVIDIA NIM + DeepSeek.
    LLM_PROVIDER: str = Field(default="nvidia", description="nvidia | deterministic")
    NVIDIA_API_KEY: str = ""
    NVIDIA_MODEL: str = "deepseek-ai/deepseek-v4.1-flash"
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    @property
    def is_google_oauth_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def is_nvidia_nim_configured(self) -> bool:
        return bool(self.NVIDIA_API_KEY.strip())

    @field_validator("GOOGLE_OAUTH_SCOPES")
    @classmethod
    def validate_google_oauth_scopes(cls, scopes: List[str]) -> List[str]:
        joined = " ".join(scopes)
        if "meetings.conference.readonly" in joined:
            raise ValueError("Use meetings.space.readonly for Meet REST access.")
        if "drive" in joined:
            raise ValueError("Drive scopes require an explicit transcript-file implementation.")
        return scopes

settings = Settings()
