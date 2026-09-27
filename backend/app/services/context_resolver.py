from typing import Any, Dict, List, Optional, Tuple, Literal
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


class ContextResolverError(ValueError):
    """Raised when context resolution cannot be completed safely."""
    pass


class ContextResolverService:
    """
    Shared project-context intelligence for Meet, WhatsApp, and Excalidraw.

    The model proposes context. Deterministic rules decide whether that proposal
    can be trusted for routing. Ambiguous/unresolved events are routed to the
    system-managed Unknown Context project for human triage.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or get_default_llm_client()

    def ensure_unknown_context_project(
        self,
        db: Session,
        workspace_id: str = "ws_default",
        tenant_id: str = "default_tenant",
    ) -> Project:
        project = db.query(Project).filter(Project.id == UNKNOWN_CONTEXT_ID).first()
        if not project:
            project = Project(
                id=UNKNOWN_CONTEXT_ID,
                workspace_id=workspace_id,
                name=UNKNOWN_CONTEXT_NAME,
                description=(
                    "System-managed quarantine workspace for source information that "
                    "cannot yet be assigned to an existing project with sufficient confidence."
                ),
            )
            db.add(project)
            db.commit()
            db.refresh(project)
        return project

    def _project_context_records(
        self,
        db: Session,
        workspace_id: Optional[str] = None,
        exclude_unknown: bool = True,
    ) -> List[Dict[str, Any]]:
        query = db.query(Project)
        if workspace_id:
            query = query.filter(Project.workspace_id == workspace_id)
        projects = query.order_by(Project.name.asc()).all()

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
                try:
                    decisions = json.loads(state.decisions_json or "[]")
                except Exception:
                    decisions = []
                try:
                    requirements = json.loads(state.requirements_json or "[]")
                except Exception:
                    requirements = []
                try:
                    architecture = json.loads(state.architecture_json or "[]")
                except Exception:
                    architecture = []
                state_data = {
                    "vision": state.vision,
                    "decisions": [d.get("title") or d.get("text") or d.get("content", "") for d in decisions[:8]],
                    "requirements": [r.get("title") or r.get("content", "") for r in requirements[:8]],
                    "architecture": [a.get("name") or a.get("title") or a.get("label") or str(a) for a in architecture[:12]],
                }

            records.append(
                {
                    "project_id": project.id,
                    "name": project.name,
                    "description": project.description or "",
                    **state_data,
                }
            )
        return records

    @staticmethod
    def _metadata_text(metadata: Optional[Dict[str, Any]]) -> str:
        if not metadata:
            return ""
        values: List[str] = []
        for key in ("group_name", "meeting_title", "channel_name", "source_name", "participants"):
            value = metadata.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                values.extend(str(v) for v in value)
            else:
                values.append(str(value))
        return " ".join(values)

    def _deterministic_candidates(
        self,
        text: str,
        project_records: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ContextCandidate]:
        lower = text.lower()
        meta_text = self._metadata_text(metadata).lower()
        combined = f"{lower} {meta_text}".strip()
        scores: List[ContextCandidate] = []

        stop_words = {
            "the", "and", "for", "with", "from", "that", "this", "will",
            "into", "have", "has", "are", "was", "were", "our", "your",
            "project", "system", "team", "today", "about", "using",
        }

        for project in project_records:
            score = 0.0
            reasons: List[str] = []
            name = project["name"].lower()
            desc = project.get("description", "").lower()

            if project["project_id"].lower() in lower:
                score += 100.0
                reasons.append("explicit project ID")

            if name in lower:
                score += 40.0
                reasons.append("full project name")

            tokens = [
                token for token in re.findall(r"[a-z0-9]+", name)
                if len(token) >= 3 and token not in stop_words
            ]
            for token in tokens:
                if re.search(rf"\b{re.escape(token)}\b", combined):
                    score += 10.0
                    reasons.append(f"name:{token}")

            for token in [
                token for token in re.findall(r"[a-z0-9]+", desc)
                if len(token) >= 4 and token not in stop_words
            ]:
                if re.search(rf"\b{re.escape(token)}\b", combined):
                    score += 2.0
                    if len(reasons) < 6:
                        reasons.append(f"description:{token}")

            for bucket_name, values, weight in (
                ("decision", project.get("decisions", []), 3.5),
                ("requirement", project.get("requirements", []), 3.0),
                ("architecture", project.get("architecture", []), 3.5),
            ):
                for item in values:
                    item_tokens = [
                        token for token in re.findall(r"[a-z0-9]+", str(item).lower())
                        if len(token) >= 4 and token not in stop_words
                    ]
                    overlap = sum(1 for token in set(item_tokens) if re.search(rf"\b{re.escape(token)}\b", combined))
                    if overlap:
                        score += min(weight * overlap, 10.0)
                        if len(reasons) < 6:
                            reasons.append(f"{bucket_name} overlap:{overlap}")

            if score > 0:
                confidence = min(0.96, 0.45 + score / 120.0)
                scores.append(
                    ContextCandidate(
                        project_id=project["project_id"],
                        project_name=project["name"],
                        confidence=round(confidence, 4),
                        reasons=reasons[:8],
                    )
                )

        return sorted(scores, key=lambda x: x.confidence, reverse=True)

    def _resolve_from_candidates(
        self,
        candidates: List[ContextCandidate],
    ) -> ContextResolutionResult:
        if not candidates:
            return ContextResolutionResult(
                status="unknown",
                selected_project_id=None,
                confidence=0.0,
                reasoning="No existing project has meaningful context overlap.",
                candidates=[],
                model="deterministic-context-v1",
                prompt_version="context-v1",
            )

        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        margin = top.confidence - second.confidence if second else top.confidence

        if top.confidence >= 0.72 and margin >= 0.12:
            return ContextResolutionResult(
                status="resolved",
                selected_project_id=top.project_id,
                confidence=top.confidence,
                reasoning=f"Strong deterministic context match: {', '.join(top.reasons[:4]) or 'context overlap'}.",
                candidates=candidates[:5],
                model="deterministic-context-v1",
                prompt_version="context-v1",
            )

        if top.confidence >= 0.50:
            return ContextResolutionResult(
                status="ambiguous",
                selected_project_id=None,
                confidence=top.confidence,
                reasoning="Multiple projects or insufficient context separation require human review.",
                candidates=candidates[:5],
                model="deterministic-context-v1",
                prompt_version="context-v1",
            )

        return ContextResolutionResult(
            status="unknown",
            selected_project_id=None,
            confidence=top.confidence,
            reasoning="Context overlap is too weak to assign this event safely.",
            candidates=candidates[:5],
            model="deterministic-context-v1",
            prompt_version="context-v1",
        )

    def resolve(
        self,
        text: str,
        db: Session,
        workspace_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ContextResolutionResult:
        if not text or not text.strip():
            return ContextResolutionResult(
                status="unknown",
                selected_project_id=None,
                confidence=0.0,
                reasoning="Empty content cannot be assigned.",
                candidates=[],
                model="deterministic-context-v1",
                prompt_version="context-v1",
            )

        records = self._project_context_records(db, workspace_id=workspace_id)
        deterministic_candidates = self._deterministic_candidates(text, records, metadata)

        # NIM/DeepSeek receives only bounded project summaries. It proposes matches;
        # deterministic validation below rejects unknown project IDs and weak matches.
        if records and self._nim_available():
            try:
                prompt = self._build_llm_prompt(text, records, metadata)
                ai_result = self.llm_client.generate_structured(prompt, ContextResolutionResult)
                allowed_ids = {r["project_id"] for r in records}

                valid_candidates = [
                    c for c in ai_result.candidates
                    if c.project_id in allowed_ids
                ]
                ai_result.candidates = valid_candidates[:5]

                if (
                    ai_result.status == "resolved"
                    and ai_result.selected_project_id in allowed_ids
                    and ai_result.confidence >= 0.75
                ):
                    # Require a deterministic support signal before auto-routing.
                    supported = any(
                        c.project_id == ai_result.selected_project_id
                        for c in deterministic_candidates
                    )
                    if supported:
                        return ai_result

                if ai_result.status == "ambiguous":
                    return ContextResolutionResult(
                        status="ambiguous",
                        selected_project_id=None,
                        confidence=ai_result.confidence,
                        reasoning=ai_result.reasoning,
                        candidates=ai_result.candidates[:5],
                        model=ai_result.model,
                        prompt_version=ai_result.prompt_version,
                    )
            except Exception as exc:
                logger.warning("Context NIM resolution failed; using deterministic fallback: %s", exc)

        return self._resolve_from_candidates(deterministic_candidates)

    def _nim_available(self) -> bool:
        # Provider availability is reflected by the selected client type rather than
        # exposing secrets or requiring a network probe.
        return self.llm_client.__class__.__name__ == "NvidiaNimLLMClient"

    def _build_llm_prompt(
        self,
        text: str,
        project_records: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
    ) -> str:
        lines = [
            "Resolve which existing Synora project this source content belongs to.",
            "You are NOT allowed to invent a project ID.",
            "Return only project IDs from the supplied candidates.",
            "Prefer ambiguity/unknown over a weak guess.",
            "Use conversation/meeting metadata as context but do not treat it as authorization.",
            "",
            f"CONTENT:\n{text}",
            f"METADATA:\n{json.dumps(metadata or {}, ensure_ascii=True)}",
            "PROJECT CANDIDATES:",
        ]
        for record in project_records:
            lines.append(json.dumps(record, ensure_ascii=True))
        return "\n".join(lines)

    def move_unknown_evidence_to_project(
        self,
        evidence_id: str,
        target_project_id: str,
        db: Session,
        actor_id: str,
        tenant_id: str = "default_tenant",
        trigger_reprocessing: bool = True,
    ) -> Dict[str, Any]:
        if target_project_id == UNKNOWN_CONTEXT_ID:
            raise ContextResolverError("Unknown Context is a quarantine destination, not a reassignment target.")

        target = db.query(Project).filter(Project.id == target_project_id).first()
        if not target:
            raise ContextResolverError(f"Target project '{target_project_id}' not found.")

        from app.models.evidence import Evidence
        from app.models.source_event import SourceEvent

        evidence = (
            db.query(Evidence)
            .filter(Evidence.id == evidence_id, Evidence.project_id == UNKNOWN_CONTEXT_ID)
            .first()
        )
        if not evidence:
            raise ContextResolverError(f"Unknown Context evidence '{evidence_id}' not found.")

        source_event = db.query(SourceEvent).filter(SourceEvent.event_id == evidence.source_event_id).first()
        evidence.project_id = target_project_id
        if source_event:
            source_event.project_id = target_project_id
            payload = json.loads(source_event.payload_json or "{}")
            payload["context_status"] = "human_assigned"
            payload["assigned_project_id"] = target_project_id
            source_event.payload_json = json.dumps(payload)

        metadata = json.loads(evidence.metadata_json or "{}")
        metadata["context_status"] = "human_assigned"
        metadata["assigned_project_id"] = target_project_id
        metadata["assigned_by"] = actor_id
        metadata["reprocessing_requested"] = bool(trigger_reprocessing)
        evidence.metadata_json = json.dumps(metadata)
        db.commit()

        return {
            "evidence_id": evidence.id,
            "source_event_id": evidence.source_event_id,
            "project_id": target_project_id,
            "project_name": target.name,
            "previous_project_id": UNKNOWN_CONTEXT_ID,
            "status": "assigned",
            "actor_id": actor_id,
        }

    def route_or_quarantine(
        self,
        result: ContextResolutionResult,
        db: Session,
        workspace_id: str = "ws_default",
        tenant_id: str = "default_tenant",
    ) -> Tuple[Project, ContextResolutionResult]:
        if result.status == "resolved" and result.selected_project_id:
            project = (
                db.query(Project)
                .filter(Project.id == result.selected_project_id)
                .first()
            )
            if project and project.id != UNKNOWN_CONTEXT_ID:
                return project, result

        unknown = self.ensure_unknown_context_project(
            db=db,
            workspace_id=workspace_id,
            tenant_id=tenant_id,
        )
        result.status = "ambiguous" if result.status == "ambiguous" else "unknown"
        result.selected_project_id = None
        return unknown, result
