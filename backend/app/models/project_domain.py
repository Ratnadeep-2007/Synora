from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.core.database import Base


def generate_project_domain_id() -> str:
    return f"pdomain_{uuid.uuid4().hex[:12]}"


class ProjectDomainProfile(Base):
    """Persistent evidence-backed project-domain profile.

    This is a retrieval/index layer, not authoritative Project State and not
    model training or fine-tuning.
    """

    __tablename__ = "project_domain_profiles"

    id = Column(String(64), primary_key=True, default=generate_project_domain_id)
    project_id = Column(String(64), unique=True, index=True, nullable=False)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    workspace_id = Column(String(64), default="ws_default", index=True, nullable=False)

    domain_summary = Column(Text, default="", nullable=False)
    keywords_json = Column(Text, default="[]", nullable=False)
    concepts_json = Column(Text, default="[]", nullable=False)
    evidence_ids_json = Column(Text, default="[]", nullable=False)

    state_version = Column(Integer, default=1, nullable=False)
    source_digest = Column(String(64), default="", nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_project_domain_tenant_project", "tenant_id", "project_id"),
        Index("ix_project_domain_state", "project_id", "state_version"),
    )
