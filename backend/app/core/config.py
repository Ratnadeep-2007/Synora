from typing import List, Optional
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
    # Design authority: Meta Muse Spark (muse-spark-1.3-contributor) with
    # complete per-project freedom. Falls through to the next configured
    # provider when Meta is not yet configured.
    # Supported: meta | gemini | groq | nvidia | deterministic
    LLM_PROVIDER: str = Field(default="meta", description="meta | gemini | groq | nvidia | deterministic")
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-2"
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"

    # Secondary failover providers: NVIDIA NIM & Groq
    NVIDIA_API_KEY: str = ""
    NVIDIA_MODEL: str = "deepseek-ai/deepseek-v4.1-flash"
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    # Design authority: Meta Muse Spark via Meta Model API
    # (https://api.meta.ai/v1, OpenAI-compatible Chat Completions).
    # Until META_API_KEY is supplied the client is never built and selection
    # falls through to Groq. Get a key from the Model API dashboard.
    # Note: the -contributor tier trades a lower price for permission to
    # train on prompts; use muse-spark-1.3 (Standard) if that is unacceptable.
    META_API_KEY: str = ""
    META_BASE_URL: str = "https://api.meta.ai/v1"
    META_MODEL: str = "muse-spark-1.3-contributor"

    # Visual design authority: "free" gives the design model complete freedom
    # per project - ungrounded nodes render, critique findings are recorded but
    # do not block. "grounded" would keep grounding enforcement and the critique
    # gate. Meta is the design authority, so free is the correct default.
    VISUAL_DESIGN_MODE: str = Field(default="free")

    # Groq high-speed Whisper audio & LLM provider
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_WHISPER_MODEL: str = "whisper-large-v3-turbo"
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Zero-touch Google Meet connection refresh token
    GOOGLE_REFRESH_TOKEN: str = ""

    # Server-side Google Meet capture + post-meeting Sarvam STT
    VEXA_ENABLED: bool = False
    VEXA_BASE_URL: str = "http://localhost:18056"
    VEXA_API_KEY: str = ""
    VEXA_BOT_NAME: str = "Synora"
    VEXA_POLL_INTERVAL_SECONDS: int = Field(default=10, ge=2, le=300)
    VEXA_MAX_WAIT_SECONDS: int = Field(default=14400, ge=60)
    VEXA_HTTP_TIMEOUT_SECONDS: float = Field(default=30.0, gt=1)
    VEXA_RECORDING_DOWNLOAD_TIMEOUT_SECONDS: float = Field(default=900.0, gt=10)

    SARVAM_API_KEY: str = ""
    SARVAM_STT_MODEL: str = "saaras:v4"
    SARVAM_STT_MODE: str = "codemix"
    SARVAM_WITH_DIARIZATION: bool = True
    SARVAM_LANGUAGE_CODE: str = ""
    SARVAM_NUM_SPEAKERS: Optional[int] = Field(default=None, ge=1, le=20)
    SARVAM_KEYTERMS: str = ""
    SARVAM_POLL_INTERVAL_SECONDS: int = Field(default=5, ge=2, le=300)
    SARVAM_MAX_WAIT_SECONDS: int = Field(default=3600, ge=60)
    SARVAM_HTTP_TIMEOUT_SECONDS: float = Field(default=60.0, gt=1)
    SARVAM_UPLOAD_TIMEOUT_SECONDS: float = Field(default=900.0, gt=10)

    # Self-hosted Whisper fallback. Loaded only when Sarvam is unavailable or fails.
    WHISPER_ENABLED: bool = True
    WHISPER_MODEL: str = "large-v3-turbo"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"
    WHISPER_LANGUAGE_CODE: str = ""
    WHISPER_INITIAL_PROMPT: str = ""
    WHISPER_BEAM_SIZE: int = Field(default=5, ge=1, le=10)
    WHISPER_VAD_FILTER: bool = True
    WHISPER_CPU_THREADS: int = Field(default=4, ge=1, le=64)
    WHISPER_MODEL_CACHE_DIR: str = "/app/.cache/whisper"

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
    # Memory-to-canvas reconciliation: how often the background loop checks
    # whether approved project memory has outrun the visual workspace.
    VISUAL_SYNC_INTERVAL_SECONDS: int = Field(default=30, ge=5, le=3600)
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

    @property
    def is_meta_configured(self) -> bool:
        return bool(self.META_API_KEY.strip() and self.META_BASE_URL.strip())

    @property
    def visual_design_free(self) -> bool:
        return str(self.VISUAL_DESIGN_MODE or "").strip().lower() == "free"


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
