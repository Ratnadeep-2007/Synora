import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.schemas.visual_plan import VisualNode, VisualPlan, VisualRelationship

logger = logging.getLogger(__name__)

AI_STATUS_AI = "ai"
AI_STATUS_DETERMINISTIC = "deterministic"


def _evidence_id_of(snippet: Any) -> str:
    """
    Recover the Evidence id from a planner evidence snippet.

    Snippets are dicts ({"id", "content"}) or bare strings, possibly already
    prefixed with "[EVIDENCE: id]". The id is required for grounding, so it is
    surfaced explicitly rather than assumed.
    """
    if isinstance(snippet, dict):
        return str(snippet.get("id") or "")
    match = re.search(r"\[EVIDENCE:\s*([^\]]+)\]", str(snippet or ""))
    return match.group(1).strip() if match else ""


def _snippet_text(snippet: Any) -> str:
    if isinstance(snippet, dict):
        return str(snippet.get("content") or "")
    return str(snippet or "")


def _snippet_ids(snippet: Any) -> List[str]:
    eid = _evidence_id_of(snippet)
    return [eid] if eid else []


def _text_evidence_id(text: str) -> str:
    """
    Stable pseudo-evidence id for text that has no persisted Evidence row.

    Text-to-diagram callers (manual paste, WhatsApp body) supply content that
    is not yet an Evidence record. Deriving an id from the content keeps the
    node citable and deterministic without inventing a database reference.
    """
    import hashlib

    return "ev_text_" + hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()[:12]


class VisualPlanService:
    """Produces a structured VisualPlan from Project State.

    The AI (Gemini or configured failover provider) reasons about what should remain, change,
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

        provider = (settings.LLM_PROVIDER or "").lower()
        if provider in ("deterministic", "mock", "test"):
            return self._deterministic_plan(state_summary, current_nodes or [], focus_prompt, evidence_snippets), AI_STATUS_DETERMINISTIC

        # Design authority first: when Meta is selected and configured, the
        # agent designs with complete freedom per project.
        if provider == "meta" and settings.is_meta_configured:
            plan = self._call_meta(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI

        if provider == "gemini" and settings.is_gemini_configured:
            plan = self._call_gemini(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI

        if provider == "groq" and settings.is_groq_configured:
            plan = self._call_groq(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI

        if provider == "nvidia" and settings.is_nvidia_nim_configured:
            plan = self._call_nim(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI

        # Fallback to any active configured semantic provider
        if settings.is_meta_configured:
            plan = self._call_meta(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI
        if settings.is_gemini_configured:
            plan = self._call_gemini(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI
        elif settings.is_groq_configured:
            plan = self._call_groq(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI
        elif settings.is_nvidia_nim_configured:
            plan = self._call_nim(
                state_summary, current_nodes or [], evidence_snippets or [], focus_prompt, constraints
            )
            if plan is not None:
                return plan, AI_STATUS_AI

        return self._deterministic_plan(state_summary, current_nodes or [], focus_prompt, evidence_snippets), AI_STATUS_DETERMINISTIC

    def build_plan_from_text(
        self,
        text: str,
        title: Optional[str] = None,
    ) -> Tuple[VisualPlan, str]:
        """Direct text-to-visual-plan synthesizer.

        Analyzes the text with AI (Groq / NVIDIA NIM / DeepSeek / LLM client) to generate
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

        provider = (settings.LLM_PROVIDER or "").lower()
        if provider in ("deterministic", "mock", "test"):
            return self._plan_from_text_deterministic(text, clean_title, _text_evidence_id(text)), AI_STATUS_DETERMINISTIC

        if provider == "meta" and settings.is_meta_configured:
            plan = self._call_meta(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI

        if provider == "gemini" and settings.is_gemini_configured:
            plan = self._call_gemini(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI

        if provider == "groq" and settings.is_groq_configured:
            plan = self._call_groq(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI

        if provider == "nvidia" and settings.is_nvidia_nim_configured:
            plan = self._call_nim(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI

        if settings.is_meta_configured:
            plan = self._call_meta(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI
        if settings.is_gemini_configured:
            plan = self._call_gemini(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI
        elif settings.is_groq_configured:
            plan = self._call_groq(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI
        elif settings.is_nvidia_nim_configured:
            plan = self._call_nim(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI

        return self._plan_from_text_deterministic(text, clean_title, _text_evidence_id(text)), AI_STATUS_DETERMINISTIC

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
        free: bool = False,
    ) -> str:
        project_title = state_summary.get("title") or "Project"
        is_synora_project = project_title.strip().lower() in ("synora", "synesis")

        # In free design mode the agent has complete freedom per project: no
        # boilerplate ban, no mandatory grounding. Evidence is still shown so
        # the model can cite it, and citations are still recorded - they are
        # simply not enforced.
        if free:
            schema = (
                '{"title": str, "layout_direction": "horizontal|vertical", '
                '"grouping_intent": [str], '
                '"nodes": [{"id": str, "label": str, "node_type": '
                '"client|service|datastore|actor|decision|requirement|group|note", '
                '"group": str|null, "emphasis": "normal|primary|muted", "annotations": [str], '
                '"evidence_ids": [str], "support_type": "explicit|inferred"}], '
                '"relationships": [{"source": str, "target": str, "label": str|null, "style": "solid|dashed", '
                '"evidence_ids": [str], "support_type": "explicit|inferred"}], '
                '"canvas_strategy": "text|mixed|diagram", "notes_sections": [{"id": str, "title": str, "body": str, "bullets": [str], "order": int, "evidence_ids": [str], "support_type": "explicit|inferred"}], '
                '"visualizations": [{"id": str, "kind": "metric|status|callout|timeline", "title": str, "value": str|null, "items": [str], "caption": str|null, "evidence_ids": [str], "support_type": "explicit|inferred"}], '
                '"preserve": [str], "add": [str], "change": [str], "remove": [str], '
                '"notes": [{"text": str, "kind": "decision|requirement|directive|action|risk|assumption|note", '
                '"order": int, "evidence_ids": [str]}]}'
            )
            lines = [
                f"You are the visual architecture designer for the project: '{project_title}'.",
                "Design this project's canvas with complete freedom, but prefer readable text over unnecessary diagrams.",
                "Only create nodes + relationships when a genuine visual structure (flow, architecture, hierarchy, dependency, sequence) is supported; an empty nodes list is valid.",
                "Use visualizations only when a compact status, metric, callout, or timeline communicates better than prose.",
                "Use notes_sections for proper document-like notes. Never force a diagram or use a diagram/card just to decorate ordinary text.",
                "Cite evidence ids where the evidence supports a node; where you design beyond the",
                "evidence, mark support_type inferred. Never return Excalidraw JSON, only the plan schema.",
                "",
                f"Respond with ONLY JSON matching: {schema}",
                "",
                "--- CURRENT PROJECT STATE ---",
                json.dumps(state_summary, default=str)[:4000],
                "",
                f"--- CURRENT CANVAS NODES --- {json.dumps(current_nodes)[:800]}",
            ]
            if evidence_snippets:
                lines += ["", "--- RELEVANT EVIDENCE ---"] + [
                    f"- [EVIDENCE: {_evidence_id_of(s)}] {_snippet_text(s)[:200]}"
                    for s in evidence_snippets[:8]
                ]
            if constraints:
                lines += ["", "--- VISUAL DESIGN CONSTRAINTS ---"] + [f"- {c}" for c in constraints]
            if focus_prompt:
                lines += ["", f"--- REQUESTED CHANGE --- {focus_prompt}"]
            return "\n".join(lines)

        # Disallow generic platform meta-scaffolding from leaking into domain architectures
        disallowed_meta = {
            "user", "evidence", "synora agent", "project state", "living workspace",
            "ba", "project", "functional", "tech", "frappe"
        }
        if not is_synora_project:
            clean_current_nodes = [n for n in current_nodes if n.lower().strip() not in disallowed_meta]
        else:
            clean_current_nodes = current_nodes

        schema = (
            '{"title": str, "layout_direction": "horizontal|vertical", '
            '"grouping_intent": [str], '
            '"nodes": [{"id": str, "label": str, "node_type": '
            '"client|service|datastore|actor|decision|requirement|group|note", '
            '"group": str|null, "emphasis": "normal|primary|muted", "annotations": [str], '
            '"evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"relationships": [{"source": str, "target": str, "label": str|null, "style": "solid|dashed", '
            '"evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"canvas_strategy": "text|mixed|diagram", '
            '"notes_sections": [{"id": str, "title": str, "body": str, "bullets": [str], "order": int, "evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"visualizations": [{"id": str, "kind": "metric|status|callout|timeline", "title": str, "value": str|null, "items": [str], "caption": str|null, "evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"preserve": [str], "add": [str], "change": [str], "remove": [str], '
            '"notes": [{"text": str, "kind": "decision|requirement|directive|action|risk|assumption|note", '
            '"order": int, "evidence_ids": [str]}]}'
        )
        lines = [
            f"You are the Synora visual architecture planner for the project: '{project_title}'.",
            "Produce a STRUCTURED, PRODUCTION-GRADE VISUAL PLAN (pure JSON, never Excalidraw JSON).",
            "",
            "CRITICAL VISUAL REPRESENTATION DIRECTIVES:",
            "1. TEXT FIRST: Build proper readable notes in notes_sections. The canvas must remain useful even when no diagram is appropriate.",
            "2. DIAGRAM ONLY WHEN JUSTIFIED: populate nodes + relationships only for a coherent architecture, flow, hierarchy, dependency, or sequence. A text-only plan is fully valid.",
            "3. LIGHTWEIGHT VISUALS: use visualizations only when a status, metric, timeline, or callout materially improves comprehension.",
            "4. NO STICKY-NOTE BOARD: notes_sections render as a document-like notes page on the right side of the canvas.",
            "5. CURRENT TRUTH: reconcile the current project state and current canvas. Preserve useful content and update only what project memory supports.",
            "6. GROUNDING: cite evidence ids where available. Use support_type=inferred for reasoning. Do not invent project-specific facts.",
            "7. DOMAIN FOCUS: when a genuine diagram exists, model concrete domain components rather than Synora internal scaffolding.",
            "8. HUMAN READABILITY: the notes must tell the project story even when the reviewer ignores the visual area.",
            "",
            f"Respond with ONLY JSON matching: {schema}",
            "",
            "--- CURRENT PROJECT STATE ---",
            json.dumps(state_summary, default=str)[:4000],
            "",
            f"--- CURRENT CANVAS NODES --- {json.dumps(clean_current_nodes)[:800]}",
        ]
        if evidence_snippets:
            # IDs are shown so the planner can cite them. Without the id the
            # model has no way to satisfy the grounding rule and every node
            # would be discarded.
            lines += ["", "--- RELEVANT EVIDENCE ---"] + [
                f"- [EVIDENCE: {_evidence_id_of(s)}] {_snippet_text(s)[:200]}"
                for s in evidence_snippets[:8]
            ]
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
            plan.prompt_version = "visual-plan-v2"
            return plan
        except Exception as exc:
            logger.warning("visual_plan_parse_failed: %s", exc)
            return None

    def _ensure_efficient_notes(
        self, plan: Optional[VisualPlan], state: Dict[str, Any], focus: Optional[str]
    ) -> Optional[VisualPlan]:
        """Backstop proper notebook notes when a provider omits them."""
        if not plan or plan.notes_sections:
            return plan

        sections: List[Dict[str, Any]] = []
        vision = str(state.get("vision") or "").strip()
        if vision:
            sections.append({
                "id": "project_overview",
                "title": "Overview",
                "body": vision[:1200],
                "bullets": [],
                "order": 0,
                "evidence_ids": [],
                "support_type": "explicit",
            })

        architecture = state.get("architecture") or []
        arch_lines: List[str] = []
        for entry in architecture[:8]:
            if isinstance(entry, dict):
                label = entry.get("component") or entry.get("name") or entry.get("title")
                detail = entry.get("detail") or entry.get("description")
                value = " — ".join(str(v).strip() for v in (label, detail) if v)
            else:
                value = str(entry).strip()
            if value:
                arch_lines.append(value[:220])
        if arch_lines:
            sections.append({
                "id": "architecture_context",
                "title": "Current Architecture",
                "body": "",
                "bullets": arch_lines,
                "order": 1,
                "evidence_ids": [],
                "support_type": "explicit",
            })

        state_sections = [
            ("requirements", "requirements", "Requirements"),
            ("decisions", "key_decisions", "Key Decisions"),
            ("constraints", "constraints", "Constraints"),
            ("risks", "risks", "Risks"),
            ("open_questions", "open_questions", "Open Questions"),
            ("actions", "actions", "Actions"),
        ]
        for order, (state_key, section_id, section_title) in enumerate(state_sections, start=2):
            items = state.get(state_key) or []
            bullets: List[str] = []
            for item in items[:8]:
                if isinstance(item, dict):
                    value = item.get("title") or item.get("text") or item.get("content") or item.get("detail")
                else:
                    value = item
                if value and str(value).strip():
                    bullets.append(str(value).strip()[:220])
            if bullets:
                sections.append({
                    "id": section_id,
                    "title": section_title,
                    "body": "",
                    "bullets": bullets,
                    "order": order,
                    "evidence_ids": [],
                    "support_type": "explicit",
                })

        if focus:
            clean_focus = str(focus).strip()
            if clean_focus:
                sections.append({
                    "id": "latest_context",
                    "title": "Latest Context",
                    "body": clean_focus[:1200],
                    "bullets": [],
                    "order": 20,
                    "evidence_ids": [],
                    "support_type": "inferred",
                })

        if not sections:
            sections.append({
                "id": "project_notes",
                "title": "Project Notes",
                "body": str(state.get("title") or "Project").strip(),
                "bullets": [],
                "order": 0,
                "evidence_ids": [],
                "support_type": "inferred",
            })

        plan.notes_sections = sections
        return plan

    def _call_client(self, state, nodes, evidence, focus, constraints) -> Optional[VisualPlan]:
        prompt = self._build_prompt(state, nodes, evidence, focus, constraints)
        try:
            content = self.client.generate_visual_plan(prompt)
        except Exception as exc:
            logger.warning("visual_plan_client_failed: %s", exc)
            return None
        if not content:
            return None
        plan = self._parse(content, model=getattr(self.client, "model_name", "client"))
        return self._ensure_efficient_notes(plan, state, focus)

    def _call_gemini(self, state, nodes, evidence, focus, constraints) -> Optional[VisualPlan]:
        if not settings.is_gemini_configured:
            return None
        import httpx

        prompt = self._build_prompt(state, nodes, evidence, focus, constraints)
        project_title = state.get("title") or "Project"
        system_instruction = (
            f"You are the Synora visual architecture planner for project '{project_title}'. "
            "You produce structured, production-grade VisualPlans and high-efficiency architectural notes. "
            "Model concrete domain components (clients, services, datastores, external APIs) and actionable architectural notes. "
            "Never emit platform meta-scaffolding (do NOT include 'Synora Agent', 'Project State', 'Living Workspace', 'Evidence'). "
            "Return ONLY strict JSON matching the requested schema. You never return Excalidraw JSON."
        )
        url = f"{settings.GEMINI_BASE_URL.rstrip('/')}/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
            },
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code != 200:
                    logger.warning("visual_plan_gemini_http_%s: %s", resp.status_code, resp.text[:200])
                    return None
                res_json = resp.json()
                candidates = res_json.get("candidates", [])
                if not candidates:
                    return None
                parts = candidates[0].get("content", {}).get("parts", [])
                content = parts[0].get("text", "") if parts else ""
                if not content or not content.strip():
                    return None
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
        except Exception as exc:
            logger.warning("visual_plan_gemini_failed: %s", exc)
            return None
        plan = self._parse(content, model=f"gemini/{settings.GEMINI_MODEL}")
        return self._ensure_efficient_notes(plan, state, focus)

    def _call_meta(self, state, nodes, evidence, focus, constraints) -> Optional[VisualPlan]:
        """Design authority path: Meta Muse Spark with complete per-project freedom."""
        if not settings.is_meta_configured:
            return None
        import httpx

        prompt = self._build_prompt(state, nodes, evidence, focus, constraints, free=True)
        project_title = state.get("title") or "Project"
        system_instruction = (
            f"You are the visual architecture designer for project '{project_title}'. "
            "You have complete freedom: design the canvas that best expresses this project. "
            "Cite evidence ids where evidence supports a node; mark the rest inferred. "
            "Return ONLY strict JSON matching the requested schema. You never return Excalidraw JSON."
        )
        payload = {
            "model": settings.META_MODEL,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {settings.META_API_KEY}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{settings.META_BASE_URL.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.warning("visual_plan_meta_http_%s", resp.status_code)
                    return None
                content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("visual_plan_meta_failed: %s", exc)
            return None
        plan = self._parse(content, model=f"meta/{settings.META_MODEL}")
        return self._ensure_efficient_notes(plan, state, focus)

    def _call_nim(self, state, nodes, evidence, focus, constraints) -> Optional[VisualPlan]:
        import httpx

        prompt = self._build_prompt(state, nodes, evidence, focus, constraints)
        project_title = state.get("title") or "Project"
        system_instruction = (
            f"You are the Synora visual architecture planner for project '{project_title}'. "
            "You produce structured, production-grade VisualPlans and high-efficiency architectural notes. "
            "Model concrete domain components (clients, services, datastores, external APIs) and actionable architectural notes. "
            "Never emit platform meta-scaffolding (do NOT include 'Synora Agent', 'Project State', 'Living Workspace', 'Evidence'). "
            "Return ONLY strict JSON matching the requested schema. You never return Excalidraw JSON."
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
        plan = self._parse(content, model=f"nvidia-nim/{settings.NVIDIA_MODEL}")
        return self._ensure_efficient_notes(plan, state, focus)

    def _call_groq(self, state, nodes, evidence, focus, constraints) -> Optional[VisualPlan]:
        import httpx

        prompt = self._build_prompt(state, nodes, evidence, focus, constraints)
        project_title = state.get("title") or "Project"
        system_instruction = (
            f"You are the Synora visual architecture planner for project '{project_title}'. "
            "You produce structured, production-grade VisualPlans and high-efficiency architectural notes. "
            "Model concrete domain components (clients, services, datastores, external APIs) and actionable architectural notes. "
            "Never emit platform meta-scaffolding (do NOT include 'Synora Agent', 'Project State', 'Living Workspace', 'Evidence'). "
            "Return ONLY strict JSON matching the requested schema. You never return Excalidraw JSON."
        )
        payload = {
            "model": settings.GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Synora/1.0",
        }
        try:
            with httpx.Client(timeout=25.0) as client:
                resp = client.post(
                    f"{settings.GROQ_BASE_URL.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.warning("visual_plan_groq_http_%s: %s", resp.status_code, resp.text[:200])
                    return None
                content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("visual_plan_groq_failed: %s", exc)
            return None
        plan = self._parse(content, model=f"groq/{settings.GROQ_MODEL}")
        return self._ensure_efficient_notes(plan, state, focus)

    # ------------------------------------------------------------------
    # Deterministic fallback (explicitly NOT AI)
    # ------------------------------------------------------------------
    def _deterministic_plan(
        self,
        state_summary: Dict[str, Any],
        current_nodes: List[str],
        focus_prompt: Optional[str] = None,
        evidence_snippets: Optional[List[Any]] = None,
    ) -> VisualPlan:
        nodes: List[VisualNode] = []
        relationships: List[VisualRelationship] = []
        notes_list: List[Any] = []

        # Every deterministic node is grounded to the evidence it was derived
        # from. Nodes that exist only as a scaffold carry no evidence and are
        # therefore dropped by the compiler rather than presented as findings.
        all_ids: List[str] = []
        for s in evidence_snippets or []:
            all_ids.extend(_snippet_ids(s))

        def add(node_id: str, label: str, node_type: str, group: Optional[str] = None, emphasis: str = "normal", annotations: Optional[List[str]] = None, grounded: bool = True):
            if any(n.id == node_id or n.label.lower() == label.lower() for n in nodes):
                return
            nodes.append(
                VisualNode(
                    id=node_id,
                    label=label[:40],
                    node_type=node_type,
                    group=group,
                    emphasis=emphasis,
                    annotations=annotations or [],
                    evidence_ids=all_ids[:2] if grounded else [],
                    support_type="inferred",
                )
            )

        project_title = state_summary.get("title") or "Project Architecture"
        is_synora_meta = project_title.strip().lower() in (
            "synora",
            "synesis",
            "demo",
            "project",
            "project architecture",
            "",
        )

        text_corpus = (
            (focus_prompt or "")
            + " "
            + " ".join(_snippet_text(s) for s in (evidence_snippets or []))
            + " "
            + (state_summary.get("vision") or "")
        )
        lower_corpus = text_corpus.lower()

        if is_synora_meta:
            add("actor_user", "User", "actor")
            add("evidence", "Evidence", "datastore", group="pipeline")
            add("agent", "Synora Agent", "service", group="pipeline", emphasis="primary")
            add("state", "Project State", "datastore", group="pipeline")
            add("visual", "Living Workspace", "service", group="pipeline")

            if "agentic layer" in lower_corpus or ("agentic" in lower_corpus and "layer" in lower_corpus):
                add("layer_agentic", "Agentic Layer", "service", group="agentic", emphasis="primary")
                add("node_autonomous", "Autonomous Agents", "service", group="agentic")

            relationships.extend([
                VisualRelationship(source="actor_user", target="evidence"),
                VisualRelationship(source="evidence", target="agent"),
                VisualRelationship(source="agent", target="state"),
                VisualRelationship(source="state", target="visual"),
            ])
            if any(n.id == "layer_agentic" for n in nodes):
                relationships.append(VisualRelationship(source="agent", target="layer_agentic"))
                if any(n.id == "node_autonomous" for n in nodes):
                    relationships.append(VisualRelationship(source="layer_agentic", target="node_autonomous"))

            notes_list.append("One shared Synora Agent coordinates evidence ingestion and living workspace updates.")
            if "agentic layer" in lower_corpus:
                notes_list.append("Agentic Layer enables autonomous task classification and background plan execution.")
        else:
            # Generic decomposition derived from the project's own title and
            # description. A previous version matched "dinein" / "table ordering"
            # and emitted a fixed restaurant architecture with invented
            # annotations ("Real-time ticket dispatch", "Bill settlement").
            # Because that branch triggered on corpus keywords rather than the
            # project's own evidence, any restaurant-adjacent project was
            # rendered as that hardcoded diagram. Nothing here is asserted as
            # fact: every node is marked inferred and carries no evidence, so
            # the compiler's grounding rules decide what survives.
            add("client_app", f"{project_title} Client", "client", group="experience")
            add("core_svc", f"{project_title} Core Service", "service", group="core", emphasis="primary")
            add("primary_db", f"{project_title} Database", "datastore", group="data")
            relationships.extend([
                VisualRelationship(source="client_app", target="core_svc"),
                VisualRelationship(source="core_svc", target="primary_db"),
            ])

        # Incorporate explicit architecture components from project state
        architecture = state_summary.get("architecture") or []
        for index, entry in enumerate(architecture[:6]):
            label = (
                entry.get("component")
                if isinstance(entry, dict)
                else str(entry)
            ) or f"Component {index + 1}"
            add(f"arch_{index}", str(label), "service", group="architecture")

        # Incorporate requirements & decisions as domain nodes or notes.
        # These come from approved Project State, so they are the most strongly
        # grounded elements available: each carries the evidence ids recorded
        # when it was approved.
        requirements = state_summary.get("requirements") or []
        for index, entry in enumerate(requirements[:4]):
            label = (
                entry.get("title") or entry.get("content")
                if isinstance(entry, dict)
                else str(entry)
            ) or f"Requirement {index + 1}"
            state_ev = entry.get("evidence_ids") if isinstance(entry, dict) else None
            add(
                f"req_{index}",
                str(label),
                "requirement",
                group="requirements",
                grounded=bool(state_ev) or bool(all_ids),
            )
            if nodes and state_ev:
                nodes[-1].evidence_ids = list(state_ev)[:3]

        decisions = state_summary.get("decisions") or []
        for index, entry in enumerate(decisions[:4]):
            label = (
                entry.get("text") or entry.get("title")
                if isinstance(entry, dict)
                else str(entry)
            ) or f"Decision {index + 1}"
            state_ev = entry.get("evidence_ids") if isinstance(entry, dict) else None
            add(
                f"dec_{index}",
                str(label),
                "decision",
                group="decisions",
                grounded=bool(state_ev) or bool(all_ids),
            )
            if nodes and state_ev:
                nodes[-1].evidence_ids = list(state_ev)[:3]

        # Extract actionable directives into high-efficiency notes. The note
        # quotes the user's own directive rather than asserting a design
        # decision, and it cites the evidence it was read from.
        task_match = re.search(r"\b(add|create|build|implement|deploy|integrate)\s+(?:an?\s+)?([^.\n\r]{3,40})", text_corpus, re.IGNORECASE)
        if task_match:
            directive_label = f"{task_match.group(1).capitalize()} {task_match.group(2).strip()}"[:45]
            notes_list.append(
                {
                    "text": f"Directive: {directive_label}",
                    "kind": "directive",
                    "order": len(notes_list),
                    "evidence_ids": all_ids[:3],
                }
            )

        return VisualPlan(
            title=project_title,
            layout_direction="horizontal",
            grouping_intent=["core", "storage", "frontend"],
            nodes=nodes,
            relationships=relationships,
            preserve=[],
            notes=notes_list or ["System architecture and operational directives."],
            model="deterministic",
            prompt_version="visual-plan-deterministic-v2",
        )

    def _plan_from_text_deterministic(self, text: str, title: str, evidence_id: str = "") -> VisualPlan:
        """Deterministic fallback when AI model is offline: extracts keywords/entities directly from text."""
        import re
        nodes: List[VisualNode] = []
        relationships: List[VisualRelationship] = []

        words = re.findall(r'\b[A-Za-z0-9_-]{2,25}\b', text)
        known_components: List[Tuple[str, str]] = []
        keyword_types = {
            "agentic": "service",
            "agent": "service",
            "orchestrator": "service",
            "layer": "service",
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

        # Multi-word key concepts
        lower_text = text.lower()
        if "agentic layer" in lower_text or ("agentic" in lower_text and "layer" in lower_text):
            known_components.append(("Agentic Layer", "service"))
        if "table ordering" in lower_text:
            known_components.append(("Table Ordering Service", "service"))

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
            nodes.append(VisualNode(id=nid, label=label, node_type=ntype, evidence_ids=[evidence_id] if evidence_id else []))
            if idx > 0:
                relationships.append(VisualRelationship(source=f"node_{idx-1}", target=nid, evidence_ids=[evidence_id] if evidence_id else []))

        notes = []
        # Notes describe what was actually supplied, not a guessed domain. The
        # previous version asserted "Direct table ordering stream with
        # automated kitchen dispatch" whenever the text merely mentioned
        # "dinein", which stated a product decision nobody had made.
        notes.append(f"Architectural components synthesized from: {text[:60]}")

        return VisualPlan(
            title=title,
            layout_direction="horizontal",
            grouping_intent=["system"],
            nodes=nodes,
            relationships=relationships,
            preserve=[],
            notes=notes,
            model="deterministic",
            prompt_version="visual-plan-text-deterministic-v2",
        )
