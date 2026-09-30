from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import Column, DateTime, Index, String, Text

from app.core.database import Base


def generate_feedback_id() -> str:
    return f"ctxfb_{uuid.uuid4().hex[:12]}"


class ContextFeedback(Base):
    """Persistent audit and reusable human classification feedback.

    Records when a user confirms, corrects, or overrides a project routing decision.
    Retrieved in future semantic resolution to anchor and train retrieval priors
    without mutating underlying model weights.
    """

    __tablename__ = "context_feedbacks"

    id = Column(String(64), primary_key=True, default=generate_feedback_id)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    workspace_id = Column(String(64), default="ws_default", nullable=True)

    source_event_id = Column(String(255), nullable=True, index=True)
    resolution_id = Column(String(64), nullable=True, index=True)
    evidence_id = Column(String(64), nullable=True, index=True)

    original_predicted_project_id = Column(String(64), nullable=True)
    selected_project_id = Column(String(64), nullable=True, index=True)

    action = Column(String(64), nullable=False)  # "assigned", "dismissed", "kept_unknown", "project_created"
    actor_id = Column(String(255), default="user", nullable=False)
    reason = Column(Text, default="", nullable=False)
    text_snippet = Column(Text, default="", nullable=False)
    model_version = Column(String(128), default="", nullable=False)
    metadata_json = Column(Text, default="{}", nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_ctxfb_tenant_selected", "tenant_id", "selected_project_id"),
        Index("ix_ctxfb_action_created", "action", "created_at"),
    )

    def get_metadata(self) -> Dict[str, Any]:
        try:
            return json.loads(self.metadata_json or "{}")
        except Exception:
            return {}
