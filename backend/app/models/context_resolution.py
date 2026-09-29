from datetime import datetime, timezone
from enum import Enum
import json
from typing import Optional
import uuid
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_resolution_id() -> str:
    return f"ctxres_{uuid.uuid4().hex[:12]}"


def generate_unknown_item_id() -> str:
    return f"unk_{uuid.uuid4().hex[:12]}"


def generate_match_id() -> str:
    return f"pmatch_{uuid.uuid4().hex[:12]}"


class ContextDecision(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"
    CASUAL_IGNORED = "casual_ignored"


class UnknownItemStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    KEPT = "kept"
    DISMISSED = "dismissed"


class ContextResolution(Base):
    """Audit record of one Context Intelligence resolution attempt.

    Captures deterministic and semantic signals, the chosen project (if any),
    confidence/margin, and whether human review is required. This is the
    provenance trail answering "why did Synora think this belonged here?".
    """

    __tablename__ = "context_resolutions"

    id = Column(String(64), primary_key=True, default=generate_resolution_id)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    workspace_id = Column(String(64), default="ws_default", nullable=True)
    source = Column(String(64), index=True, nullable=False)
    source_event_id = Column(String(255), index=True, nullable=True)
    evidence_id = Column(String(64), nullable=True, index=True)
    project_id = Column(String(64), nullable=True, index=True)
    decision = Column(String(32), default=ContextDecision.UNKNOWN.value, index=True, nullable=False)
    confidence = Column(Float, default=0.0, nullable=False)
    margin = Column(Float, default=0.0, nullable=False)
    signals_json = Column(Text, default="[]", nullable=False)
    candidate_projects_json = Column(Text, default="[]", nullable=False)
    reason = Column(Text, default="", nullable=False)
    requires_human_review = Column(Boolean, default=True, nullable=False)
    model = Column(String(64), nullable=True)
    model_version = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_context_resolution_source_event", "source", "source_event_id"),
        Index("ix_context_resolution_decision", "tenant_id", "decision"),
    )

    @property
    def context_status(self) -> str:
        return self.decision

    @context_status.setter
    def context_status(self, val: str) -> None:
        self.decision = val

    @property
    def resolved_project_id(self) -> Optional[str]:
        return self.project_id

    @resolved_project_id.setter
    def resolved_project_id(self, val: Optional[str]) -> None:
        self.project_id = val

    @property
    def explanation(self) -> str:
        return self.reason

    @explanation.setter
    def explanation(self, val: str) -> None:
        self.reason = val

    @property
    def deterministic_signals_json(self) -> str:
        try:
            sigs = json.loads(self.signals_json or "[]")
            return json.dumps([s for s in sigs if isinstance(s, dict) and s.get("kind") in ("deterministic", "authorization")])
        except Exception:
            return "[]"

    @property
    def semantic_signals_json(self) -> str:
        try:
            sigs = json.loads(self.signals_json or "[]")
            return json.dumps([s for s in sigs if isinstance(s, dict) and s.get("kind") in ("semantic", "continuity", "visual")])
        except Exception:
            return "[]"

    def __repr__(self) -> str:
        return (
            f"<ContextResolution id={self.id} source={self.source} "
            f"decision={self.decision} project={self.project_id}>"
        )


class UnknownContextItem(Base):
    """Source evidence that could not be confidently mapped to a project.

    Lives in the reserved system project and preserves full original
    provenance (source, sender, timestamp, evidence id). Human review can
    assign it, keep it, create a project from it, or dismiss it.
    """

    __tablename__ = "unknown_context_items"

    id = Column(String(64), primary_key=True, default=generate_unknown_item_id)
    project_id = Column(String(64), index=True, nullable=False)
    tenant_id = Column(String(64), default="default_tenant", index=True, nullable=False)
    source = Column(String(64), index=True, nullable=False)
    source_event_id = Column(String(255), index=True, nullable=True)
    evidence_id = Column(String(64), nullable=True, index=True)
    meeting_id = Column(String(64), nullable=True, index=True)
    actor_id = Column(String(255), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=True)
    content = Column(Text, default="", nullable=False)
    payload_json = Column(Text, default="{}", nullable=False)
    context_resolution_id = Column(String(64), nullable=True, index=True)
    status = Column(String(32), default=UnknownItemStatus.PENDING.value, index=True, nullable=False)
    assigned_project_id = Column(String(64), nullable=True, index=True)
    assigned_by = Column(String(255), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    matches = relationship(
        "PossibleProjectMatch",
        back_populates="unknown_item",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_unknown_item_status", "tenant_id", "status"),
        Index("ix_unknown_item_source_event", "source", "source_event_id"),
    )

    def __repr__(self) -> str:
        return f"<UnknownContextItem id={self.id} source={self.source} status={self.status}>"


class PossibleProjectMatch(Base):
    """Explainable suggestion that an Unknown Context item belongs to a project.

    Similarity is a suggestion, never authorization. Reasons are stored so the
    UI can explain WHY a project is suggested instead of showing a raw score.
    """

    __tablename__ = "possible_project_matches"

    id = Column(String(64), primary_key=True, default=generate_match_id)
    unknown_item_id = Column(
        String(64),
        ForeignKey("unknown_context_items.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    candidate_project_id = Column(String(64), index=True, nullable=False)
    similarity_reason_json = Column(Text, default="[]", nullable=False)
    supporting_evidence_ids_json = Column(Text, default="[]", nullable=False)
    supporting_state_sections_json = Column(Text, default="[]", nullable=False)
    conflicts_json = Column(Text, default="[]", nullable=False)
    recommendation = Column(String(32), default="review", nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    unknown_item = relationship("UnknownContextItem", back_populates="matches")

    __table_args__ = (
        Index("ix_possible_match_item", "unknown_item_id", "candidate_project_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PossibleProjectMatch id={self.id} item={self.unknown_item_id} "
            f"candidate={self.candidate_project_id}>"
        )
