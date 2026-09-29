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
        if self._explicit_client:
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

    def build_plan_from_text(
        self,
        text: str,
        title: Optional[str] = None,
    ) -> Tuple[VisualPlan, str]:
        """Direct text-to-visual-plan synthesizer.

        Analyzes the text with AI (NVIDIA NIM / DeepSeek / LLM client) to generate
        a tailored VisualPlan (nodes, edges, groups, layout), or parses
        the text deterministically if the model is offline.
        """
        clean_title = title or (text[:40].strip() + ("..." if len(text) > 40 else ""))
        state_summary = {
            "title": clean_title,
            "vision": text,
            "architecture": [],
            "requirements": [{"title": "Requirement", "detail": text}],
            "decisions": [],
            "constraints": [],
            "raw_text": text,
        }

        if self._explicit_client:
            plan = self._call_client(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI

        if settings.LLM_PROVIDER.lower() == "nvidia" and settings.is_nvidia_nim_configured:
            plan = self._call_nim(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI

        return self._plan_from_text_deterministic(text, clean_title), AI_STATUS_DETERMINISTIC

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

        # Architecture components become the technical layer of the diagram.
        architecture = state_summary.get("architecture") or []
        for index, entry in enumerate(architecture[:6]):
            label = (
                entry.get("component")
                if isinstance(entry, dict)
                else str(entry)
            ) or f"Component {index + 1}"
            add(f"arch_{index}", str(label), "service", group="architecture")

        # Requirements and decisions are first-class visual nodes (decision cards).
        requirements = state_summary.get("requirements") or []
        for index, entry in enumerate(requirements[:4]):
            label = (
                entry.get("title") or entry.get("content")
                if isinstance(entry, dict)
                else str(entry)
            ) or f"Requirement {index + 1}"
            add(f"req_{index}", str(label), "requirement", group="requirements")

        decisions = state_summary.get("decisions") or []
        for index, entry in enumerate(decisions[:4]):
            label = (
                entry.get("text") or entry.get("title")
                if isinstance(entry, dict)
                else str(entry)
            ) or f"Decision {index + 1}"
            add(f"dec_{index}", str(label), "decision", group="decisions")

        relationships = [
            VisualRelationship(source="actor_user", target="evidence"),
            VisualRelationship(source="evidence", target="agent"),
            VisualRelationship(source="agent", target="state"),
            VisualRelationship(source="state", target="visual"),
        ]

        def chain(group: str, source: str):
            ids = [n.id for n in nodes if n.group == group]
            for i in range(len(ids) - 1):
                relationships.append(
                    VisualRelationship(source=ids[i], target=ids[i + 1])
                )
            if ids:
                relationships.append(
                    VisualRelationship(source=source, target=ids[0], style="dashed")
                )

        chain("architecture", "state")
        chain("requirements", "agent")
        chain("decisions", "state")

        # `preserve` refers to visual element ids the plan keeps. The
        # deterministic planner rebuilds the canvas from Project State, so it
        # preserves nothing by id; existing-but-dropped content is reported
        # through the proposal diff (nodes_removed) instead.
        return VisualPlan(
            title=state_summary.get("title") or "Project Architecture",
            layout_direction="horizontal",
            grouping_intent=["pipeline", "architecture"],
            nodes=nodes,
            relationships=relationships,
            preserve=[],
            notes=["Deterministic plan derived from Project State (AI visual planner unavailable)."],
            model="deterministic",
            prompt_version="visual-plan-deterministic-v1",
        )

    def _plan_from_text_deterministic(self, text: str, title: str) -> VisualPlan:
        """Deterministic fallback when AI model is offline: extracts keywords/entities directly from text."""
        import re
        nodes: List[VisualNode] = []
        relationships: List[VisualRelationship] = []

        words = re.findall(r'\b[A-Za-z0-9_-]{2,25}\b', text)
        known_components: List[Tuple[str, str]] = []
        keyword_types = {
            "gateway": "service",
            "api": "service",
            "service": "service",
            "server": "service",
            "backend": "service",
            "frontend": "client",
            "client": "client",
            "ui": "client",
            "web": "client",
            "mobile": "client",
            "app": "client",
            "database": "datastore",
            "db": "datastore",
            "postgres": "datastore",
            "postgresql": "datastore",
            "mysql": "datastore",
            "mongodb": "datastore",
            "redis": "datastore",
            "cache": "datastore",
            "queue": "queue",
            "kafka": "queue",
            "rabbitmq": "queue",
            "celery": "queue",
            "auth": "service",
            "payment": "service",
            "stripe": "external",
            "user": "actor",
            "customer": "actor",
            "admin": "actor",
        }

        found_types = set()
        for w in words:
            wl = w.lower()
            if wl in keyword_types and wl not in found_types:
                found_types.add(wl)
                known_components.append((w.capitalize(), keyword_types[wl]))

        if not known_components:
            clauses = [c.strip() for c in re.split(r'[,.;\n]+', text) if len(c.strip()) > 3]
            for idx, clause in enumerate(clauses[:6]):
                label = clause[:30].strip()
                known_components.append((label, "service"))

        if not known_components:
            known_components = [("Input System", "service"), ("Processing Engine", "service"), ("Output Storage", "datastore")]

        for idx, (label, ntype) in enumerate(known_components):
            nid = f"node_{idx}"
            nodes.append(VisualNode(id=nid, label=label, node_type=ntype))
            if idx > 0:
                relationships.append(VisualRelationship(source=f"node_{idx-1}", target=nid))

        return VisualPlan(
            title=title,
            layout_direction="horizontal",
            grouping_intent=["system"],
            nodes=nodes,
            relationships=relationships,
            preserve=[],
            notes=["Synthesized directly from input text."],
            model="deterministic",
            prompt_version="visual-plan-text-deterministic-v1",
        )
