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
        return projects

    def _is_authorized(self, project: Project, authorized_project_ids: Optional[List[str]]) -> bool:
        if project.is_system:
            return False
        if authorized_project_ids is not None:
            return project.id in authorized_project_ids
        return True

    def _build_corpus(self, projects: List[Project], db: Session) -> List[Dict[str, Any]]:
        """Build the bounded candidate corpus: prompt-safe project summaries."""
        corpus: List[Dict[str, Any]] = []
        evidence_limit = settings.CONTEXT_RESOLUTION_EVIDENCE_LIMIT
        for project in projects:
            state = db.query(ProjectState).filter(ProjectState.project_id == project.id).first()
            sections: Dict[str, Any] = {}
            if state:
                sections = {
                    "vision": (state.vision or "")[:400],
                    "requirements": self._safe_json(state.requirements_json)[:4],
                    "decisions": self._safe_json(state.decisions_json)[:4],
                    "constraints": self._safe_json(state.constraints_json)[:3],
                    "architecture": self._safe_json(state.architecture_json)[:4],
                }
            recent_evidence = (
                db.query(Evidence)
                .filter(Evidence.project_id == project.id)
                .order_by(Evidence.created_at.desc())
                .limit(evidence_limit)
                .all()
            )
            corpus.append(
                {
                    "project_id": project.id,
                    "name": project.name,
                    "description": (project.description or "")[:400],
                    "state": sections,
                    "recent_evidence": [
                        {"id": e.id, "text": (e.content or "")[:240]} for e in recent_evidence
                    ],
                }
            )
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
        nodes = payload.get("extracted_nodes")
        if isinstance(nodes, list):
            return " ".join(str(n) for n in nodes).strip()
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
                    if tag_val and (tag_val in name_words or tag_val == p.id.lower() or tag_val in p.name.lower()):
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
                    if tag_val and (tag_val in name_words or tag_val == p.id.lower() or tag_val in p.name.lower()):
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
    ) -> tuple[List[CandidateProject], Optional[str]]:
        """Ask the semantic provider to rank candidate projects.

        Returns (candidates, ai_status) where ai_status is None on success or a
        machine-readable reason when semantic resolution was unavailable.
        """
        if not text.strip() or not corpus:
            return [], None

        if not self._explicit_client:
            if settings.LLM_PROVIDER.lower() != "nvidia" or not settings.is_nvidia_nim_configured:
                # Deterministic-only mode: no semantic candidates, and no fabricated output.
                return [], "ai_unavailable"

        prompt = self._build_semantic_prompt(text, corpus, continuity_context, visual_context)
        try:
            batch = self.llm_client.generate_structured(prompt, ContextCandidateBatch)
        except NotImplementedError:
            return [], "ai_unavailable"
        except Exception as exc:
            logger.warning("context_intelligence_semantic_failed: %s", exc)
            return [], "semantic_error"

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
        return candidates[: settings.CONTEXT_RESOLUTION_CANDIDATE_LIMIT], None

    def _build_semantic_prompt(
        self,
        text: str,
        corpus: List[Dict[str, Any]],
        continuity_context: Optional[str],
        visual_context: Optional[str],
    ) -> str:
        lines = [
            "You resolve which Synora project an incoming source event belongs to.",
            "Return ONLY JSON: {\"items\":[{\"project_id\":\"...\",\"confidence\":0.0,\"reasons\":[\"...\"]}]}",
            "Rank the candidate projects by how strongly the incoming content belongs to them.",
            "Use ONLY the project_ids listed below. If nothing fits, return an empty items array.",
            "Explain each suggestion with short concrete reasons (terms, components, intent).",
            "",
            "--- CANDIDATE PROJECTS ---",
        ]
        for c in corpus:
            lines.append(json.dumps(c, default=str))
        if continuity_context:
            lines += ["", "--- CONVERSATION CONTINUITY ---", continuity_context[:1500]]
        if visual_context:
            lines += ["", "--- VISUAL CONTEXT ---", visual_context[:1500]]
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

        # B/C/D. Semantic + continuity + visual, delegated to a pure scoring step
        # so callers can run it concurrently with knowledge extraction.
        corpus = self._build_corpus(projects, db) if projects else []
        result = self.resolve_with_corpus(
            text=text,
            corpus=corpus,
            det_signals=det_signals,
            continuity_context=continuity_context,
            visual_context=visual_context,
        )
        if record:
            self._record(source, source_event_id, result, db, tenant_id)
        return result

    def resolve_with_corpus(
        self,
        text: str,
        corpus: List[Dict[str, Any]],
        det_signals: Optional[List[ContextSignal]] = None,
        continuity_context: Optional[str] = None,
        visual_context: Optional[str] = None,
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

        candidates, ai_status = self._semantic_candidates(text, corpus, continuity_context, visual_context)

        if ai_status:
            signals.append(
                ContextSignal(kind="semantic", name="ai_unavailable", detail=ai_status, weight=0.0)
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
            source=source,
            source_event_id=source_event_id,
            project_id=result.project_id,
            decision=result.decision,
            confidence=result.confidence,
            margin=result.margin,
            signals_json=json.dumps([s.model_dump() for s in result.signals]),
            candidate_projects_json=json.dumps([c.model_dump() for c in result.candidate_projects]),
            reason=result.reason,
            requires_human_review=result.requires_human_review,
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
