from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import Column, DateTime, Index, String, Text

from app.core.database import Base


def generate_cluster_id() -> str:
    return f"uclust_{uuid.uuid4().hex[:12]}"


class UnknownCluster(Base):
    """Semantic cluster of related Unknown Context items.

    Groups orphaned or hard-to-classify source events based on embedding similarity,
    enabling atomic batch assignment or one-click project creation from a cluster.
    """

    __tablename__ = "unknown_clusters"

    id = Column(String(64), primary_key=True, default=generate_cluster_id)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    workspace_id = Column(String(64), default="ws_default", nullable=True)

    title = Column(String(255), nullable=False)
    summary = Column(Text, default="", nullable=False)
    suggested_project_id = Column(String(64), nullable=True, index=True)
    suggested_project_name = Column(String(255), nullable=True)

    item_ids_json = Column(Text, default="[]", nullable=False)
    centroid_vector_json = Column(Text, default="[]", nullable=False)

    status = Column(String(32), default="pending", nullable=False)  # pending | assigned | dismissed
    assigned_project_id = Column(String(64), nullable=True, index=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_uclust_tenant_status", "tenant_id", "status"),
        Index("ix_uclust_suggested_project", "suggested_project_id"),
    )

    def get_item_ids(self) -> List[str]:
        try:
            return json.loads(self.item_ids_json or "[]")
        except Exception:
            return []

    def set_item_ids(self, ids: List[str]) -> None:
        self.item_ids_json = json.dumps(ids)
