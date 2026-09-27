from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.project import Project
from app.services.audit_service import AuditService
from app.services.excalidraw_service import ExcalidrawService
from app.services.ingestion_service import IngestionService
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
    ):
        self.ingestion_service = ingestion_service or IngestionService()
        self.excal_service = excal_service or ExcalidrawService()
        self.agent_service = agent_service or ProjectAgentService()
        self.audit_service = audit_service or AuditService()
        self.pipeline = pipeline or SourceIntelligencePipeline(
            ingestion_service=self.ingestion_service
        )

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
        raw_text = payload.get("text") or payload.get("caption") or ""
        sender_name = payload.get("sender_name") or payload.get("pushName") or "WhatsApp User"
        sender_jid = payload.get("sender_jid") or "unknown@s.whatsapp.net"
        group_name = payload.get("group_name") or "WhatsApp Group"
        group_jid = payload.get("group_jid") or "unknown@g.us"
        message_id = payload.get("message_id") or payload.get("id") or f"wamid_{int(datetime.now().timestamp() * 1000)}"

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
            metadata={"group_name": group_name, "sender_jid": sender_jid},
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
                "message": "Message preserved in Unknown Context for human review.",
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

        project_id = outcome.project_id
        matched_project = db.query(Project).filter(Project.id == project_id).first()
        confidence = 1.0

        # Visual changes are proposal-first: the living workspace is never
        # silently mutated by an incoming message.
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
            },
        )

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
            "excalidraw_updated": False,
            "visual_proposal_pending": proposal is not None,
            "proposal_id": proposal.id if proposal else None,
            "message": (
                f"Routed to project '{matched_project.name if matched_project else project_id}'. "
                "Visual changes are pending human review."
            ),
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
            for ev in recent:
                try:
                    body = json.loads(ev.payload_json).get("text", "")
                except Exception:
                    body = ""
                if body:
                    lines.append(f"- {body}")
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
        """
        clean = text.strip().lower()
        if not clean:
            return True

        # Extract alphanumeric words
        cleaned_words = re.findall(r"[a-z0-9]+", clean)
        acks = {
            "ok", "okay", "k", "kk", "cool", "sure", "done", "got", "it", "noted",
            "yes", "yeah", "yep", "no", "nope", "thanks", "thank", "you", "thx", "ty",
            "great", "awesome", "perfect", "good", "nice", "sounds", "will", "do",
            "alright", "agreed", "understood"
        }
        if cleaned_words and all(w in acks for w in cleaned_words):
            return True

        # Casual greeting phrases
        greetings = [
            r"^good\s+(morning|afternoon|evening|night)\b",
            r"^gm\b",
            r"^(hey|hi|hello|hola|yo)\b",
            r"^how\s+are\s+you\b",
            r"^whats\s+up\b",
            r"^what's\s+up\b",
            r"^happy\s+(friday|monday|weekend|birthday)\b",
            r"^have\s+a\s+good\s+(weekend|day|evening)\b",
            r"^see\s+you\s+(tomorrow|later|soon)\b",
            r"^bye\b",
        ]
        tech_anchors = [
            "api", "service", "pipeline", "database", "redis", "jwt", "model",
            "excalidraw", "project", "architecture", "decided", "integrate", "claims", "core"
        ]
        for pattern in greetings:
            if re.search(pattern, clean):
                if not any(anchor in clean for anchor in tech_anchors):
                    return True

        # Food, lunch, coffee, social outings
        if re.search(r"\b(lunch|dinner|breakfast|coffee|tea|pizza|burger|snacks|cafeteria|restaurant|hungry|food|drinks|beers)\b", clean):
            if not any(anchor in clean for anchor in tech_anchors):
                return True

        # Meeting links & logistics banter
        logistics_patterns = [
            r"\b(send|share|give|drop|where is|what is)\b.*?\b(link|url)\b",
            r"\b(zoom|meet|gmeet|teams|call)\s+(link|url)\b",
            r"\b(can you call me|give me a call|call you in a bit|on another call)\b",
            r"\b(are you free|anyone free|quick sync|hop on a call)\b",
            r"\b(traffic is bad|running late|be there in \d+\s*mins?)\b",
        ]
        if any(re.search(pat, clean) for pat in logistics_patterns):
            if not any(anchor in clean for anchor in tech_anchors):
                return True

        return False

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
