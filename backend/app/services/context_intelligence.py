from datetime import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.context_resolution import (
    ContextDecision,
    ContextResolution,
)
from app.models.evidence import Evidence
from app.models.project import SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID, Project
from app.models.project_state import ProjectState
from app.schemas.context import (
    CandidateProject,
    ContextCandidateBatch,
    ContextResolutionResult,
    ContextSignal,
)
from app.services.llm import LLMClient, get_default_llm_client

logger = logging.getLogger(__name__)

TAG_PATTERN = re.compile(r"\[([^\]]+)\]|#([a-zA-Z0-9_-]+)|@([a-zA-Z0-9_-]+)")
PROJECT_ID_PATTERN = re.compile(r"\b(proj_[a-zA-Z0-9_]+)\b")


class ContextIntelligenceService:
    """Shared project-context resolver used by every source.

    Layered strategy (deterministic first, semantic second):

    A. Deterministic signals - explicit project id, explicit tag, trusted
       connector mapping, user-selected project. A deterministic hit
       short-circuits with no model call and no human review.
    B. Semantic signals - NVIDIA NIM + DeepSeek ranks candidate projects and
       returns per-candidate reasons.
    C. Continuity / D. Visual - source-specific window supplied by the caller.

    Hard rules:
    - System projects (Unknown Context) never participate as candidates.
    - The resolver never invents a project; unknown ids from the model are dropped.
    - Authorization is validated deterministically and can never be bypassed by
      semantic similarity.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        # An explicitly injected client is authoritative: provider configuration
        # gates only apply when we resolve the product default ourselves.
        self._explicit_client = llm_client is not None
        self.llm_client = llm_client or get_default_llm_client()

    # ------------------------------------------------------------------
    # System project
    # ------------------------------------------------------------------
    def ensure_unknown_context_project(
        self, db: Session, workspace_id: str = "ws_default"
    ) -> Project:
        """Idempotently ensure the reserved Unknown Context system project exists."""
        project = (
            db.query(Project)
            .filter(Project.id == SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID)
            .first()
        )
        if project:
            return project
        project = Project(
            id=SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID,
            workspace_id=workspace_id,
            name="Unknown Context",
            description=(
                "System-held source evidence that could not be confidently mapped "
                "to a project. Awaiting human triage."
            ),
            is_system=True,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        logger.info("Ensured system project '%s' exists", SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID)
        return project

    # ------------------------------------------------------------------
    # Candidate corpus / authorization
    # ------------------------------------------------------------------
    def _authorized_projects(
        self,
        db: Session,
        tenant_id: str,
        authorized_project_ids: Optional[List[str]] = None,
    ) -> List[Project]:
        """Projects the actor may resolve into.

        System projects are excluded. When an explicit authorization set is
        supplied (e.g. from a workspace/membership scope) it is enforced;
        otherwise every non-system project is treated as visible.
        """
        query = db.query(Project).filter(Project.is_system.is_(False))
        projects = query.all()
        if authorized_project_ids is not None:
            allowed = set(authorized_project_ids)
            projects = [p for p in projects if p.id in allowed]
        projects.sort(key=lambda p: (getattr(p, "updated_at", None) or getattr(p, "created_at", None) or datetime.min), reverse=True)
        return projects

    def _is_authorized(self, project: Project, authorized_project_ids: Optional[List[str]]) -> bool:
        if project.is_system:
            return False
        if authorized_project_ids is not None:
            return project.id in authorized_project_ids
        return True

    @staticmethod
    def is_casual_chatter(text: str) -> bool:
        """
        Shared casual-chat gate used by EVERY source.

        Returns True when the message is pure banter (greetings, acks,
        food/lunch, meeting-link logistics) with no project substance.
        Such messages must be dropped BEFORE any persistence so they never
        appear in the platform (no SourceEvent, no Evidence, no Unknown item).
        Project-related content always returns False, even if uncertain —
        uncertain project talk goes to Unknown Context, never dropped.
        """
        import re as _re

        clean = (text or "").strip().lower()
        if not clean:
            return True

        cleaned_words = _re.findall(r"[a-z0-9]+", clean)
        acks = {
            "ok", "okay", "k", "kk", "cool", "sure", "done", "got", "it", "noted",
            "yes", "yeah", "yep", "no", "nope", "thanks", "thank", "you", "thx", "ty",
            "great", "awesome", "perfect", "good", "nice", "sounds", "will", "do",
            "alright", "agreed", "understood", "lol", "haha", "hahaha", "lmao", "rofl",
            "xd", "true", "fine", "np", "welcome",
        }
        if cleaned_words and all(w in acks for w in cleaned_words):
            return True

        tech_anchors = [
            "api", "service", "pipeline", "database", "redis", "jwt", "model",
            "excalidraw", "project", "architecture", "decided", "integrate", "claims", "core",
            "synora", "dinein", "feature", "schema", "table", "endpoint", "agent", "llm",
            "backend", "frontend", "ui", "ux", "canvas", "webhook", "token", "auth",
            "deploy", "build", "bug", "fix", "test", "docker", "server", "code", "repo",
        ]

        # Casual greeting phrases
        greetings = [
            r"^good\s+(morning|afternoon|evening|night)\b",
            r"^gm\b",
            r"^(hey|hi|hello|hola|yo|sup)\b",
            r"^how\s+are\s+you\b",
            r"^whats\s+up\b",
            r"^what's\s+up\b",
            r"^happy\s+(friday|monday|weekend|birthday|diwali|holi|eid|new year)\b",
            r"^have\s+a\s+good\s+(weekend|day|evening)\b",
            r"^see\s+you\s+(tomorrow|later|soon)\b",
            r"^bye\b",
        ]
        for pattern in greetings:
            if _re.search(pattern, clean):
                if not any(anchor in clean for anchor in tech_anchors):
                    return True

        # Social small talk / personal banter
        social_patterns = [
            r"\b(weekend plans|plans for the weekend|watch(?:ing)? (?:the )?(?:match|game|movie)|going home|on the way|brb|gtg|ttyl)\b",
            r"\b(congrats|congratulations|happy birthday|take care|sleep well)\b",
            r"\b(how was your day|how is it going|what are you doing)\b",
        ]
        if any(_re.search(pat, clean) for pat in social_patterns):
            if not any(anchor in clean for anchor in tech_anchors):
                return True

        meal_banter = [
            r"\b(going for|having|grab(?:bing)?|out for|up for|time for)\s+(?:some\s+|a\s+)?(lunch|dinner|breakfast|coffee|tea|snacks|drinks|food)\b",
            r"\b(coffee break|tea break|grab a bite|let'?s eat|hungry now)\b",
        ]
        if any(_re.search(pat, clean) for pat in meal_banter):
            if not any(anchor in clean for anchor in tech_anchors):
                return True

        logistics_patterns = [
            r"\b(send|share|give|drop|where is|what is)\b.*?\b(link|url)\b",
            r"\b(zoom|meet|gmeet|teams|call)\s+(link|url)\b",
            r"\b(can you call me|give me a call|call you in a bit|on another call)\b",
            r"\b(are you free|anyone free|quick sync|hop on a call)\b",
            r"\b(traffic is bad|running late|be there in \d+\s*mins?)\b",
        ]
        if any(_re.search(pat, clean) for pat in logistics_patterns):
            if not any(anchor in clean for anchor in tech_anchors):
                return True

        return False

    def _build_corpus(self, projects: List[Project], db: Session, tenant_id: str = "default_tenant") -> List[Dict[str, Any]]:
        """Build the bounded candidate corpus: prompt-safe, high-density project summaries."""
        corpus: List[Dict[str, Any]] = []
        evidence_limit = min(settings.CONTEXT_RESOLUTION_EVIDENCE_LIMIT, 3)
        seen_names = set()
        deduped_projects = []
        for p in projects:
            norm_name = (p.name or "").strip().lower()
            if norm_name and norm_name not in seen_names:
                seen_names.add(norm_name)
                deduped_projects.append(p)
            elif not norm_name:
                deduped_projects.append(p)

        from app.services.project_semantic_profile_service import ProjectSemanticProfileService
        profile_svc = ProjectSemanticProfileService()

        for project in deduped_projects:
            profile = profile_svc.get_or_create_profile(project.id, db, tenant_id=tenant_id)
            state = db.query(ProjectState).filter(ProjectState.project_id == project.id).first()
            sections: Dict[str, Any] = {}
            if state:
                if state.vision and state.vision != "Build an evidence-backed software product.":
                    sections["vision"] = state.vision[:300]
                reqs = self._safe_json(state.requirements_json)
                if reqs:
                    sections["requirements"] = reqs[:3]
                arch = self._safe_json(state.architecture_json)
                if arch:
                    sections["architecture"] = arch[:3]
            try:
                from app.models.visual_revision import VisualRevision
                rev = (
                    db.query(VisualRevision)
                    .filter(VisualRevision.project_id == project.id, VisualRevision.is_current == True)
                    .first()
                )
                if rev and rev.scene_json:
                    data = json.loads(rev.scene_json)
                    elems = data if isinstance(data, list) else data.get("elements", [])
                    comps = []
                    for el in elems:
                        txt = el.get("text") if isinstance(el, dict) else None
                        if txt and 2 < len(txt.strip()) < 80:
                            clean_t = txt.strip().replace("\n", " ")
                            if clean_t not in comps:
                                comps.append(clean_t)
                    if comps:
                        sections["whiteboard_components"] = comps[:5]
            except Exception:
                pass
            recent_evidence = (
                db.query(Evidence)
                .filter(Evidence.project_id == project.id)
                .order_by(Evidence.created_at.desc())
                .limit(evidence_limit)
                .all()
            )
            item: Dict[str, Any] = {
                "project_id": project.id,
                "name": project.name,
                "description": (project.description or "")[:350],
                "domain": profile.domain,
            }
            if profile.business_concepts:
                item["business_concepts"] = profile.business_concepts[:10]
            if profile.technical_concepts:
                item["technical_concepts"] = profile.technical_concepts[:10]
            if profile.important_entities:
                item["entities"] = profile.important_entities[:8]
            if sections:
                item["state"] = sections
            if recent_evidence:
                item["recent_evidence"] = [
                    {"id": e.id, "text": (e.content or "")[:140]} for e in recent_evidence
                ]
            corpus.append(item)
        return corpus


    @staticmethod
    def _safe_json(raw: Optional[str]) -> List[Any]:
        try:
            value = json.loads(raw) if raw else []
            return value if isinstance(value, list) else [value]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Input extraction
    # ------------------------------------------------------------------
    @staticmethod
    def extract_text(source: str, payload: Dict[str, Any]) -> str:
        for key in ("text", "content", "caption", "summary", "raw_transcript"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        transcript = payload.get("transcript_entries")
        if isinstance(transcript, list):
            return " ".join(str(t.get("text", "")) for t in transcript if isinstance(t, dict)).strip()
        nodes = payload.get("extracted_nodes") or payload.get("nodes")
        if isinstance(nodes, list):
            return " ".join(str(n) for n in nodes).strip()
        elements = payload.get("elements")
        if isinstance(elements, list):
            texts = [e.get("text", "") for e in elements if isinstance(e, dict) and e.get("text")]
            if texts:
                return " ".join(t.strip() for t in texts if t.strip())
        return ""

    # ------------------------------------------------------------------
    # A. Deterministic signals
    # ------------------------------------------------------------------
    def _deterministic_signals(
        self,
        text: str,
        projects: List[Project],
        trusted_project_id: Optional[str],
    ) -> List[ContextSignal]:
        signals: List[ContextSignal] = []

        if trusted_project_id:
            signals.append(
                ContextSignal(
                    kind="deterministic",
                    name="trusted_connector_mapping",
                    detail=f"Connector is bound to project '{trusted_project_id}'",
                    weight=1.0,
                )
            )

        if text:
            for match in PROJECT_ID_PATTERN.findall(text):
                if any(p.id == match for p in projects):
                    signals.append(
                        ContextSignal(
                            kind="deterministic",
                            name="explicit_project_id",
                            detail=f"Message references '{match}'",
                            weight=1.0,
                        )
                    )

            tag = TAG_PATTERN.search(text)
            if tag:
                tag_val = (tag.group(1) or tag.group(2) or tag.group(3) or "").lower()
                for p in projects:
                    name_words = [w.lower() for w in re.split(r"[\s_-]+", p.name) if w]
                    norm_id = p.id.lower().replace("proj_", "")
                    if tag_val and (tag_val in name_words or tag_val == p.id.lower() or tag_val == norm_id or tag_val in p.name.lower()):
                        signals.append(
                            ContextSignal(
                                kind="deterministic",
                                name="explicit_project_tag",
                                detail=f"Tag '[{tag_val}]' matches '{p.name}'",
                                weight=1.0,
                            )
                        )
                        break
        return signals

    def _apply_deterministic(
        self,
        signals: List[ContextSignal],
        text: str,
        projects: List[Project],
        trusted_project_id: Optional[str],
    ) -> Optional[str]:
        """Return the resolved project id when a deterministic signal is conclusive."""
        if trusted_project_id and any(p.id == trusted_project_id for p in projects):
            return trusted_project_id

        if text:
            for match in PROJECT_ID_PATTERN.findall(text):
                if any(p.id == match for p in projects):
                    return match

            tag = TAG_PATTERN.search(text)
            if tag:
                tag_val = (tag.group(1) or tag.group(2) or tag.group(3) or "").lower()
                for p in projects:
                    name_words = [w.lower() for w in re.split(r"[\s_-]+", p.name) if w]
                    norm_id = p.id.lower().replace("proj_", "")
                    if tag_val and (tag_val in name_words or tag_val == p.id.lower() or tag_val == norm_id or tag_val in p.name.lower()):
                        return p.id
        return None

    # ------------------------------------------------------------------
    # B. Semantic signals
    # ------------------------------------------------------------------
    def _semantic_candidates(
        self,
        text: str,
        corpus: List[Dict[str, Any]],
        continuity_context: Optional[str] = None,
        visual_context: Optional[str] = None,
        feedback_context: Optional[str] = None,
    ) -> tuple[List[CandidateProject], Optional[str], bool]:
        """Ask the semantic provider to rank candidate projects.

        Returns (candidates, ai_status, is_casual) where is_casual is True
        if the message was identified as purely casual/off-topic chat.
        """
        if not text.strip() or not corpus:
            return [], None, False

        if not self._explicit_client:
            provider = (settings.LLM_PROVIDER or "").lower()
            if provider == "deterministic":
                # Deterministic-only mode: no semantic candidates, and no fabricated output.
                return [], "deterministic_only", False
            is_active = (
                (provider == "gemini" and settings.is_gemini_configured)
                or (provider == "groq" and settings.is_groq_configured)
                or (provider == "nvidia" and settings.is_nvidia_nim_configured)
                or settings.is_gemini_configured
                or settings.is_groq_configured
                or settings.is_nvidia_nim_configured
            )
            if not is_active:
                # No semantic provider is reachable: safe deterministic-only path.
                # Candidates stay empty so content routes to Unknown Context;
                # nothing here is ever presented as AI output.
                return [], "ai_unavailable", False

        prompt = self._build_semantic_prompt(text, corpus, continuity_context, visual_context, feedback_context=feedback_context)

        try:
            batch = self.llm_client.generate_structured(prompt, ContextCandidateBatch)
        except NotImplementedError:
            # Safe fallback path (deterministic rule engine has no semantic
            # ranking): report it explicitly and keep candidates empty so the
            # content routes to Unknown Context instead of guessing.
            return [], "ai_unavailable", False
        except Exception as exc:
            # Provider failover: a live AI failure must never fabricate
            # candidates. Surface the error state and fall to Unknown Context.
            logger.warning("context_intelligence_semantic_failed: %s", exc)
            return [], "semantic_error", False

        if getattr(batch, "is_casual", False):
            return [], None, True

        valid_ids = {c["project_id"] for c in corpus}
        candidates: List[CandidateProject] = []
        for item in batch.items:
            # Reject hallucinated projects: never invent a project.
            if item.project_id not in valid_ids:
                continue
            name = next((c["name"] for c in corpus if c["project_id"] == item.project_id), item.project_id)
            candidates.append(
                CandidateProject(
                    project_id=item.project_id,
                    project_name=name,
                    confidence=max(0.0, min(1.0, float(item.confidence))),
                    reasons=list(item.reasons)[:5],
                )
            )
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        candidates = candidates[: settings.CONTEXT_RESOLUTION_CANDIDATE_LIMIT]

        # Efficient-agent backstops (deterministic, no guessing):
        # 1. If the model returned NO candidates at all, build one ranked
        #    slate from lexical overlap so a clearly-topical project still
        #    wins. Zero overlap everywhere -> stays Unknown.
        # 2. If every score is weak, boost by overlap the same way.
        if not candidates:
            candidates = self._lexical_slate(text, corpus)
        elif max(float(c.confidence) for c in candidates) < 0.35:
            boosted = self._lexical_backstop(text, corpus, candidates)
            if boosted:
                candidates = boosted
        return candidates, None, False

    @staticmethod
    def _corpus_terms(entry: Dict[str, Any]) -> set:
        import re as _re

        haystack = " ".join(
            [
                str(entry.get("name", "")),
                str(entry.get("description", "")),
                str(entry.get("domain", "")),
                json.dumps(entry.get("business_concepts", []), default=str),
                json.dumps(entry.get("technical_concepts", []), default=str),
                json.dumps(entry.get("entities", []), default=str),
                json.dumps(entry.get("state", {}), default=str),
                json.dumps(entry.get("recent_evidence", []), default=str),
            ]
        ).lower()
        words = set(_re.findall(r"[a-z0-9]{3,}", haystack))
        stop = {
            "the", "and", "for", "with", "that", "this", "from", "have", "has",
            "will", "should", "could", "would", "what", "when", "where", "which",
            "create", "make", "build", "need", "want", "please", "team",
        }
        return words - stop

    @classmethod
    def _lexical_slate(
        cls,
        text: str,
        corpus: List[Dict[str, Any]],
    ) -> List["CandidateProject"]:
        """Rank every project by topical token overlap with the message."""
        import re as _re

        words = {w for w in _re.findall(r"[a-z0-9]{3,}", (text or "").lower())}
        stop = {
            "the", "and", "for", "with", "that", "this", "from", "have", "has",
            "will", "should", "could", "would", "what", "when", "where", "which",
            "create", "make", "build", "need", "want", "please", "team",
        }
        words -= stop
        if not words:
            return []
        scored: List[tuple] = []
        for entry in corpus:
            overlap = len(words & cls._corpus_terms(entry))
            if overlap > 0:
                confidence = min(0.35 + 0.10 * overlap, 0.88)
                scored.append(
                    (
                        overlap,
                        CandidateProject(
                            project_id=entry["project_id"],
                            project_name=entry.get("name", entry["project_id"]),
                            confidence=confidence,
                            reasons=[f"Topical overlap with project context ({overlap} terms)"],
                        ),
                    )
                )
        scored.sort(key=lambda s: s[0], reverse=True)
        return [c for _, c in scored[: settings.CONTEXT_RESOLUTION_CANDIDATE_LIMIT]]

    @classmethod
    def _lexical_backstop(
        cls,
        text: str,
        corpus: List[Dict[str, Any]],
        candidates: List["CandidateProject"],
    ) -> List["CandidateProject"]:
        """Deterministic token-overlap boost for weak semantic scores."""
        import re as _re

        words = {w for w in _re.findall(r"[a-z0-9]{3,}", (text or "").lower())}
        words -= {
            "the", "and", "for", "with", "that", "this", "from", "have", "has",
            "will", "should", "could", "would", "what", "when", "where", "which",
            "create", "make", "build", "need", "want", "please", "team",
        }
        if not words:
            return candidates
        scored: List[tuple] = []
        for cand in candidates:
            entry = next((c for c in corpus if c["project_id"] == cand.project_id), None)
            overlap = len(words & cls._corpus_terms(entry)) if entry else 0
            scored.append((overlap, cand))
        best_overlap = max(s for s, _ in scored)
        if best_overlap <= 0:
            return candidates
        out: List["CandidateProject"] = []
        for overlap, cand in scored:
            if overlap == best_overlap:
                boost = min(0.15 + 0.05 * overlap, 0.45)
                out.append(
                    CandidateProject(
                        project_id=cand.project_id,
                        project_name=cand.project_name,
                        confidence=min(1.0, float(cand.confidence) + boost),
                        reasons=list(cand.reasons or []) + [f"Topical overlap with project context ({overlap} terms)"],
                        supporting_evidence_ids=list(getattr(cand, "supporting_evidence_ids", []) or []),
                        supporting_state_sections=list(getattr(cand, "supporting_state_sections", []) or []),
                        conflicts=list(getattr(cand, "conflicts", []) or []),
                    )
                )
            else:
                out.append(cand)
        out.sort(key=lambda c: float(c.confidence), reverse=True)
        return out

    def _build_semantic_prompt(
        self,
        text: str,
        corpus: List[Dict[str, Any]],
        continuity_context: Optional[str],
        visual_context: Optional[str],
        feedback_context: Optional[str] = None,
    ) -> str:
        lines = [
            "You are Synora's Context Intelligence routing engine.",
            "Return ONLY JSON matching this schema: {\"is_casual\": false, \"items\": [{\"project_id\": \"...\", \"confidence\": 0.0, \"reasons\": [\"...\"]}]}",
            "",
            "RULE 1: CASUAL CHIT-CHAT DETECTION (ZERO PLATFORM POLLUTION)",
            "is_casual=true ONLY for pure banter with ZERO project substance:",
            "- short acks (ok, thanks, got it, sounds good), pure greetings (hi, good morning) with no technical content,",
            "- food/lunch/coffee/social talk with no technical anchor, meeting-link logistics (send the link, hop on a call).",
            "- NEVER set is_casual=true just because the text contains the words 'chatter', 'chat', 'unrelated', 'topic'.",
            "- If the content mentions ANY feature, system, decision, task, requirement, architecture, bug, or business idea — even if it matches NO candidate — set is_casual=false and return low-confidence items or [] so it routes to Unknown Context.",
            "- If it is casual chat: return {\"is_casual\": true, \"items\": []}. This ensures casual chat is dropped and never appears anywhere on the platform.",
            "- If the content contains ANY project discussion, technical ideas, features, architecture, bug reports, tasks, or business requirements: set \"is_casual\": false and proceed to Rule 2.",
            "",
            "RULE 2: CONTEXTUAL & DOMAIN-BASED CLASSIFICATION (NO PROJECT NAME REQUIRED)",
            "Team members rarely type the project name or ID. You MUST classify based on domain semantics, technical concepts, architecture, feature continuity, and system context:",
            "- Study the candidate projects below: inspect their names, descriptions, vision, architecture, requirements, decisions, and recent evidence.",
            "- Identify the technical domain, business concepts, or feature area being discussed (e.g. restaurant tables/billing/KOT -> Dinein; agentic execution/vector quantization/whiteboard canvas sync -> Synora; claims review/KYC/medical verification -> Healthcare Claims Engine).",
            "- Do NOT require or expect the user to say the project name or ID. If the concepts, vocabulary, workflow, or technical substance clearly align with one project, assign HIGH confidence (0.80 - 0.95) and detail your domain reasoning in 'reasons'.",
            "- Use the conversation continuity window to check which project this group/channel is currently working on.",
            "",
            "RULE 3: UNKNOWN CONTEXT CRITERIA (ONLY WHEN IMPOSSIBLE TO RESOLVE)",
            "Only route project discussion to Unknown Context (assigning confidence < 0.50 or returning []) when:",
            "- UNRECOGNIZED / UNRELATED DOMAIN: The message discusses a product, system, or business completely alien to all candidate projects (e.g., shoe retail, cryptocurrency mining, real estate CRM when no such project exists).",
            "- SPLIT INTENT: The message explicitly spans multiple distinct projects (e.g., 'we have to add agentic layer in Synora and Dinein'). Assign equal low confidence (< 0.50) so human triage can decide.",
            "- CONFLICTING OR HIGHLY AMBIGUOUS: Two projects share the exact same domain concepts and cannot be differentiated.",
            "",
            "--- CANDIDATE PROJECTS ---",
        ]
        for c in corpus:
            lines.append(json.dumps(c, default=str))
        if continuity_context:
            lines += ["", "--- CONVERSATION CONTINUITY ---", continuity_context[:1500]]
        if visual_context:
            lines += ["", "--- VISUAL CONTEXT ---", visual_context[:1500]]
        if feedback_context:
            lines += ["", "--- HISTORICAL HUMAN CLASSIFICATION FEEDBACK ---", feedback_context[:1500]]
        lines += ["", "--- INCOMING CONTENT ---", text[:4000]]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def resolve(
        self,
        source: str,
        payload: Dict[str, Any],
        db: Session,
        tenant_id: str = "default_tenant",
        actor_id: Optional[str] = None,
        trusted_project_id: Optional[str] = None,
        continuity_context: Optional[str] = None,
        visual_context: Optional[str] = None,
        source_event_id: Optional[str] = None,
        authorized_project_ids: Optional[List[str]] = None,
        record: bool = True,
    ) -> ContextResolutionResult:
        """Resolve the project context for one incoming source event."""
        text = self.extract_text(source, payload)

        # Casual / noise gate: drop pure banter before any routing or persistence
        if self.is_casual_chatter(text):
            return ContextResolutionResult(
                decision=ContextDecision.CASUAL_IGNORED.value,
                project_id=None,
                confidence=0.0,
                margin=0.0,
                is_casual=True,
                signals=[],
                candidate_projects=[],
                reason="Casual non-project conversation detected; ignored to preserve workspace purity",
                requires_human_review=False,
            )

        projects = self._authorized_projects(db, tenant_id, authorized_project_ids)

        # A. Deterministic first (short-circuits, no model call).
        det_signals = self._deterministic_signals(text, projects, trusted_project_id)
        det_project_id = self._apply_deterministic(det_signals, text, projects, trusted_project_id)
        if det_project_id:
            result = ContextResolutionResult(
                decision=ContextDecision.RESOLVED.value,
                project_id=det_project_id,
                confidence=1.0,
                margin=1.0,
                signals=det_signals,
                candidate_projects=[],
                reason=det_signals[0].detail if det_signals else "Deterministic match",
                requires_human_review=False,
            )
            if record:
                self._record(source, source_event_id, result, db, tenant_id)
            return result

        # Top-K candidate retrieval via vector embeddings if multiple projects exist
        if len(projects) > 5 and text.strip():
            from app.services.project_semantic_profile_service import ProjectSemanticProfileService
            profile_svc = ProjectSemanticProfileService()
            top_ranked = profile_svc.rank_candidates_by_embedding(text, projects, db, tenant_id=tenant_id, top_k=5)
            ranked_pids = {p.id for p, _ in top_ranked}
            projects = [p for p in projects if p.id in ranked_pids]

        # Historical human feedback retrieval
        feedback_context: Optional[str] = None
        try:
            from app.services.context_feedback_service import ContextFeedbackService
            fb_svc = ContextFeedbackService(db)
            feedback_context = fb_svc.get_feedback_for_prompt([p.id for p in projects], tenant_id=tenant_id)
        except Exception as exc:
            logger.debug("failed_to_fetch_feedback: %s", exc)

        # B/C/D. Semantic + continuity + visual, delegated to a pure scoring step
        # so callers can run it concurrently with knowledge extraction.
        corpus = self._build_corpus(projects, db, tenant_id=tenant_id) if projects else []
        result = self.resolve_with_corpus(
            text=text,
            corpus=corpus,
            det_signals=det_signals,
            continuity_context=continuity_context,
            visual_context=visual_context,
            feedback_context=feedback_context,
        )
        if record and result.decision != ContextDecision.CASUAL_IGNORED.value:
            self._record(source, source_event_id, result, db, tenant_id)
        return result

    def resolve_with_corpus(
        self,
        text: str,
        corpus: List[Dict[str, Any]],
        det_signals: Optional[List[ContextSignal]] = None,
        continuity_context: Optional[str] = None,
        visual_context: Optional[str] = None,
        feedback_context: Optional[str] = None,
    ) -> ContextResolutionResult:
        """Pure scoring + routing decision. Performs NO database access.

        Safe to run on a worker thread while knowledge extraction runs in
        parallel: the caller pre-loads the corpus and evidence snapshot.
        """
        signals = list(det_signals or [])

        if not corpus:
            return ContextResolutionResult(
                decision=ContextDecision.UNKNOWN.value,
                confidence=0.0,
                margin=0.0,
                signals=signals,
                reason="No authorized projects exist to resolve against",
                requires_human_review=True,
            )

        if continuity_context:
            signals.append(ContextSignal(kind="continuity", name="conversation_window", weight=0.3))
        if visual_context:
            signals.append(ContextSignal(kind="visual", name="scene_structure", weight=0.3))

        candidates, ai_status, is_casual = self._semantic_candidates(
            text, corpus, continuity_context, visual_context, feedback_context=feedback_context
        )


        if is_casual:
            return ContextResolutionResult(
                decision=ContextDecision.CASUAL_IGNORED.value,
                project_id=None,
                confidence=0.0,
                margin=0.0,
                is_casual=True,
                signals=signals,
                candidate_projects=[],
                reason="Casual non-project conversation detected; ignored to preserve workspace purity",
                requires_human_review=False,
            )

        if ai_status:
            signals.append(
                ContextSignal(kind="semantic", name=ai_status, detail=ai_status, weight=0.0)
            )

        if not candidates:
            return ContextResolutionResult(
                decision=ContextDecision.UNKNOWN.value,
                confidence=0.0,
                margin=0.0,
                signals=signals,
                candidate_projects=[],
                reason=(
                    "Semantic resolution unavailable and no deterministic match"
                    if ai_status
                    else "No project matched the incoming content"
                ),
                requires_human_review=True,
            )

        top = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None
        margin = top.confidence - (runner_up.confidence if runner_up else 0.0)
        signals.append(
            ContextSignal(
                kind="semantic",
                name="ranked_candidates",
                detail=f"top={top.project_id} confidence={top.confidence:.2f}",
                weight=top.confidence,
            )
        )

        if (
            top.confidence >= settings.CONTEXT_RESOLUTION_MIN_CONFIDENCE
            and margin >= settings.CONTEXT_RESOLUTION_MIN_MARGIN
        ):
            decision = ContextDecision.RESOLVED
            project_id = top.project_id
            reason = "; ".join(top.reasons) or "Strong semantic match"
            requires_review = False
        elif top.confidence >= settings.CONTEXT_RESOLUTION_MIN_CONFIDENCE:
            decision = ContextDecision.AMBIGUOUS
            project_id = None
            reason = "Multiple projects are similarly plausible; human review required"
            requires_review = True
        else:
            decision = ContextDecision.UNKNOWN
            project_id = None
            reason = "No project matched weakly-confident semantic candidates"
            requires_review = True

        return ContextResolutionResult(
            decision=decision.value,
            project_id=project_id,
            confidence=round(top.confidence, 4),
            margin=round(margin, 4),
            signals=signals,
            candidate_projects=candidates,
            reason=reason,
            requires_human_review=requires_review,
        )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def _record(
        self,
        source: str,
        source_event_id: Optional[str],
        result: ContextResolutionResult,
        db: Session,
        tenant_id: str,
    ) -> ContextResolution:
        row = ContextResolution(
            tenant_id=tenant_id,
            workspace_id="ws_default",
            source=source,
            source_event_id=source_event_id,
            evidence_id=result.evidence_ids[0] if result.evidence_ids else None,
            project_id=result.project_id,
            decision=result.decision,
            confidence=result.confidence,
            margin=result.margin,
            signals_json=json.dumps([s.model_dump() for s in result.signals]),
            candidate_projects_json=json.dumps([c.model_dump() for c in result.candidate_projects]),
            reason=result.reason,
            requires_human_review=result.requires_human_review,
            model=result.model,
            model_version=result.model_version,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info(
            "context_resolved: source=%s source_event_id=%s decision=%s project_id=%s "
            "confidence=%.3f margin=%.3f review=%s",
            source,
            source_event_id,
            result.decision,
            result.project_id,
            result.confidence,
            result.margin,
            result.requires_human_review,
        )
        return row
