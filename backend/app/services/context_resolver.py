from typing import Any, Dict, List, Optional
import json
import logging
import re

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.project_state import ProjectState
from app.schemas.context import ContextCandidate, ContextResolutionResult
from app.services.llm import LLMClient, get_default_llm_client

logger = logging.getLogger(__name__)

UNKNOWN_CONTEXT_ID = "system_unknown_context"
UNKNOWN_CONTEXT_NAME = "Unknown Context"
UNKNOWN_CONTEXT_DESCRIPTION = (
    "System-managed quarantine workspace for source information that cannot yet "
    "be assigned to an existing project with sufficient confidence."
)


class ContextResolverService:
    """
    Shared project-context resolver for Google Meet, WhatsApp, and Excalidraw.

    The resolver combines deterministic signals with the configured semantic model
    and always keeps uncertainty explicit. Authorization/project membership remain
    deterministic concerns outside the model.
    """

    RESOLVED_THRESHOLD = 0.78
    MIN_CANDIDATE_THRESHOLD = 0.35
    AMBIGUITY_MARGIN = 0.12
    MAX_CANDIDATES = 5

    PROJECT_DOMAIN_KEYWORDS = {
        "health": [
            "claim", "claims", "claimant", "healthcare", "patient", "hospital",
            "insurance", "fhir", "hl7", "kyc", "fraud", "adjudication", "preauth",
        ],
        "core": [
            "synora", "synesis", "authentication", "auth", "session", "jwt",
            "oauth", "redis", "postgres", "postgresql", "fastapi", "nextjs",
            "excalidraw", "whiteboard", "project state", "agent",
        ],
        "frappe": [
            "frappe", "erpnext", "doctype", "bench", "mariadb", "supplier",
            "ledger", "purchase order",
        ],
    }

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or get_default_llm_client()

    def _project_context_records(
        self,
        db: Session,
        workspace_id: str = "ws_default",
        exclude_unknown: bool = True,
    ) -> List[Dict[str, Any]]:
        projects = (
            db.query(Project)
            .filter(Project.workspace_id == workspace_id)
            .order_by(Project.created_at.asc())
            .all()
        )
        records: List[Dict[str, Any]] = []
        for project in projects:
            if exclude_unknown and project.id == UNKNOWN_CONTEXT_ID:
                continue
            state = (
                db.query(ProjectState)
                .filter(ProjectState.project_id == project.id)
                .first()
            )
            state_data: Dict[str, Any] = {}
            if state:
                for field, key in [
                    ("requirements_json", "requirements"),
                    ("architecture_json", "architecture"),
                    ("decisions_json", "decisions"),
                    ("constraints_json", "constraints"),
                    ("assumptions_json", "assumptions"),
                    ("open_questions_json", "open_questions"),
                ]:
                    raw = getattr(state, field, "[]") or "[]"
                    try:
                        state_data[key] = json.loads(raw)
                    except Exception:
                        state_data[key] = []
            records.append(
                {
                    "project": project,
                    "state": state_data,
                    "vision": state.vision if state else "",
                }
            )
        return records

    @staticmethod
    def _flatten_state_text(state_data: Dict[str, Any]) -> str:
        parts: List[str] = []
        for value in state_data.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        parts.extend(str(v) for v in item.values() if v)
                    elif item:
                        parts.append(str(item))
            elif value:
                parts.append(str(value))
        return " ".join(parts)

    def _deterministic_score(
        self,
        text: str,
        project: Project,
        state_data: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> tuple[float, List[str], List[str]]:
        clean = re.sub(r"\s+", " ", text.lower()).strip()
        reasons: List[str] = []
        basis: List[str] = []
        score = 0.0

        project_name = (project.name or "").strip().lower()
        project_id = (project.id or "").lower()
        description = (project.description or "").lower()
        state_text = self._flatten_state_text(state_data).lower()

        if project_id and project_id in clean:
            score = max(score, 0.99)
            reasons.append(f"explicit project id: {project.id}")
            basis.append("deterministic:project_id")

        tag_values = re.findall(r"\[([^\]]+)\]|#([a-zA-Z0-9_-]+)|@([a-zA-Z0-9_-]+)", text)
        for match in tag_values:
            tag = next((part for part in match if part), "").lower()
            if tag and (tag == project_name or tag in project_name.split() or tag in project_name):
                score = max(score, 0.96)
                reasons.append(f"explicit project tag: {tag}")
                basis.append("deterministic:tag")

        if project_name and project_name in clean:
            score += 0.38
            reasons.append(f"project name: {project.name}")
            basis.append("deterministic:project_name")

        name_tokens = [t for t in re.split(r"[\s_\-]+", project_name) if len(t) > 2]
        matched_name_tokens = [t for t in name_tokens if t in clean]
        if matched_name_tokens:
            score += min(0.30, 0.12 * len(matched_name_tokens))
            reasons.append("name tokens: " + ", ".join(matched_name_tokens[:4]))
            basis.append("deterministic:name_tokens")

        if description:
            desc_tokens = {t for t in re.findall(r"[a-z0-9_\-]{4,}", description)}
            overlaps = sorted(t for t in desc_tokens if t in clean)
            if overlaps:
                score += min(0.18, 0.03 * len(overlaps))
                reasons.append("description overlap: " + ", ".join(overlaps[:4]))
                basis.append("deterministic:description")

        combined = " ".join([project_name, description, state_text])
        overlap_tokens = {
            t for t in re.findall(r"[a-z0-9_\-]{4,}", combined)
            if t in clean
        }
        if overlap_tokens:
            score += min(0.20, 0.02 * len(overlap_tokens))
            reasons.append("project context overlap: " + ", ".join(sorted(overlap_tokens)[:5]))
            basis.append("context:state_overlap")

        pn = project_name + " " + description
        domain_bucket = None
        if any(x in pn for x in ["health", "claim", "insurance", "hospital"]):
            domain_bucket = "health"
        elif any(x in pn for x in ["frappe", "erp", "erpnext"]):
            domain_bucket = "frappe"
        elif any(x in pn for x in ["core", "architecture", "synora", "synesis", "platform"]):
            domain_bucket = "core"

        if domain_bucket:
            hits = [kw for kw in self.PROJECT_DOMAIN_KEYWORDS[domain_bucket] if kw in clean]
            if hits:
                score += min(0.25, 0.04 * len(hits))
                reasons.append("domain hints: " + ", ".join(hits[:4]))
                basis.append(f"deterministic:domain:{domain_bucket}")

        known_project_id = metadata.get("bound_project_id")
        if known_project_id and known_project_id == project.id:
            score = max(score, 0.995)
            reasons.append("source binding")
            basis.append("deterministic:source_binding")

        recent_context = metadata.get("recent_context") or []
        if isinstance(recent_context, list):
            recent_text = " ".join(str(x) for x in recent_context).lower()
            continuity_hits = [
                token for token in set(re.findall(r"[a-z0-9_\-]{4,}", combined))
                if token in recent_text
            ]
            if continuity_hits:
                score += min(0.15, 0.03 * len(continuity_hits))
                reasons.append("conversation continuity")
                basis.append("context:continuity")

        return min(0.99, score), reasons, basis

    def _semantic_score(
        self,
        text: str,
        record: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> tuple[Optional[float], List[str]]:
        """
        Ask the configured semantic model for a bounded project-match score.

        Deterministic signals remain separate and stronger than model output. The
        model only supplies semantic evidence; it never grants authorization and
        cannot directly route data.
        """
        try:
            project = record["project"]
            state_data = record["state"]
            context_payload = {
                "incoming_text": text,
                "project": {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "vision": record.get("vision") or "",
                    "state": state_data,
                },
                "conversation_context": metadata.get("conversation_context") or metadata.get("recent_context") or [],
            }
            prompt = (
                "Determine semantic relevance between the incoming project information and this candidate project. "
                "Return JSON only with {\"relevance\": 0.0}. Relevance means topical/contextual fit, not authorization. "
                "Score 0 only when unrelated, 0.5 when plausible, 1 when clearly about the project. "
                "Do not infer facts not present.\n"
                + json.dumps(context_payload, default=str)
            )

            class _SemanticMatch:
                relevance: float

            # Reuse the existing structured client with an inline Pydantic schema.
            from pydantic import BaseModel, Field

            class SemanticMatch(BaseModel):
                relevance: float = Field(ge=0.0, le=1.0)

            result = self.llm_client.generate_structured(prompt, SemanticMatch)
            value = float(getattr(result, "relevance", 0.0))
            return max(0.0, min(1.0, value)), ["llm:semantic_relevance"]
        except Exception as exc:
            logger.warning("Semantic project matching unavailable: %s", exc)
            return None, ["llm:semantic_unavailable"]

    def resolve(
        self,
        text: str,
        db: Session,
        workspace_id: str = "ws_default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ContextResolutionResult:
        metadata = metadata or {}
        clean = text.strip()
        if not clean:
            return ContextResolutionResult(
                status="unknown",
                confidence=0.0,
                reasoning="Empty context window.",
                candidates=[],
                model="context-resolver-v3",
                prompt_version="context-v3",
                source=str(metadata.get("source_name") or "unknown"),
                context_window_id=metadata.get("context_window_id"),
            )

        records = self._project_context_records(
            db, workspace_id=workspace_id, exclude_unknown=True
        )
        if not records:
            return ContextResolutionResult(
                status="unknown",
                confidence=0.0,
                reasoning="No candidate projects exist.",
                candidates=[],
                model="context-resolver-v3",
                prompt_version="context-v3",
                source=str(metadata.get("source_name") or "unknown"),
                context_window_id=metadata.get("context_window_id"),
            )

        candidates: List[ContextCandidate] = []
        for record in records:
            project = record["project"]
            det_score, reasons, basis = self._deterministic_score(
                clean, project, record["state"], metadata
            )

            semantic_score, semantic_basis = self._semantic_score(clean, record, metadata)
            if semantic_score is not None and det_score < 0.99:
                # Semantic signal is blended conservatively; deterministic evidence
                # remains the primary routing signal.
                blended = min(0.99, 0.65 * det_score + 0.35 * semantic_score)
            else:
                blended = det_score

            if semantic_score is not None:
                reasons = reasons + semantic_basis
                basis = basis + ["semantic:model"]
            candidates.append(
                ContextCandidate(
                    project_id=project.id,
                    project_name=project.name,
                    confidence=blended,
                    reasons=reasons,
                    basis=basis,
                )
            )

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        candidates = candidates[: self.MAX_CANDIDATES]
        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        margin = top.confidence - second.confidence if second else top.confidence

        if top.confidence >= self.RESOLVED_THRESHOLD and (second is None or margin >= self.AMBIGUITY_MARGIN):
            status = "resolved"
            selected = top.project_id
            reasoning = f"Resolved to '{top.project_name}'. " + "; ".join(top.reasons[:5])
            confidence = top.confidence
        elif top.confidence >= self.MIN_CANDIDATE_THRESHOLD:
            status = "ambiguous"
            selected = None
            confidence = top.confidence
            reasoning = (
                f"Ambiguous context. Top candidates: {top.project_name} ({top.confidence:.2f})"
                + (f", {second.project_name} ({second.confidence:.2f})." if second else ".")
            )
        else:
            status = "unknown"
            selected = None
            confidence = 0.0
            reasoning = "No project matched with sufficient confidence."

        return ContextResolutionResult(
            status=status,
            selected_project_id=selected,
            confidence=confidence,
            reasoning=reasoning,
            candidates=candidates,
            model="context-resolver-v3",
            prompt_version="context-v3",
            source=str(metadata.get("source_name") or "unknown"),
            context_window_id=metadata.get("context_window_id"),
        )

    def ensure_unknown_context_project(
        self,
        db: Session,
        workspace_id: str = "ws_default",
        tenant_id: str = "default_tenant",
    ) -> Project:
        project = (
            db.query(Project)
            .filter(
                Project.id == UNKNOWN_CONTEXT_ID,
                Project.workspace_id == workspace_id,
            )
            .first()
        )
        if project:
            return project

        project = Project(
            id=UNKNOWN_CONTEXT_ID,
            workspace_id=workspace_id,
            name=UNKNOWN_CONTEXT_NAME,
            description=UNKNOWN_CONTEXT_DESCRIPTION,
        )
        db.add(project)
        db.flush()

        from app.services.project_state_service import ProjectStateService
        ProjectStateService().get_or_create_state(project.id, db)
        db.commit()
        db.refresh(project)
        return project

    def route_or_quarantine(
        self,
        result: ContextResolutionResult,
        db: Session,
        workspace_id: str = "ws_default",
        tenant_id: str = "default_tenant",
    ) -> tuple[Project, ContextResolutionResult]:
        if result.status == "resolved" and result.selected_project_id:
            project = (
                db.query(Project)
                .filter(
                    Project.id == result.selected_project_id,
                    Project.workspace_id == workspace_id,
                    Project.id != UNKNOWN_CONTEXT_ID,
                )
                .first()
            )
            if project:
                return project, result

        unknown = self.ensure_unknown_context_project(
            db, workspace_id=workspace_id, tenant_id=tenant_id
        )
        return unknown, result.model_copy(update={"selected_project_id": None})

    def unknown_context_candidates(
        self,
        db: Session,
        evidence_text: str,
        workspace_id: str = "ws_default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ContextCandidate]:
        return self.resolve(
            text=evidence_text,
            db=db,
            workspace_id=workspace_id,
            metadata=metadata,
        ).candidates

    def move_unknown_evidence_to_project(
        self,
        evidence_id: str,
        target_project_id: str,
        db: Session,
        actor_id: str,
        tenant_id: str = "default_tenant",
        trigger_reprocessing: bool = True,
    ) -> Dict[str, Any]:
        from app.models.evidence import Evidence

        evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()
        if not evidence:
            raise ValueError(f"Evidence '{evidence_id}' not found.")

        target = (
            db.query(Project)
            .filter(
                Project.id == target_project_id,
                Project.workspace_id == "ws_default",
                Project.id != UNKNOWN_CONTEXT_ID,
            )
            .first()
        )
        if not target:
            raise ValueError("Target project does not exist or is not assignable.")

        old_project_id = evidence.project_id
        evidence.project_id = target.id
        metadata = json.loads(evidence.metadata_json or "{}")
        metadata.update({
            "manually_assigned_from_unknown_context": True,
            "assigned_by": actor_id,
            "previous_project_id": old_project_id,
        })
        evidence.metadata_json = json.dumps(metadata)
        db.commit()

        return {
            "ok": True,
            "evidence_id": evidence.id,
            "target_project_id": target.id,
            "target_project_name": target.name,
            "reprocessing_requested": trigger_reprocessing,
        }
