from typing import Any, Dict, List, Optional, Tuple
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


class ContextResolverError(ValueError):
    """Raised when context resolution cannot be completed safely."""
    pass


class ContextResolverService:
    """
    Shared project-context intelligence for Meet, WhatsApp, and Excalidraw.

    Resolution is intentionally two-stage:
    1. Deterministic candidate generation from project metadata, source bindings and
       conversation continuity.
    2. Optional NVIDIA NIM / DeepSeek semantic ranking over only those candidates.

    The model proposes context; deterministic rules make the routing decision.
    Ambiguous or unknown events are quarantined in the system-managed Unknown Context project.
    """

    RESOLVED_CONFIDENCE = 0.78
    AMBIGUITY_CONFIDENCE = 0.55
    MIN_MARGIN = 0.10
    MAX_CANDIDATES_FOR_LLM = 6

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
                description=UNKNOWN_CONTEXT_DESCRIPTION,
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
                def _load_json(value: Optional[str]) -> List[Any]:
                    try:
                        data = json.loads(value or "[]")
                        return data if isinstance(data, list) else []
                    except Exception:
                        return []

                decisions = _load_json(state.decisions_json)
                requirements = _load_json(state.requirements_json)
                architecture = _load_json(state.architecture_json)
                constraints = _load_json(state.constraints_json)
                assumptions = _load_json(state.assumptions_json)

                state_data = {
                    "vision": state.vision,
                    "decisions": [
                        d.get("title") or d.get("text") or d.get("content", "")
                        if isinstance(d, dict) else str(d)
                        for d in decisions[:10]
                    ],
                    "requirements": [
                        r.get("title") or r.get("content", "")
                        if isinstance(r, dict) else str(r)
                        for r in requirements[:10]
                    ],
                    "architecture": [
                        a.get("name") or a.get("title") or a.get("label") or str(a)
                        if isinstance(a, dict) else str(a)
                        for a in architecture[:16]
                    ],
                    "constraints": [str(c) for c in constraints[:8]],
                    "assumptions": [str(a) for a in assumptions[:8]],
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
    def _tokenize(value: Any) -> List[str]:
        return [
            t for t in re.findall(r"[a-z0-9][a-z0-9_./-]*", str(value).lower())
            if len(t) >= 3
        ]

    @staticmethod
    def _metadata_text(metadata: Optional[Dict[str, Any]]) -> str:
        if not metadata:
            return ""
        values: List[str] = []
        for key in (
            "group_name",
            "meeting_title",
            "channel_name",
            "source_name",
            "participants",
            "recent_context",
            "thread_context",
            "conversation_context",
            "current_project_id",
        ):
            value = metadata.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                values.extend(str(v) for v in value)
            else:
                values.append(str(value))
        return " ".join(values)

    def _metadata_project_signals(
        self,
        metadata: Optional[Dict[str, Any]],
        project: Dict[str, Any],
    ) -> Tuple[float, List[str]]:
        if not metadata:
            return 0.0, []

        score = 0.0
        reasons: List[str] = []
        project_id = project["project_id"]

        # Exact source binding should dominate weak semantic similarity.
        bindings = metadata.get("project_bindings") or metadata.get("source_project_bindings") or {}
        if isinstance(bindings, dict):
            bound = bindings.get(metadata.get("group_jid")) or bindings.get(metadata.get("channel_name"))
            if bound == project_id:
                score += 65.0
                reasons.append("known source-to-project binding")

        if metadata.get("current_project_id") == project_id:
            score += 25.0
            reasons.append("explicit current project context")

        return score, reasons

    def _deterministic_candidates(
        self,
        text: str,
        project_records: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ContextCandidate]:
        lower = text.lower()
        combined = f"{lower} {self._metadata_text(metadata).lower()}".strip()
        text_tokens = set(self._tokenize(combined))

        stop_words = {
            "the", "and", "for", "with", "from", "that", "this", "will", "into",
            "have", "has", "are", "was", "were", "our", "your", "project",
            "system", "team", "today", "about", "using", "please", "would",
            "could", "should", "they", "their", "then", "than", "here",
        }

        results: List[ContextCandidate] = []

        for project in project_records:
            score = 0.0
            reasons: List[str] = []
            name = project["name"].lower()
            desc = project.get("description", "").lower()

            if project["project_id"].lower() in lower:
                score += 110.0
                reasons.append("explicit project ID")

            if name and name in lower:
                score += 48.0
                reasons.append("full project name")

            name_tokens = {
                t for t in self._tokenize(name) if t not in stop_words
            }
            for token in sorted(name_tokens):
                if token in text_tokens:
                    score += 12.0
                    if len(reasons) < 6:
                        reasons.append(f"name:{token}")

            desc_tokens = {
                t for t in self._tokenize(desc) if t not in stop_words
            }
            overlap = len(name_tokens & text_tokens)
            desc_overlap = len(desc_tokens & text_tokens)
            if desc_overlap:
                score += min(10.0, desc_overlap * 2.5)
                if len(reasons) < 6:
                    reasons.append(f"description_overlap:{desc_overlap}")

            for bucket_name, values, weight in (
                ("decision", project.get("decisions", []), 5.0),
                ("requirement", project.get("requirements", []), 4.5),
                ("architecture", project.get("architecture", []), 5.0),
                ("constraint", project.get("constraints", []), 3.0),
                ("assumption", project.get("assumptions", []), 2.5),
            ):
                bucket_best = 0
                for item in values:
                    item_tokens = {
                        t for t in self._tokenize(item) if t not in stop_words
                    }
                    bucket_best = max(bucket_best, len(item_tokens & text_tokens))
                if bucket_best:
                    score += min(15.0, bucket_best * weight)
                    if len(reasons) < 6:
                        reasons.append(f"{bucket_name}_overlap:{bucket_best}")

            binding_score, binding_reasons = self._metadata_project_signals(metadata, project)
            score += binding_score
            reasons.extend(binding_reasons)

            if score > 0:
                confidence = min(0.98, 0.40 + score / 125.0)
                results.append(
                    ContextCandidate(
                        project_id=project["project_id"],
                        project_name=project["name"],
                        confidence=round(confidence, 4),
                        reasons=reasons[:8],
                        basis=[
                            "deterministic project metadata",
                            "authoritative project state",
                            "source/conversation metadata",
                        ],
                    )
                )

        return sorted(results, key=lambda x: x.confidence, reverse=True)

    def _deterministic_resolution(
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
                model="deterministic-context-v2",
                prompt_version="context-v2",
                source="deterministic",
            )

        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        margin = top.confidence - second.confidence if second else top.confidence

        if top.confidence >= self.RESOLVED_CONFIDENCE and margin >= self.MIN_MARGIN:
            return ContextResolutionResult(
                status="resolved",
                selected_project_id=top.project_id,
                confidence=top.confidence,
                reasoning="Strong deterministic context match.",
                candidates=candidates[:self.MAX_CANDIDATES_FOR_LLM],
                model="deterministic-context-v2",
                prompt_version="context-v2",
                source="deterministic",
            )

        if top.confidence >= self.AMBIGUITY_CONFIDENCE:
            return ContextResolutionResult(
                status="ambiguous",
                selected_project_id=None,
                confidence=top.confidence,
                reasoning="More than one project may fit, or the evidence separation is too weak for safe routing.",
                candidates=candidates[:self.MAX_CANDIDATES_FOR_LLM],
                model="deterministic-context-v2",
                prompt_version="context-v2",
                source="deterministic",
            )

        return ContextResolutionResult(
            status="unknown",
            selected_project_id=None,
            confidence=top.confidence,
            reasoning="Context overlap is too weak to assign this source safely.",
            candidates=candidates[:self.MAX_CANDIDATES_FOR_LLM],
            model="deterministic-context-v2",
            prompt_version="context-v2",
            source="deterministic",
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
                model="deterministic-context-v2",
                prompt_version="context-v2",
                source="deterministic",
            )

        records = self._project_context_records(db, workspace_id=workspace_id)
        deterministic_candidates = self._deterministic_candidates(text, records, metadata)
        deterministic_result = self._deterministic_resolution(deterministic_candidates)

        if not records or not self._nim_available():
            return deterministic_result

        try:
            prompt = self._build_llm_prompt(text, records, metadata, deterministic_candidates)
            ai_result = self.llm_client.generate_structured(prompt, ContextResolutionResult)
            allowed_ids = {r["project_id"] for r in records}

            ai_result.candidates = [
                c for c in ai_result.candidates
                if c.project_id in allowed_ids
            ][:self.MAX_CANDIDATES_FOR_LLM]

            # AI cannot route without deterministic corroboration.
            deterministic_ids = {c.project_id for c in deterministic_candidates}

            if (
                ai_result.status == "resolved"
                and ai_result.selected_project_id in deterministic_ids
                and ai_result.confidence >= self.RESOLVED_CONFIDENCE
            ):
                return ContextResolutionResult(
                    status="resolved",
                    selected_project_id=ai_result.selected_project_id,
                    confidence=ai_result.confidence,
                    reasoning=ai_result.reasoning or "NIM/DeepSeek and deterministic context agreed.",
                    candidates=ai_result.candidates or deterministic_candidates[:self.MAX_CANDIDATES_FOR_LLM],
                    model=ai_result.model,
                    prompt_version=ai_result.prompt_version,
                    source="nim+deterministic",
                )

            # If AI is uncertain, preserve deterministic candidates for human triage.
            if ai_result.status in ("ambiguous", "unknown"):
                merged: List[ContextCandidate] = list(ai_result.candidates)
                seen = {c.project_id for c in merged}
                for candidate in deterministic_candidates[:self.MAX_CANDIDATES_FOR_LLM]:
                    if candidate.project_id not in seen:
                        merged.append(candidate)
                triage_status = "ambiguous" if ai_result.status == "ambiguous" or merged else "unknown"
                return ContextResolutionResult(
                    status=triage_status,
                    selected_project_id=None,
                    confidence=max(ai_result.confidence, deterministic_result.confidence),
                    reasoning=ai_result.reasoning or deterministic_result.reasoning,
                    candidates=merged[:self.MAX_CANDIDATES_FOR_LLM],
                    model=ai_result.model,
                    prompt_version=ai_result.prompt_version,
                    source="nim+deterministic",
                )

        except Exception as exc:
            logger.warning("Context NIM resolution failed; falling back to deterministic result: %s", exc)

        return deterministic_result

    def _nim_available(self) -> bool:
        return self.llm_client.__class__.__name__ == "NvidiaNimLLMClient"

    def _build_llm_prompt(
        self,
        text: str,
        project_records: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
        deterministic_candidates: Optional[List[ContextCandidate]] = None,
    ) -> str:
        lines = [
            "Resolve the project context for this source content.",
            "You are selecting only from existing project IDs supplied below.",
            "Never invent, rename, or infer an unauthorized project.",
            "If two or more projects are plausible, return ambiguous.",
            "If evidence is insufficient, return unknown.",
            "Consider the full conversation window, metadata, current project state, architecture, decisions, requirements, and prior context.",
            "",
            "CONTENT:",
            text,
            "",
            "METADATA:",
            json.dumps(metadata or {}, ensure_ascii=True),
            "",
            "DETERMINISTIC CANDIDATES:",
        ]
        for candidate in (deterministic_candidates or [])[:self.MAX_CANDIDATES_FOR_LLM]:
            lines.append(candidate.model_dump_json())

        lines.extend(["", "PROJECT CONTEXT CANDIDATES:"])
        candidate_ids = {
            c.project_id for c in (deterministic_candidates or [])[:self.MAX_CANDIDATES_FOR_LLM]
        }
        for record in project_records:
            if candidate_ids and record["project_id"] not in candidate_ids:
                continue
            # Bound the context sent to the model.
            lines.append(json.dumps(record, ensure_ascii=True))

        return "
".join(lines)

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
        previous_project_id = evidence.project_id

        evidence.project_id = target_project_id
        if source_event:
            source_event.project_id = target_project_id
            payload = json.loads(source_event.payload_json or "{}")
            payload["context_status"] = "human_assigned"
            payload["assigned_project_id"] = target_project_id
            payload["reprocessing_requested"] = bool(trigger_reprocessing)
            source_event.payload_json = json.dumps(payload)

        metadata = json.loads(evidence.metadata_json or "{}")
        metadata["context_status"] = "human_assigned"
        metadata["assigned_project_id"] = target_project_id
        metadata["assigned_by"] = actor_id
        metadata["reprocessing_requested"] = bool(trigger_reprocessing)
        evidence.metadata_json = json.dumps(metadata)
        assigned = {
            "evidence_id": evidence.id,
            "source_event_id": evidence.source_event_id,
            "project_id": target_project_id,
            "project_name": target.name,
            "previous_project_id": previous_project_id,
            "status": "assigned",
            "actor_id": actor_id,
            "reprocessing_requested": bool(trigger_reprocessing),
        }
        db.commit()

        if trigger_reprocessing:
            # Human assignment should not leave the target project without the
            # semantic interpretation that was previously quarantined.
            try:
                from app.services.meeting_intelligence import MeetingIntelligenceService
                intelligence = MeetingIntelligenceService()
                candidates = intelligence.analyze_evidence_records(
                    evidence_records=[evidence],
                    project_id=target_project_id,
                    db=db,
                    meeting_id=evidence.meeting_id,
                    source_name=evidence.source,
                    context_status="human_assigned",
                    context_confidence=1.0,
                    context_model="human_assignment",
                )
                assigned["candidates_created"] = len(candidates)
            except Exception as exc:
                logger.exception("Reprocessing of assigned Unknown Context evidence failed: %s", exc)
                assigned["reprocessing_status"] = "failed"
                assigned["reprocessing_error"] = str(exc)
        return assigned

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
        result.selected_project_id = None
        result.status = "ambiguous" if result.status == "ambiguous" else "unknown"
        return unknown, result
