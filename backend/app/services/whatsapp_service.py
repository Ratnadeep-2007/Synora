from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.project import Project
from app.services.audit_service import AuditService
from app.services.excalidraw_service import ExcalidrawService
from app.services.ingestion_service import IngestionService
from app.services.multimodal_service import MultimodalService
from app.services.project_agent_service import ProjectAgentService
from app.services.source_intelligence_pipeline import SourceIntelligencePipeline

logger = logging.getLogger(__name__)


class WhatsAppIntelligenceService:
    """
    Intelligent WhatsApp Ingestion & Disambiguation Service.
    
    Responsibilities:
    1. Ingest WhatsApp Group messages via Baileys Webhook or REST sync.
    2. Understand which Project people are discussing across the portfolio.
    3. Persist immutable Evidence with provenance linking.
    4. Extract Candidate Decisions & Architectural Requirements.
    5. Automatically apply corresponding visual updates to the target Project's Excalidraw whiteboard!
    """

    def __init__(
        self,
        ingestion_service: Optional[IngestionService] = None,
        excal_service: Optional[ExcalidrawService] = None,
        agent_service: Optional[ProjectAgentService] = None,
        audit_service: Optional[AuditService] = None,
        pipeline: Optional["SourceIntelligencePipeline"] = None,
        multimodal_service: Optional[MultimodalService] = None,
    ):
        self.ingestion_service = ingestion_service or IngestionService()
        self.excal_service = excal_service or ExcalidrawService()
        self.agent_service = agent_service or ProjectAgentService()
        self.audit_service = audit_service or AuditService()
        self.pipeline = pipeline or SourceIntelligencePipeline(
            ingestion_service=self.ingestion_service
        )
        self.multimodal = multimodal_service or MultimodalService()


    REACTION_EVENT_TYPES = {
        "reaction", "message_reaction", "reaction_add", "reaction_remove",
    }

    POSITIVE_REACTIONS = {"👍", "✅", "❤️", "🎉", "👏", "🙏", "💯", "+1", "thumbsup", "heart"}
    NEGATIVE_REACTIONS = {"👎", "❌", "👿", "😡", "-1", "thumbsdown"}
    ACK_REACTIONS = {"👀", "✅", "👍", "🫡", "noted", "seen", "ack"}

    def process_incoming_message(
        self,
        payload: Dict[str, Any],
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> Dict[str, Any]:
        """
        End-to-end processing of a WhatsApp group chat message.

        Delegates to the shared source intelligence pipeline so WhatsApp uses
        the SAME Context Intelligence and Knowledge Intelligence services as
        Google Meet. This method keeps no project-matching algorithm of its own.
        """
        reaction = self._extract_reaction(payload)
        if reaction is not None:
            return self._record_reaction_feedback(reaction, db, tenant_id=tenant_id)

        sender_name = payload.get("sender_name") or payload.get("pushName") or "WhatsApp User"
        sender_jid = payload.get("sender_jid") or "unknown@s.whatsapp.net"
        group_name = payload.get("group_name") or "WhatsApp Group"
        group_jid = payload.get("group_jid") or "unknown@g.us"
        message_id = payload.get("message_id") or payload.get("id") or f"wamid_{int(datetime.now().timestamp() * 1000)}"

        # Pre-process multimodal content (Voice notes via Groq Whisper, Diagram images via Llama Vision)
        raw_text, multimodal_meta = self.multimodal.process_incoming_payload(payload)

        if not raw_text.strip():
            return {
                "ok": False,
                "message": "Empty message ignored",
                "processed": False,
            }

        # Deterministic filter: casual chit-chat never becomes project evidence.
        if self._is_casual_chitchat(raw_text):
            logger.info(
                f"WhatsApp message from '{sender_name}' in '{group_name}' flagged as casual chit-chat. "
                "Leaving project evidence untouched."
            )
            return {
                "ok": True,
                "processed": False,
                "status": "ignored",
                "reason": "Casual conversation / non-project chit-chat (leave it)",
                "matched_project": None,
                "confidence": 0.0,
                "excalidraw_updated": False,
                "message": "Message ignored: casual chit-chat detected. All project evidence left untouched.",
            }

        continuity = self._conversation_continuity(
            group_name, raw_text, db, tenant_id,
            group_jid=group_jid, sender_jid=sender_jid,
        )

        meta_dict: Dict[str, Any] = {
            "group_name": group_name,
            "sender_jid": sender_jid,
        }
        if multimodal_meta:
            meta_dict["multimodal"] = multimodal_meta

        outcome = self.pipeline.process(
            source="whatsapp",
            payload={
                "message_id": message_id,
                "text": raw_text,
                "sender_name": sender_name,
                "sender_jid": sender_jid,
                "group_name": group_name,
                "group_jid": group_jid,
            },
            db=db,
            tenant_id=tenant_id,
            actor_id=sender_name,
            source_event_id=message_id,
            event_type="group_message",
            occurred_at=datetime.now(timezone.utc),
            continuity_context=continuity,
            metadata=meta_dict,
        )


        if outcome.outcome == "unknown_context":
            logger.info(
                "whatsapp_routed_unknown_context: message_id=%s item=%s reason=%s",
                message_id,
                outcome.unknown_item_id,
                outcome.reason,
            )
            return {
                "ok": True,
                "processed": True,
                "status": "unknown_context",
                "reason": outcome.reason,
                "matched_project": None,
                "unknown_item_id": outcome.unknown_item_id,
                "evidence_id": outcome.evidence_id,
                "confidence": 0.0,
                "excalidraw_updated": False,
                "multimodal": multimodal_meta or None,
                "message": "Message preserved in Unknown Context for human review.",
            }

        if outcome.outcome == "ignored":
            return {
                "ok": True,
                "processed": False,
                "status": "ignored",
                "reason": outcome.reason or "Casual conversation / non-project chit-chat (leave it)",
                "matched_project": None,
                "confidence": 0.0,
                "excalidraw_updated": False,
                "multimodal": multimodal_meta or None,
                "message": "Message ignored: casual chit-chat detected. All project evidence left untouched.",
            }

        if outcome.outcome == "duplicate":
            return {
                "ok": True,
                "processed": False,
                "status": "duplicate",
                "reason": outcome.reason,
                "matched_project": None,
                "confidence": 0.0,
                "excalidraw_updated": False,
                "message": "Duplicate message ignored (already processed).",
            }

        if outcome.outcome == "ignored":
            return {
                "ok": True,
                "processed": False,
                "status": "ignored",
                "reason": outcome.reason,
                "matched_project": None,
                "confidence": 0.0,
                "excalidraw_updated": False,
                "message": "Message ignored: casual chit-chat detected. All project evidence left untouched.",
            }

        project_id = outcome.project_id
        matched_project = db.query(Project).filter(Project.id == project_id).first()
        confidence = 1.0

        auto_apply = bool(
            payload.get("auto_apply_diagram", getattr(settings, "AUTO_APPLY_VISUAL_UPDATES", False))
        )

        proposal = None
        diagram_res = None
        excalidraw_updated = False

        if auto_apply:
            try:
                diagram_res = self.excal_service.generate_diagram_from_text(
                    project_id=project_id,
                    text=raw_text,
                    db=db,
                    tenant_id=tenant_id,
                    auto_apply=True,
                    actor_id=sender_name or "whatsapp_agent",
                )
                excalidraw_updated = bool(
                    diagram_res.get("auto_applied")
                    or diagram_res.get("applied")
                    or diagram_res.get("success")
                )
            except Exception as exc:
                logger.error(f"Error auto-applying Excalidraw diagram from WhatsApp: {exc}")
                excalidraw_updated = False
        else:
            # Visual changes are proposal-first when auto_apply is False:
            # the living workspace is not mutated without human review.
            proposal = self._propose_visual_update(
                project_id=project_id,
                db=db,
                tenant_id=tenant_id,
                reason=f"WhatsApp update from '{sender_name}' in group '{group_name}'",
            )

        self.audit_service.record_event(
            action="whatsapp_group_message_processed",
            actor_id=sender_name,
            resource_type="project_evidence",
            resource_id=outcome.evidence_id,
            db=db,
            tenant_id=tenant_id,
            after_state={
                "project_id": project_id,
                "project_name": matched_project.name if matched_project else None,
                "ai_status": outcome.ai_status,
                "candidates_created": outcome.candidates_created,
                "visual_proposal_id": proposal.id if proposal else None,
                "excalidraw_updated": excalidraw_updated,
            },
        )

        msg_str = (
            f"Routed to project '{matched_project.name if matched_project else project_id}'."
        )
        if excalidraw_updated:
            msg_str += " Excalidraw whiteboard automatically updated with new architecture diagram."
        elif proposal:
            msg_str += " Visual changes are pending human review."

        return {
            "ok": True,
            "processed": True,
            "message_id": message_id,
            "matched_project": (
                {"id": matched_project.id, "name": matched_project.name}
                if matched_project
                else None
            ),
            "confidence": confidence,
            "reasoning": outcome.reason,
            "ai_status": outcome.ai_status,
            "evidence_id": outcome.evidence_id,
            "candidate_id": None,
            "candidates_created": outcome.candidates_created,
            "excalidraw_updated": excalidraw_updated,
            "visual_proposal_pending": proposal is not None,
            "proposal_id": proposal.id if proposal else None,
            "diagram": diagram_res,
            "multimodal": multimodal_meta or None,
            "message": msg_str,
        }

    def _conversation_continuity(
        self, group_name: str, raw_text: str, db: Session, tenant_id: str,
        group_jid: Optional[str] = None, sender_jid: Optional[str] = None,
    ) -> str:
        """Shared continuity window: same-group thread + cross-source context.

        Group-scoped first (same group_jid/name), then recent Meet discussion
        so a short reply resolves against the conversation it continues.
        """
        from app.services.conversation_continuity import build_continuity_window

        try:
            return build_continuity_window(
                db=db,
                tenant_id=tenant_id,
                group_name=group_name,
                group_jid=group_jid,
                current_text=raw_text,
                actor_jid=sender_jid,
            )
        except Exception:
            return ""

    def _propose_visual_update(
        self, project_id: str, db: Session, tenant_id: str, reason: str
    ):
        """Create a pending visual proposal. Never auto-applies a change."""
        try:
            state = self.agent_service.state_service.get_or_create_state(project_id, db)
            return self.excal_service.generate_proposal_from_state(
                project_id=project_id,
                state_version=state.current_version,
                db=db,
                tenant_id=tenant_id,
                reason=reason,
            )
        except Exception as exc:
            logger.warning(
                "whatsapp_visual_proposal_deferred: project=%s error=%s", project_id, exc
            )
            return None

    def _is_casual_chitchat(self, text: str) -> bool:
        """
        Detects casual non-project banter, greetings, food/lunch talk,
        meeting link requests, and short acknowledgments.
        Returns True if the message should be completely ignored (leave it).
        Delegates to the shared gate so every source behaves identically.
        """
        from app.services.context_intelligence import ContextIntelligenceService

        return ContextIntelligenceService.is_casual_chatter(text)

    # ------------------------------------------------------------------
    # Reactions as human feedback signals
    # ------------------------------------------------------------------
    def _extract_reaction(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Detect a Baileys reaction event (emoji vote on an earlier message)."""
        event_type = str(payload.get("event_type", "") or "").lower()
        message_type = str(payload.get("message_type", "") or payload.get("type", "") or "").lower()
        emoji = (
            payload.get("reaction")
            or payload.get("emoji")
            or payload.get("reaction_emoji")
            or (payload.get("reaction_body") if isinstance(payload.get("reaction_body"), str) else None)
        )
        target = (
            payload.get("target_message_id")
            or payload.get("react_to")
            or payload.get("quoted_message_id")
        )
        nested = payload.get("reaction_message") or payload.get("reactionMessage")
        if isinstance(nested, dict):
            emoji = emoji or nested.get("text") or nested.get("emoji")
            target = target or nested.get("key", {}).get("id") if isinstance(nested.get("key"), dict) else target
        is_reaction_shape = (
            event_type in self.REACTION_EVENT_TYPES
            or message_type in self.REACTION_EVENT_TYPES
            or (emoji and target)
        )
        if not is_reaction_shape:
            return None
        if not emoji or not target:
            return None
        return {
            "emoji": str(emoji).strip(),
            "target_message_id": str(target).strip(),
            "sender_name": payload.get("sender_name") or payload.get("pushName") or "WhatsApp User",
            "sender_jid": payload.get("sender_jid") or "unknown@s.whatsapp.net",
            "group_name": payload.get("group_name") or "WhatsApp Group",
            "group_jid": payload.get("group_jid") or "unknown@g.us",
            "removed": bool(payload.get("removed", False)) or event_type == "reaction_remove",
        }

    def _record_reaction_feedback(
        self, reaction: Dict[str, Any], db: Session, tenant_id: str = "default_tenant"
    ) -> Dict[str, Any]:
        """Persist an emoji reaction as auditable human feedback.

        A reaction never creates Evidence or candidate knowledge and never
        moves anything between projects. It is recorded as audit + feedback
        metadata on the target source event so agreement (👍/✅), rejection
        (👎/❌) and acknowledgement (👀) stay visible to reviewers.
        """
        from app.models.source_event import SourceEvent

        emoji = reaction["emoji"]
        target_id = reaction["target_message_id"]
        sender = reaction["sender_name"]
        sentiment = "neutral"
        if emoji in self.POSITIVE_REACTIONS:
            sentiment = "positive"
        elif emoji in self.NEGATIVE_REACTIONS:
            sentiment = "negative"
        elif emoji in self.ACK_REACTIONS:
            sentiment = "acknowledged"

        event = (
            db.query(SourceEvent)
            .filter(
                SourceEvent.source == "whatsapp",
                SourceEvent.source_event_id == target_id,
            )
            .first()
        )
        feedback = {
            "emoji": emoji,
            "sentiment": sentiment,
            "sender_name": sender,
            "sender_jid": reaction["sender_jid"],
            "removed": reaction["removed"],
        }
        if event is not None:
            try:
                stored = json.loads(event.payload_json) if event.payload_json else {}
            except Exception:
                stored = {}
            reactions = stored.get("reactions") if isinstance(stored, dict) else None
            if not isinstance(reactions, list):
                reactions = []
            reactions.append(feedback)
            stored["reactions"] = reactions[-20:]
            event.payload_json = json.dumps(stored, default=str)
            db.commit()
            project_id = event.project_id
        else:
            project_id = None

        self.audit_service.record_event(
            action="whatsapp_reaction_feedback",
            actor_id=sender,
            resource_type="whatsapp_message",
            resource_id=target_id,
            db=db,
            tenant_id=tenant_id,
            after_state={**feedback, "project_id": project_id},
        )
        logger.info(
            "whatsapp_reaction_recorded: target=%s emoji=%s sentiment=%s actor=%s",
            target_id, emoji, sentiment, sender,
        )
        return {
            "ok": True,
            "processed": True,
            "status": "reaction_feedback",
            "emoji": emoji,
            "sentiment": sentiment,
            "target_message_id": target_id,
            "matched_project": {"id": project_id} if project_id else None,
            "confidence": 0.0,
            "excalidraw_updated": False,
            "message": f"Reaction {emoji} recorded as {sentiment} feedback.",
        }

    def _clean_summary(self, text: str, prefix: str = "") -> str:
        """Helper to create a neat 1-line summary title from message text."""
        cleaned = re.sub(r"\[.*?\]|#\w+|@\w+", "", text).strip()
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        first_line = lines[0] if lines else cleaned
        # Strip conversational fillers
        first_line = re.sub(r"^(?:team,?|hey,?|hi,?|everyone,?)\s*", "", first_line, flags=re.IGNORECASE)

        # Check for core decision / action clause
        core_match = re.search(
            r"(?:we have decided to|we decided to|decided to|agreed to|confirmed that|confirmed:|let's|switch to|integrate|add)\s+([^.,;\n]+)",
            first_line,
            re.IGNORECASE,
        )
        if core_match:
            action_phrase = core_match.group(0).strip()
            action_phrase = action_phrase[0].upper() + action_phrase[1:]
            if len(action_phrase) > 70:
                return prefix + action_phrase[:67] + "..."
            return prefix + action_phrase

        if len(first_line) > 70:
            return prefix + first_line[:67] + "..."
        return prefix + first_line
