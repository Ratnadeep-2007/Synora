from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import Column, DateTime, Index, String, Text

from app.core.database import Base


def generate_patch_id() -> str:
    return f"vpatch_{uuid.uuid4().hex[:12]}"


class VisualPatchModel(Base):
    """Persistent record of a semantic visual patch proposal and application.

    Captures high-level semantic intent (ADD_NODE, UPDATE_NODE, ADD_EDGE, etc.)
    derived from evidence and applied via the 3-way visual merge engine.
    """

    __tablename__ = "visual_patches"

    id = Column(String(64), primary_key=True, default=generate_patch_id)
    project_id = Column(String(64), index=True, nullable=False)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)

    base_revision_id = Column(String(64), nullable=True)
    target_revision_id = Column(String(64), nullable=True)

    operations_json = Column(Text, default="[]", nullable=False)
    status = Column(String(32), default="applied", nullable=False)  # proposed | applied | rejected
    safety_classification = Column(
        String(32), default="SAFE_AUTO_APPLY", nullable=False
    )  # SAFE_AUTO_APPLY | REVIEW_REQUIRED | USER_ONLY

    reason = Column(Text, default="", nullable=False)
    source_evidence_ids_json = Column(Text, default="[]", nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_vpatch_project_created", "project_id", "created_at"),
        Index("ix_vpatch_status", "status"),
    )

    def get_operations(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.operations_json or "[]")
        except Exception:
            return []

    def get_evidence_ids(self) -> List[str]:
        try:
            return json.loads(self.source_evidence_ids_json or "[]")
        except Exception:
            return []
