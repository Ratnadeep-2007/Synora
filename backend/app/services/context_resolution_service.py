"""Reusable, source-agnostic ContextResolutionService (Enterprise Part 1).

Shared context intelligence layer used by:
- Google Meet
- WhatsApp
- Excalidraw
- Slack / Webhooks

Decides what an incoming message, transcript segment, or visual diagram is
about and routes it to the correct project or system Unknown Context.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.project import Project
from app.schemas.context import ContextResolutionResult, ContextSignal
from app.services.context_intelligence import ContextIntelligenceService
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)


class ContextResolutionService(ContextIntelligenceService):
    """The canonical, source-agnostic Context Resolution service.

    Inputs support:
    - source (google_meet | whatsapp | excalidraw | slack)
    - source_event / payload
    - content
    - conversation/segment context (continuity_context)
    - sender/participants
    - group/channel
    - meeting metadata
    - current Excalidraw context
    - candidate projects
    - tenant / workspace
    - authorization constraints

    Outputs:
    ContextResolutionResult {
        resolved_project_id: Optional[str],
        status: "resolved" | "ambiguous" | "unresolved",
        confidence: float,
        candidates: [...],
        signals: [...],
        reasoning_summary: str,
        requires_human_review: bool
    }
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        super().__init__(llm_client=llm_client)

    def resolve_context(
        self,
        source: str,
        content: Optional[str] = None,
        source_event: Optional[Any] = None,
        conversation_context: Optional[str] = None,
        sender_participants: Optional[List[str]] = None,
        group_channel: Optional[str] = None,
        meeting_metadata: Optional[Dict[str, Any]] = None,
        current_excalidraw_context: Optional[Dict[str, Any]] = None,
        candidate_projects: Optional[List[Project]] = None,
        tenant_id: str = "default_tenant",
        workspace_id: str = "ws_default",
        authorization_constraints: Optional[Dict[str, Any]] = None,
        trusted_project_id: Optional[str] = None,
        source_event_id: Optional[str] = None,
        db: Optional[Session] = None,
        record: bool = False,
        payload: Optional[Dict[str, Any]] = None,
    ) -> ContextResolutionResult:
        """Resolve incoming multi-source information into a project context.

        Constructs normalized payload dictionary and invokes the layered
        deterministic and semantic resolution engine.
        """
        built_payload: Dict[str, Any] = dict(payload or {})
        if content:
            built_payload["text"] = content
        if group_channel:
            built_payload["group"] = group_channel
        if sender_participants:
            built_payload["sender"] = sender_participants[0] if sender_participants else None
            built_payload["participants"] = sender_participants
        if meeting_metadata:
            built_payload.setdefault("meeting_metadata", meeting_metadata)
        if current_excalidraw_context:
            built_payload.setdefault("excalidraw_context", current_excalidraw_context)

        visual_context: Optional[str] = None
        if current_excalidraw_context:
            if isinstance(current_excalidraw_context, dict):
                elements = current_excalidraw_context.get("elements", [])
                visual_context = f"Excalidraw canvas with {len(elements)} elements"
            else:
                visual_context = str(current_excalidraw_context)

        actor_id = None
        if sender_participants:
            actor_id = sender_participants[0]

        if db is None:
            # Caller did not provide database session; return unknown context
            return ContextResolutionResult(
                decision="unknown",
                confidence=0.0,
                margin=0.0,
                reason="No active database session provided for context resolution",
                requires_human_review=True,
            )

        authorized_project_ids = None
        if authorization_constraints and isinstance(authorization_constraints, dict):
            authorized_project_ids = authorization_constraints.get("authorized_project_ids")

        return self.resolve(
            source=source,
            payload=built_payload,
            db=db,
            actor_id=actor_id,
            tenant_id=tenant_id,
            trusted_project_id=trusted_project_id,
            continuity_context=conversation_context,
            visual_context=visual_context,
            source_event_id=source_event_id,
            authorized_project_ids=authorized_project_ids,
            record=record,
        )


__all__ = [
    "ContextResolutionService",
    "ContextResolutionResult",
    "ContextSignal",
]
