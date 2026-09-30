from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.context_feedback import ContextFeedback
from app.models.project_semantic_profile import ProjectSemanticProfile

logger = logging.getLogger(__name__)


class ContextFeedbackService:
    """Manages persistent human classification feedback.

    Stores user corrections, triage actions, and confirmations as reusable
    knowledge for retrieval-augmented classification.
    """

    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def record_feedback(
        self,
        db: Optional[Session] = None,
        selected_project_id: Optional[str] = None,
        action: str = "assigned",  # assigned | dismissed | kept_unknown | project_created
        actor_id: str = "user",
        reason: str = "",
        text_snippet: str = "",
        source_event_id: Optional[str] = None,
        original_predicted_project_id: Optional[str] = None,
        resolution_id: Optional[str] = None,
        evidence_id: Optional[str] = None,
        tenant_id: str = "default_tenant",
        workspace_id: str = "ws_default",
        model_version: str = "gemini-3.8-flash",
    ) -> ContextFeedback:
        """Record an explicit human triage or assignment action."""
        session = db or self.db
        if not session:
            raise ValueError("Database session required")

        feedback = ContextFeedback(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            source_event_id=source_event_id,
            resolution_id=resolution_id,
            evidence_id=evidence_id,
            original_predicted_project_id=original_predicted_project_id,
            selected_project_id=selected_project_id,
            action=action,
            actor_id=actor_id,
            reason=reason or f"Human action: {action}",
            text_snippet=(text_snippet or "")[:500],
            model_version=model_version,
            created_at=datetime.now(timezone.utc),
        )
        db.add(feedback)

        # Update ProjectSemanticProfile's historical feedback cache if assigned to a project
        if selected_project_id:
            profile = (
                db.query(ProjectSemanticProfile)
                .filter(ProjectSemanticProfile.project_id == selected_project_id)
                .first()
            )
            if profile:
                try:
                    existing = json.loads(profile.historical_feedback_json or "[]")
                    entry = {
                        "text": text_snippet[:150],
                        "reason": reason[:100],
                        "actor": actor_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    existing.insert(0, entry)
                    profile.historical_feedback_json = json.dumps(existing[:10])
                except Exception as exc:
                    logger.warning("failed_to_append_feedback_to_profile: %s", exc)

        db.commit()
        db.refresh(feedback)
        logger.info(
            "context_feedback_recorded: action=%s project=%s actor=%s",
            action,
            selected_project_id,
            actor_id,
        )
        return feedback

    def get_recent_feedback(
        self,
        db: Session,
        project_id: Optional[str] = None,
        limit: int = 10,
        tenant_id: str = "default_tenant",
    ) -> List[ContextFeedback]:
        """Fetch recent feedback records for audit or prompting."""
        query = db.query(ContextFeedback).filter(ContextFeedback.tenant_id == tenant_id)
        if project_id:
            query = query.filter(ContextFeedback.selected_project_id == project_id)
        return query.order_by(ContextFeedback.created_at.desc()).limit(limit).all()

    def get_feedback_for_prompt(
        self,
        db_or_pids: Any,
        candidate_project_ids: Optional[List[str]] = None,
        limit_per_project: int = 3,
        db: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """Format historical human decisions as prompt guidance for the semantic reranker."""
        session = db or self.db
        if isinstance(db_or_pids, Session):
            session = db_or_pids
            pids = candidate_project_ids or []
        else:
            pids = db_or_pids or []

        if not session or not pids:
            return []
        rows = (
            session.query(ContextFeedback)
            .filter(
                ContextFeedback.tenant_id == getattr(session.get_bind(), "tenant_id", "default_tenant")
                if False else ContextFeedback.selected_project_id.in_(pids),
                ContextFeedback.action.in_(["assigned", "project_created"]),
            )
            .order_by(ContextFeedback.created_at.desc())
            .limit(limit_per_project * len(pids))
            .all()
        )
        out = []
        for r in rows:
            out.append({
                "project_id": r.selected_project_id,
                "text": r.text_snippet[:120],
                "reason": r.reason,
            })
        return out

