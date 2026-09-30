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

    # Free runtime provider abstraction.
    # Default: Google Gemini with gemini-3.5-flash-lite and gemini-embedding-2.
    # Supported: gemini | groq | nvidia | deterministic
    LLM_PROVIDER: str = Field(default="gemini", description="gemini | groq | nvidia | deterministic")
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-2"
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"

    # Secondary failover providers: NVIDIA NIM & Groq
    NVIDIA_API_KEY: str = ""
    NVIDIA_MODEL: str = "deepseek-ai/deepseek-v4.1-flash"
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    # Groq high-speed Whisper audio & LLM provider
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_WHISPER_MODEL: str = "whisper-large-v3-turbo"
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Zero-touch Google Meet connection refresh token
    GOOGLE_REFRESH_TOKEN: str = ""

    # Context Intelligence routing gate thresholds.
    # The Agent auto-routes almost everything: only genuinely hard-to-classify
    # content (nothing remotely plausible) stays in Unknown Context. A single
    # weak-but-plausible candidate is enough for automatic assignment.
    CONTEXT_RESOLUTION_MIN_CONFIDENCE: float = Field(default=0.72)
    CONTEXT_RESOLUTION_MIN_MARGIN: float = Field(default=0.08)
    CONTEXT_RESOLUTION_AUTO_ASSIGN_MIN_CONFIDENCE: float = Field(default=0.72)
    CONTEXT_RESOLUTION_CANDIDATE_LIMIT: int = Field(default=5)
    CONTEXT_RESOLUTION_EVIDENCE_LIMIT: int = Field(default=12)
    AUTO_APPLY_VISUAL_UPDATES: bool = Field(default=True, description="Whether incoming messages auto-apply diagrams directly to Excalidraw")
    WHATSAPP_PROCESSING_INTERVAL_SECONDS: int = Field(default=60, ge=1, description="Durable processing window in seconds.")
    WHATSAPP_BATCH_POLL_SECONDS: int = Field(default=1, ge=1, description="Interval for background batch worker to poll.")
    WHATSAPP_BATCH_MAX_MESSAGES: int = Field(default=100, ge=1, le=1000)
    WHATSAPP_BATCH_MAX_RETRIES: int = Field(default=3, ge=1, le=20)
    WHATSAPP_BATCH_RETRY_SECONDS: int = Field(default=15, ge=1)
    WHATSAPP_CONTEXT_WINDOW_SIZE: int = Field(default=6, ge=1, le=50)

    model_config = SettingsConfigDict(env_file=(".env", "backend/.env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    @property
    def is_google_oauth_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def is_google_refresh_token_configured(self) -> bool:
        return bool(self.GOOGLE_REFRESH_TOKEN.strip())

    @property
    def is_nvidia_nim_configured(self) -> bool:
        return bool(self.NVIDIA_API_KEY.strip())

    @property
    def is_gemini_configured(self) -> bool:
        return bool(self.GEMINI_API_KEY.strip())

    @property
    def is_groq_configured(self) -> bool:
        return bool(self.GROQ_API_KEY.strip())


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
