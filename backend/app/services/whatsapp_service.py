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

        continuity = self._conversation_continuity(group_name, raw_text, db, tenant_id)

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
        self, group_name: str, raw_text: str, db: Session, tenant_id: str
    ) -> str:
        """Recent messages from the same group, used as a context signal."""
        try:
            from app.models.source_event import SourceEvent

            recent = (
                db.query(SourceEvent)
                .filter(
                    SourceEvent.source == "whatsapp",
                    SourceEvent.tenant_id == tenant_id,
                )
                .order_by(SourceEvent.ingested_at.desc())
                .limit(8)
                .all()
            )
            lines = []
            if group_name and group_name != "WhatsApp Group":
                lines.append(f"WhatsApp Group: {group_name}")
            for ev in recent:
                try:
                    payload = json.loads(ev.payload_json)
                    body = payload.get("text", "")
                    sender = payload.get("sender_name", "")
                except Exception:
                    body = ""
                    sender = ""
                if body:
                    sender_prefix = f"{sender}: " if sender else ""
                    lines.append(f"- {sender_prefix}{body}")
            return "\n".join(lines)
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
