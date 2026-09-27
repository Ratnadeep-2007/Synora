import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship

logger = logging.getLogger(__name__)

AI_STATUS_AI = "ai"
AI_STATUS_DETERMINISTIC = "deterministic"


class VisualPlanService:
    """Produces a structured VisualPlan from Project State.

    The AI (NVIDIA NIM + DeepSeek) reasons about what should remain, change,
    be added or removed. When no semantic provider is available the service
    produces an explicitly-labelled DETERMINISTIC plan derived from Project
    State - it never presents deterministic output as AI output, and it never
    produces raw Excalidraw JSON in either case.
    """

    def __init__(self, client: Optional[Any] = None):
        self._explicit_client = client is not None
        self.client = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_plan(
        self,
        state_summary: Dict[str, Any],
        current_nodes: Optional[List[str]] = None,
        evidence_snippets: Optional[List[str]] = None,
        focus_prompt: Optional[str] = None,
        constraints: Optional[List[str]] = None,
    ) -> Tuple[VisualPlan, str]:
        """Return (plan, ai_status) where ai_status is 'ai' or 'deterministic'."""
        if self._explicit_client is not None:
            plan = self._call_client(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI

        if settings.LLM_PROVIDER.lower() == "nvidia" and settings.is_nvidia_nim_configured:
            plan = self._call_nim(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI

        return self._deterministic_plan(state_summary, current_nodes or []), AI_STATUS_DETERMINISTIC

    # ------------------------------------------------------------------
    # Semantic providers
    # ------------------------------------------------------------------
    def _build_prompt(
        self,
        state_summary: Dict[str, Any],
        current_nodes: List[str],
        evidence_snippets: List[str],
        focus_prompt: Optional[str],
        constraints: Optional[List[str]],
    ) -> str:
        schema = (
            '{"title": str, "layout_direction": "horizontal|vertical", '
            '"grouping_intent": [str], '
            '"nodes": [{"id": str, "label": str, "node_type": '
            '"client|service|datastore|actor|decision|requirement|group|note", '
            '"group": str|null, "emphasis": "normal|primary|muted", "annotations": [str]}], '
            '"relationships": [{"source": str, "target": str, "label": str|null, "style": "solid|dashed"}], '
            '"preserve": [str], "add": [str], "change": [str], "remove": [str], "notes": [str]}'
        )
        lines = [
            "You are the Synora visual planner. Produce a STRUCTURED VISUAL PLAN, not Excalidraw JSON.",
            "Decide what should remain, change, be added, and be removed, and how the result fits the existing composition.",
            "Prefer preserving a good existing layout over rebuilding the whole canvas.",
            "Use minimum text and maximum visual structure. Node labels must be short.",
            f"Respond with ONLY JSON matching: {schema}",
            "",
            "--- CURRENT PROJECT STATE ---",
            json.dumps(state_summary, default=str)[:4000],
            "",
            f"--- CURRENT CANVAS NODES --- {json.dumps(current_nodes)[:800]}",
        ]
        if evidence_snippets:
            lines += ["", "--- RELEVANT EVIDENCE ---"] + [f"- {s[:200]}" for s in evidence_snippets[:8]]
        if constraints:
            lines += ["", "--- VISUAL DESIGN CONSTRAINTS ---"] + [f"- {c}" for c in constraints]
        if focus_prompt:
            lines += ["", f"--- REQUESTED CHANGE --- {focus_prompt}"]
        return "\n".join(lines)

    def _parse(self, content: str, model: str) -> Optional[VisualPlan]:
        try:
            data = json.loads(content)
            plan = VisualPlan.model_validate(data)
            plan.model = model
            plan.prompt_version = "visual-plan-v1"
            return plan
        except Exception as exc:
            logger.warning("visual_plan_parse_failed: %s", exc)
            return None

    def _call_client(self, state, nodes, evidence, focus, constraints) -> Optional[VisualPlan]:
        prompt = self._build_prompt(state, nodes, evidence, focus, constraints)
        try:
            content = self.client.generate_visual_plan(prompt)
        except Exception as exc:
            logger.warning("visual_plan_client_failed: %s", exc)
            return None
        if not content:
            return None
        return self._parse(content, model=getattr(self.client, "model_name", "client"))

    def _call_nim(self, state, nodes, evidence, focus, constraints) -> Optional[VisualPlan]:
        import httpx

        prompt = self._build_prompt(state, nodes, evidence, focus, constraints)
        system_instruction = (
            "You are the Synora visual architecture planner. "
            "You return only strict JSON visual plans. You never return Excalidraw JSON."
        )
        payload = {
            "model": settings.NVIDIA_MODEL,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{settings.NVIDIA_BASE_URL.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.warning("visual_plan_nim_http_%s", resp.status_code)
                    return None
                content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("visual_plan_nim_failed: %s", exc)
            return None
        return self._parse(content, model=f"nvidia-nim/{settings.NVIDIA_MODEL}")

    # ------------------------------------------------------------------
    # Deterministic fallback (explicitly NOT AI)
    # ------------------------------------------------------------------
    def _deterministic_plan(
        self, state_summary: Dict[str, Any], current_nodes: List[str]
    ) -> VisualPlan:
        nodes: List[VisualNode] = []
        relationships: List[VisualRelationship] = []

        def add(node_id: str, label: str, node_type: str, group: Optional[str] = None):
            if any(n.id == node_id for n in nodes):
                return
            nodes.append(
                VisualNode(id=node_id, label=label[:40], node_type=node_type, group=group)
            )

        add("actor_user", "User", "actor")
        add("evidence", "Evidence", "datastore", group="pipeline")
        add("agent", "Synora Agent", "service", group="pipeline")
        add("state", "Project State", "datastore", group="pipeline")
        add("visual", "Living Workspace", "service", group="pipeline")

        architecture = state_summary.get("architecture") or []
        for index, entry in enumerate(architecture[:6]):
            label = (
                entry.get("component")
                if isinstance(entry, dict)
                else str(entry)
            ) or f"Component {index + 1}"
            add(f"arch_{index}", str(label), "service", group="architecture")

        relationships = [
            VisualRelationship(source="actor_user", target="evidence"),
            VisualRelationship(source="evidence", target="agent"),
            VisualRelationship(source="agent", target="state"),
            VisualRelationship(source="state", target="visual"),
        ]
        arch_ids = [n.id for n in nodes if n.group == "architecture"]
        for i in range(len(arch_ids) - 1):
            relationships.append(
                VisualRelationship(source=arch_ids[i], target=arch_ids[i + 1])
            )
        if arch_ids:
            relationships.append(VisualRelationship(source="state", target=arch_ids[0], style="dashed"))

        return VisualPlan(
            title=state_summary.get("title") or "Project Architecture",
            layout_direction="horizontal",
            grouping_intent=["pipeline", "architecture"],
            nodes=nodes,
            relationships=relationships,
            preserve=list(current_nodes),
            notes=["Deterministic plan derived from Project State (AI visual planner unavailable)."],
            model="deterministic",
            prompt_version="visual-plan-deterministic-v1",
        )
