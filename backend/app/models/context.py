from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime, Float, Index, String, Text

from app.core.database import Base


def generate_context_resolution_id() -> str:
    return f"ctxres_{uuid.uuid4().hex[:12]}"


class ContextResolution(Base):
    """
    Auditable source-to-project context decision.

    Stores the model and deterministic signals used to resolve a source event.
    It does not grant authorization and does not itself mutate Project State.
    """
    __tablename__ = "context_resolutions"

    id = Column(String(64), primary_key=True, default=generate_context_resolution_id)
    tenant_id = Column(String(64), index=True, nullable=False, default="default_tenant")
    workspace_id = Column(String(64), index=True, nullable=False, default="ws_default")
    source_event_id = Column(String(64), index=True, nullable=True)
    context_window_id = Column(String(255), index=True, nullable=True)

    source = Column(String(64), index=True, nullable=False)
    input_hash = Column(String(64), index=True, nullable=False)

    status = Column(String(32), index=True, nullable=False)  # resolved, ambiguous, unknown
    selected_project_id = Column(String(64), index=True, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)

    candidates_json = Column(Text, nullable=False, default="[]")
    reasoning = Column(Text, nullable=True)

    model = Column(String(128), nullable=False, default="context-resolver-v3")
    prompt_version = Column(String(64), nullable=False, default="context-v3")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_ctx_res_workspace_status", "workspace_id", "status"),
        Index("ix_ctx_res_source_event", "source_event_id"),
    )
