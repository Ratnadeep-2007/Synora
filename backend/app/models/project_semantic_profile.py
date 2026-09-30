from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.core.database import Base


def generate_semantic_profile_id() -> str:
    return f"semprof_{uuid.uuid4().hex[:12]}"


class ProjectSemanticProfile(Base):
    """Rich semantic profile for a project.

    Used by Gemini-embedding-2 and Context Intelligence to form a robust,
    multi-dimensional identity that transcends simple keyword or project name matching.
    """

    __tablename__ = "project_semantic_profiles"

    id = Column(String(64), primary_key=True, default=generate_semantic_profile_id)
    project_id = Column(String(64), unique=True, index=True, nullable=False)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    workspace_id = Column(String(64), default="ws_default", index=True, nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text, default="", nullable=False)
    domain = Column(String(255), default="", nullable=False)
    aliases_json = Column(Text, default="[]", nullable=False)
    business_concepts_json = Column(Text, default="[]", nullable=False)
    technical_concepts_json = Column(Text, default="[]", nullable=False)
    important_entities_json = Column(Text, default="[]", nullable=False)
    architecture_concepts_json = Column(Text, default="[]", nullable=False)
    requirements_summary_json = Column(Text, default="[]", nullable=False)
    decisions_summary_json = Column(Text, default="[]", nullable=False)
    visual_concepts_json = Column(Text, default="[]", nullable=False)
    representative_evidence_json = Column(Text, default="[]", nullable=False)
    historical_feedback_json = Column(Text, default="[]", nullable=False)

    embedding_vector_json = Column(Text, default="[]", nullable=False)
    embedding_model = Column(String(128), default="gemini-embedding-2", nullable=False)

    state_version = Column(Integer, default=1, nullable=False)
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
        Index("ix_semprof_tenant_project", "tenant_id", "project_id"),
        Index("ix_semprof_state_version", "project_id", "state_version"),
    )

    def get_aliases(self) -> List[str]:
        try:
            return json.loads(self.aliases_json or "[]")
        except Exception:
            return []

    def get_business_concepts(self) -> List[str]:
        try:
            return json.loads(self.business_concepts_json or "[]")
        except Exception:
            return []

    def get_technical_concepts(self) -> List[str]:
        try:
            return json.loads(self.technical_concepts_json or "[]")
        except Exception:
            return []

    def get_important_entities(self) -> List[str]:
        try:
            return json.loads(self.important_entities_json or "[]")
        except Exception:
            return []

    def get_architecture_concepts(self) -> List[str]:
        try:
            return json.loads(self.architecture_concepts_json or "[]")
        except Exception:
            return []

    def get_embedding_vector(self) -> List[float]:
        try:
            return json.loads(self.embedding_vector_json or "[]")
        except Exception:
            return []

    @property
    def business_concepts(self) -> List[str]:
        return self.get_business_concepts()

    @property
    def technical_concepts(self) -> List[str]:
        return self.get_technical_concepts()

    @property
    def important_entities(self) -> List[str]:
        return self.get_important_entities()

    @property
    def aliases(self) -> List[str]:
        return self.get_aliases()


    def to_composite_text(self) -> str:
        """Flatten profile into a rich text corpus for semantic embedding and reranking."""
        parts = [
            f"Project: {self.name}",
            f"Description: {self.description}",
            f"Domain: {self.domain}",
        ]
        aliases = self.get_aliases()
        if aliases:
            parts.append(f"Aliases: {', '.join(aliases)}")
        biz = self.get_business_concepts()
        if biz:
            parts.append(f"Business Concepts: {', '.join(biz)}")
        tech = self.get_technical_concepts()
        if tech:
            parts.append(f"Technical Concepts: {', '.join(tech)}")
        entities = self.get_important_entities()
        if entities:
            parts.append(f"Important Entities: {', '.join(entities)}")
        arch = self.get_architecture_concepts()
        if arch:
            parts.append(f"Architecture Concepts: {', '.join(arch)}")
        return "\n".join(parts)
