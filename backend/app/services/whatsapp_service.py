from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.excalidraw import ExcalidrawArtifact, ExcalidrawProposal, ExcalidrawProposalStatus
from app.models.intelligence import CandidateKnowledge
from app.models.project import Project
from app.models.project_state import ProjectState
from app.models.source_event import SourceEvent
from app.schemas.source_event import SourceEventCreate
from app.services.audit_service import AuditService
from app.services.excalidraw_service import ExcalidrawService
from app.services.ingestion_service import IngestionService
from app.services.project_agent_service import ProjectAgentService
from app.services.context_resolver import ContextResolverService, UNKNOWN_CONTEXT_ID, UNKNOWN_CONTEXT_NAME

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
        context_resolver: Optional[ContextResolverService] = None,
    ):
        self.ingestion_service = ingestion_service or IngestionService()
        self.excal_service = excal_service or ExcalidrawService()
        self.agent_service = agent_service or ProjectAgentService()
        self.audit_service = audit_service or AuditService()
        self.context_resolver = context_resolver or ContextResolverService()

    def process_incoming_message(
        self,
        payload: Dict[str, Any],
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> Dict[str, Any]:
        """
        End-to-end processing of a WhatsApp group chat message:
        1. Context Disambiguation (which project are they talking about?)
        2. Idempotent Ingestion & Evidence Generation
        3. Architectural Candidate Extraction
        4. Excalidraw Whiteboard Visual Changes & Proposals
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

        # 1. Filter out casual chit-chat (greetings, lunch, coffee, emojis, link requests) -> LEAVE IT
        if self._is_casual_chitchat(raw_text):
            logger.info(
                f"WhatsApp message from '{sender_name}' in '{group_name}' flagged as casual chit-chat. "
                "Leaving Excalidraw whiteboards untouched."
            )
            return {
                "ok": True,
                "processed": False,
                "status": "ignored",
                "reason": "Casual conversation / non-project chit-chat (leave it)",
                "matched_project": None,
                "confidence": 0.0,
                "excalidraw_updated": False,
                "message": "Message ignored: casual chit-chat detected. All project whiteboards left untouched.",
            }

        # 2. Shared context resolution. Meet and WhatsApp use the same resolver.
        context_result = self.context_resolver.resolve(
            text=raw_text,
            db=db,
            metadata={
                "group_name": group_name,
                "group_jid": group_jid,
                "source_name": "whatsapp",
                "sender_name": sender_name,
            },
        )
        matched_project, context_result = self.context_resolver.route_or_quarantine(
            result=context_result,
            db=db,
            workspace_id="ws_default",
            tenant_id=tenant_id,
        )
        project_id = matched_project.id
        confidence = context_result.confidence
        reasoning = context_result.reasoning
        logger.info(
            f"WhatsApp Message from '{sender_name}' in group '{group_name}' "
            f"classified to Project '{matched_project.name}' ({project_id}) "
            f"with confidence {confidence:.2f}. Reason: {reasoning}"
        )

        # 2. Ingest SourceEvent
        event_create = SourceEventCreate(
            tenant_id=tenant_id,
            project_id=project_id,
            source="whatsapp",
            source_event_id=message_id,
            event_type="group_message",
            actor_id=sender_name,
            occurred_at=datetime.now(timezone.utc),
            payload={
                "message_id": message_id,
                "text": raw_text,
                "sender_name": sender_name,
                "sender_jid": sender_jid,
                "group_name": group_name,
                "group_jid": group_jid,
                "matched_project_id": None if project_id == UNKNOWN_CONTEXT_ID else project_id,
                "context_status": context_result.status,
                "context_candidates": [candidate.model_dump() for candidate in context_result.candidates],
                "confidence": confidence,
                "reasoning": reasoning,
            },
            status="received",
        )
        source_event = self.ingestion_service.ingest_event(event_create, db)

        # 3. Create Immutable Evidence
        evidence_content = f"WhatsApp [{group_name}] {sender_name}: {raw_text}"
        evidence = self.ingestion_service.create_evidence_from_event(
            event=source_event,
            db=db,
            content=evidence_content,
            metadata={
                "source": "whatsapp",
                "group_name": group_name,
                "group_jid": group_jid,
                "sender_jid": sender_jid,
                "confidence": confidence,
                "context_status": context_result.status,
                "context_candidates": [candidate.model_dump() for candidate in context_result.candidates],
                "reasoning": reasoning,
            },
        )

        # 4. Extract Architectural Knowledge (Decisions, Requirements, Nodes)
        extracted = self._extract_knowledge_and_components(raw_text)

        candidate_item = None
        if extracted["is_actionable"]:
            candidate_item = CandidateKnowledge(
                project_id=project_id,
                category=extracted["category"],
                title=extracted["title"],
                content=raw_text,
                confidence=confidence,
                status="proposed",
                evidence_ids_json=json.dumps([evidence.id]),
            )
            db.add(candidate_item)
            db.commit()
            db.refresh(candidate_item)

        # 5. Consequential visual changes are proposal-first.
        if context_result.status != "resolved":
            # Unknown/ambiguous context is intentionally quarantined. Its Evidence remains
            # available in the Unknown Context project for later human assignment.
            whiteboard_result = {
                "updated": False,
                "artifact_version": None,
                "nodes_added": [],
                "proposal_id": None,
            }
        else:
            whiteboard_result = self.propose_whiteboard_changes(
                project=matched_project,
                extracted=extracted,
                evidence=evidence,
                sender_name=sender_name,
                group_name=group_name,
                db=db,
                tenant_id=tenant_id,
            )

        # 6. Audit Logging
        self.audit_service.record_event(
            action="whatsapp_group_message_processed",
            actor_id=sender_name,
            resource_type="project_evidence",
            resource_id=evidence.id,
            db=db,
            tenant_id=tenant_id,
            after_state={
                "project_id": project_id,
                "project_name": matched_project.name,
                "context_status": context_result.status,
                "context_candidates": [candidate.model_dump() for candidate in context_result.candidates],
                "confidence": confidence,
                "artifact_version": whiteboard_result.get("artifact_version"),
                "nodes_added": whiteboard_result.get("nodes_added", []),
            },
        )

        return {
            "ok": True,
            "processed": True,
            "message_id": message_id,
            "matched_project": {
                "id": matched_project.id,
                "name": matched_project.name,
            } if project_id != UNKNOWN_CONTEXT_ID else {"id": UNKNOWN_CONTEXT_ID, "name": UNKNOWN_CONTEXT_NAME},
            "context_status": context_result.status,
            "context_candidates": [candidate.model_dump() for candidate in context_result.candidates],
            "confidence": confidence,
            "reasoning": reasoning,
            "evidence_id": evidence.id,
            "candidate_id": candidate_item.id if candidate_item else None,
            "extracted_category": extracted["category"] if extracted["is_actionable"] else "general_discussion",
            "extracted_title": extracted["title"] if extracted["is_actionable"] else None,
            "excalidraw_updated": whiteboard_result.get("updated", False),
            "artifact_version": whiteboard_result.get("artifact_version"),
            "nodes_added": whiteboard_result.get("nodes_added", []),
            "proposal_id": whiteboard_result.get("proposal_id"),
            "message": (
                f"Context {context_result.status} for '{matched_project.name}' ({confidence*100:.0f}% confidence). "
                + (
                    f"Created a reviewable Excalidraw proposal (artifact v{whiteboard_result.get('artifact_version')})."
                    if context_result.status == "resolved"
                    else "Stored in Unknown Context for human review."
                )
            ),
        }


    def propose_whiteboard_changes(
        self,
        project: Project,
        extracted: Dict[str, Any],
        evidence: Evidence,
        sender_name: str,
        group_name: str,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> Dict[str, Any]:
        artifact = self.excal_service.get_or_create_artifact(
            project_id=project.id,
            db=db,
            tenant_id=tenant_id,
            name=f"{project.name} Architecture Whiteboard",
        )
        current_nodes = json.loads(artifact.extracted_nodes_json) if artifact.extracted_nodes_json else []
        nodes_to_add = extracted.get("nodes_to_add", [])
        new_nodes = list(current_nodes)
        added_nodes: List[str] = []
        for node in nodes_to_add:
            if not any(node.lower() == existing.lower() for existing in new_nodes):
                new_nodes.append(node)
                added_nodes.append(node)

        state = self.agent_service.state_service.get_or_create_state(project.id, db)
        decisions = json.loads(state.decisions_json) if state.decisions_json else []
        requirements = json.loads(state.requirements_json) if state.requirements_json else []
        updated_elements = self.excal_service._build_living_workspace_elements(
            node_names=new_nodes,
            decisions=decisions,
            requirements=requirements,
        )
        diff_preview = {
            "nodes_before": current_nodes,
            "nodes_after": new_nodes,
            "nodes_added": added_nodes,
            "nodes_removed": [],
            "source": "whatsapp_group_chat",
            "group_name": group_name,
            "sender_name": sender_name,
        }
        proposal = ExcalidrawProposal(
            artifact_id=artifact.id,
            project_id=project.id,
            tenant_id=tenant_id,
            derived_from_state_version=state.current_version,
            status=ExcalidrawProposalStatus.PENDING.value,
            reason=(
                f"WhatsApp context resolved for '{project.name}'. "
                f"Proposed visual update from '{sender_name}' in '{group_name}'. Evidence: {evidence.id}"
            ),
            proposed_elements_json=json.dumps(updated_elements),
            diff_preview_json=json.dumps(diff_preview),
            evidence_ids_json=json.dumps([evidence.id]),
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        return {
            "updated": False,
            "artifact_version": artifact.version,
            "nodes_added": added_nodes,
            "proposal_id": proposal.id,
        }

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

    def identify_project_from_context(
        self,
        text: str,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> Tuple[Optional[Project], float, str]:
        """
        Disambiguates which Project the people are talking about.
        
        Strategy:
        1. Exact Project ID mention (proj_...)
        2. Hashtag or Bracketed tag ([Healthcare], #claims, @Claims)
        3. Name & Domain Keywords Scoring against all created projects
        4. If top_score >= 3.0: returns matched project
        5. If top_score < 3.0: returns (None, 0.0, reasoning) -> LEAVE IT.
           Crucial Rule: NEVER fallback to proj_default for unknown or uncreated projects.
        """
        projects = db.query(Project).all()
        if not projects:
            return None, 0.0, "No projects exist in the workspace"

        lower_text = text.lower()

        # 1. Exact Project ID in text
        for p in projects:
            if p.id.lower() in lower_text:
                return p, 0.99, f"Explicit Project ID '{p.id}' found in message"

        # 2. Tag / Hashtag / Bracket Matching (e.g. #claims, [Healthcare Claims], @Claims)
        tag_match = re.search(r"\[([^\]]+)\]|#([a-zA-Z0-9_-]+)|@([a-zA-Z0-9_-]+)", text)
        if tag_match:
            tag_val = (tag_match.group(1) or tag_match.group(2) or tag_match.group(3)).lower()
            for p in projects:
                p_name_words = [w.lower() for w in re.split(r"[\s_-]+", p.name)]
                if tag_val in p_name_words or tag_val == p.id.lower() or tag_val in p.name.lower():
                    return p, 0.97, f"Explicit Project tag '[{tag_val}]' matched '{p.name}'"

        # 3. Keyword Scoring across created projects
        scores: Dict[str, float] = {}
        reasons: Dict[str, List[str]] = {}

        for p in projects:
            score = 0.0
            matched_terms = []
            p_name_lower = p.name.lower()
            p_desc_lower = (p.description or "").lower()

            # Name matching
            p_tokens = [t for t in re.split(r"[\s_-]+", p_name_lower) if len(t) > 2]
            for token in p_tokens:
                if token in lower_text:
                    score += 3.0
                    matched_terms.append(f"name_token:{token}")

            # Entire name match
            if p_name_lower in lower_text:
                score += 5.0
                matched_terms.append(f"full_name:{p.name}")

            # Domain keyword dictionaries
            if "claim" in p_name_lower or "health" in p_name_lower:
                health_keywords = [
                    "claims", "claimant", "healthcare", "adjudication", "patient",
                    "tpa", "fhir", "hl7", "kyc", "insurance", "hospital", "diagnosis",
                    "billing", "icd10", "policy", "fraud detection", "digilocker", "preauth"
                ]
                for kw in health_keywords:
                    if kw in lower_text:
                        score += 2.0
                        matched_terms.append(f"domain:{kw}")

            elif "core" in p_name_lower or "architecture" in p_name_lower or "synesis" in p_name_lower or "synora" in p_name_lower:
                core_keywords = [
                    "synora", "core", "auth", "session", "pipeline", "synesis", "rbac", "user",
                    "agent", "oauth", "jwt", "redis", "postgres", "fastapi", "nextjs", "excalidraw", "whiteboard"
                ]
                for kw in core_keywords:
                    if kw in lower_text:
                        score += 2.0
                        matched_terms.append(f"domain:{kw}")

            elif "frappe" in p_name_lower or "erp" in p_name_lower:
                frappe_keywords = [
                    "frappe", "doctype", "erpnext", "supplier", "erp", "ledger",
                    "purchase order", "bench", "mariadb"
                ]
                for kw in frappe_keywords:
                    if kw in lower_text:
                        score += 2.0
                        matched_terms.append(f"domain:{kw}")

            # Description matching
            if p_desc_lower:
                for token in [t for t in re.split(r"[\s_-]+", p_desc_lower) if len(t) > 3]:
                    if token in lower_text and token not in matched_terms:
                        score += 1.0
                        matched_terms.append(f"desc:{token}")

            scores[p.id] = score
            reasons[p.id] = matched_terms

        # Pick highest scoring project
        sorted_projects = sorted(projects, key=lambda p: scores.get(p.id, 0.0), reverse=True)
        top_project = sorted_projects[0]
        top_score = scores.get(top_project.id, 0.0)

        if top_score >= 3.0:
            confidence = min(0.96, 0.70 + (top_score * 0.05))
            reasoning = f"Matched terms: {', '.join(reasons[top_project.id][:4])}"
            return top_project, confidence, reasoning

        # If score is below 3.0, it is NOT about any created project! LEAVE IT!
        return None, 0.0, "Conversation does not match any created project in the workspace"

    def _extract_knowledge_and_components(self, text: str) -> Dict[str, Any]:
        """
        Extracts actionable decisions, requirements, and visual whiteboard components from the text.
        """
        lower = text.lower()
        is_actionable = False
        category = "discussion"
        title = ""
        nodes_to_add: List[str] = []

        # 1. Detect Decision
        if any(w in lower for w in [
            "decided to", "we decided", "let's use", "agreed to", "confirmed:",
            "switch to", "approved", "we will use", "decision:"
        ]):
            is_actionable = True
            category = "decision_candidate"
            title = self._clean_summary(text, prefix="Decision: ")

        # 2. Detect Requirement
        elif any(w in lower for w in [
            "requirement", "must have", "must provide", "system must", "needs to support", "required to"
        ]):
            is_actionable = True
            category = "requirement_candidate"
            title = self._clean_summary(text, prefix="Requirement: ")

        # 3. Detect Component Addition / Architectural Change
        elif any(w in lower for w in [
            "add ", "integrate ", "put ", "create component", "new node", "insert "
        ]):
            is_actionable = True
            category = "proposal"
            title = self._clean_summary(text, prefix="Architecture Change: ")

        # 4. Extract Visual Nodes from text
        # Look for explicit components mentioned
        component_candidates = [
            ("digilocker kyc", "Digilocker KYC Service"),
            ("fraud detection", "Fraud Detection Engine"),
            ("aml", "AML Verification Engine"),
            ("hl7 fhir", "HL7 FHIR Validator"),
            ("fhir", "FHIR Data Bridge"),
            ("redis", "Redis Session Cache"),
            ("jwt", "JWT Auth Gateway"),
            ("celery", "Celery Task Queue"),
            ("kafka", "Kafka Event Bus"),
            ("adjudicator", "Claims Adjudication Engine"),
            ("tax compliance", "Tax Compliance Module"),
            ("supplier portal", "Supplier Portal DocType"),
        ]

        for trigger, node_label in component_candidates:
            if trigger in lower:
                nodes_to_add.append(node_label)

        # Regex fallback for "add/integrate [Name] [service/api/engine/component]"
        regex_matches = re.findall(r"(?:add|integrate|include|use)\s+([A-Za-z0-9_\-\s]{3,25}?)\s+(?:api|service|engine|module|component|gateway)", text, re.IGNORECASE)
        for m in regex_matches:
            clean_node = f"{m.strip().title()} Service"
            if not any(clean_node.lower() == existing.lower() for existing in nodes_to_add) and len(clean_node) < 30:
                nodes_to_add.append(clean_node)

        if not title and is_actionable:
            title = text[:60] + "..." if len(text) > 60 else text

        return {
            "is_actionable": is_actionable,
            "category": category,
            "title": title,
            "nodes_to_add": nodes_to_add,
        }

    def apply_whiteboard_changes(
        self,
        project: Project,
        extracted: Dict[str, Any],
        evidence: Evidence,
        sender_name: str,
        group_name: str,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> Dict[str, Any]:
        """
        Applies changes directly to the project's living Excalidraw whiteboard:
        1. Ensures the target project's ExcalidrawArtifact exists.
        2. Adds newly identified component nodes into the visual architecture pipeline.
        3. Adds a Key Decision card linked to the WhatsApp Evidence provenance.
        4. Increments the artifact version and creates an ExcalidrawProposal with diff preview.
        """
        artifact = self.excal_service.get_or_create_artifact(
            project_id=project.id,
            db=db,
            tenant_id=tenant_id,
            name=f"{project.name} Architecture Whiteboard",
        )

        current_nodes = json.loads(artifact.extracted_nodes_json) if artifact.extracted_nodes_json else ["User", "BA", "Functional", "Tech"]
        nodes_to_add = extracted.get("nodes_to_add", [])
        new_nodes = list(current_nodes)
        added_nodes = []

        for node in nodes_to_add:
            if not any(node.lower() == n.lower() for n in new_nodes):
                # Insert new node right before the last technical node or at the end
                insert_idx = len(new_nodes) - 1 if len(new_nodes) > 1 else len(new_nodes)
                new_nodes.insert(insert_idx, node)
                added_nodes.append(node)

        # Get existing decisions or construct one for this WhatsApp event
        state = self.agent_service.state_service.get_or_create_state(project.id, db)
        state_decisions = json.loads(state.decisions_json) if state.decisions_json else []

        new_decision_entry = {
            "title": extracted.get("title") or f"WhatsApp update from {sender_name}",
            "source": f"WhatsApp [{group_name}]",
            "evidence_ref": evidence.id,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        }
        state_decisions.insert(0, new_decision_entry)

        requirements = json.loads(state.requirements_json) if state.requirements_json else []

        # Build refreshed Excalidraw scene elements
        updated_elements = self.excal_service._build_living_workspace_elements(
            node_names=new_nodes,
            decisions=state_decisions,
            requirements=requirements,
        )

        old_version = artifact.version
        artifact.elements_json = json.dumps(updated_elements)
        artifact.extracted_nodes_json = json.dumps(new_nodes)
        artifact.version += 1
        artifact.updated_at = datetime.now(timezone.utc)

        # Generate ExcalidrawProposal record for auditability & diff preview
        proposal_reason = (
            f"WhatsApp update from '{sender_name}' in group '{group_name}'. "
            f"Added nodes: {', '.join(added_nodes) if added_nodes else 'None'}. "
            f"Evidence: {evidence.id}"
        )
        diff_preview = {
            "nodes_before": current_nodes,
            "nodes_after": new_nodes,
            "nodes_added": added_nodes,
            "nodes_removed": [],
            "source": "whatsapp_group_chat",
            "group_name": group_name,
            "sender_name": sender_name,
        }

        proposal = ExcalidrawProposal(
            artifact_id=artifact.id,
            project_id=project.id,
            tenant_id=tenant_id,
            derived_from_state_version=state.current_version,
            status=ExcalidrawProposalStatus.APPROVED.value,  # Auto-applied to living whiteboard
            reason=proposal_reason,
            proposed_elements_json=json.dumps(updated_elements),
            diff_preview_json=json.dumps(diff_preview),
            approved_at=datetime.now(timezone.utc),
            approved_by=f"whatsapp:{sender_name}",
        )
        db.add(proposal)
        db.commit()
        db.refresh(artifact)
        db.refresh(proposal)

        logger.info(
            f"Updated Excalidraw Whiteboard for project '{project.id}' from v{old_version} to v{artifact.version}. "
            f"Added nodes: {added_nodes}, Proposal ID: {proposal.id}"
        )

        return {
            "updated": True,
            "artifact_id": artifact.id,
            "artifact_version": artifact.version,
            "nodes_added": added_nodes,
            "proposal_id": proposal.id,
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
