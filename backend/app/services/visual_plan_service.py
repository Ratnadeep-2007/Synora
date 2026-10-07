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
                '"preserve": [str], "add": [str], "change": [str], "remove": [str], '
                '"notes": [{"text": str, "kind": "decision|requirement|directive|action|risk|assumption|note", '
                '"order": int, "evidence_ids": [str]}]}'
            )
            lines = [
                f"You are the visual architecture designer for the project: '{project_title}'.",
                "Design this project's canvas with complete freedom. Choose the nodes, relationships,",
                "grouping and layout that best express what this project is and where it is going.",
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
            '"preserve": [str], "add": [str], "change": [str], "remove": [str], '
            '"notes": [{"text": str, "kind": "decision|requirement|directive|action|risk|assumption|note", '
            '"order": int, "evidence_ids": [str]}]}'
        )
        lines = [
            f"You are the Synora visual architecture planner for the project: '{project_title}'.",
            "Produce a STRUCTURED, PRODUCTION-GRADE VISUAL PLAN (pure JSON, never Excalidraw JSON).",
            "",
            "CRITICAL ARCHITECTURAL DIRECTIVES:",
            f"1. DOMAIN FOCUS: Model the concrete domain architecture of '{project_title}' (e.g. client apps, core services, autonomous agents, datastores, message queues, external APIs).",
            "2. ZERO PLATFORM BOILERPLATE: NEVER emit internal Synora platform meta-nodes ('Synora Agent', 'Project State', 'Living Workspace', 'Evidence', or generic 'BA'/'Tech'/'Frappe' nodes). Every node must be a functional component of the target project.",
            "3. GROUNDING IS MANDATORY: every node, relationship and note MUST carry "
            '"evidence_ids" listing the EVIDENCE ids that justify it, taken verbatim from the '
            "--- RELEVANT EVIDENCE --- block below. A node you cannot cite will be discarded "
            "before rendering. Do NOT invent a component just because a real system of this "
            "kind would normally have one. Fewer, grounded nodes beat many speculative ones.",
            '4. SUPPORT TYPE: use "support_type": "explicit" when the evidence states that the '
            'component exists, and "inferred" when you reasoned it out. Never claim "explicit" '
            "for something the evidence only implies.",
            "5. VISUAL-FIRST ARCHITECTURE: organize grounded components into logical layers such as Experience, Core Logic, Data, Integrations when the evidence supports them.",
            "6. NODE LABELS: Keep node labels short, crisp, and professional (2-4 words).",
            "7. RELATIONSHIPS: Connect components with directional data flow and a short edge label describing what actually moves.",
            "8. SUPPORTING NOTES: use them only for decisions, constraints, assumptions, risks, or open questions. Each note must cite evidence_ids.",
            "9. HUMAN READABILITY: A reviewer should be able to answer what enters the system, what transforms it, where state is stored, and what external systems participate.",
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
        """Ensures the plan always carries concise, high-signal notes even if the model omitted them."""
        if not plan:
            return None
        if not plan.notes:
            auto_notes = []
            if focus:
                clean_f = focus.replace("Update the living visual project memory from this WhatsApp batch.", "").strip()
                clean_f = clean_f.replace("Extract only meaningful project knowledge and represent it as concise visual notes, decisions, requirements, actions, questions, risks, and architecture relationships. Preserve useful current content and do not dump the transcript. Batch content:", "").strip()
                if clean_f:
                    first_line = clean_f.splitlines()[0].strip()
                    auto_notes.append(f"⚡ Directive: {first_line[:90]}")
            if state.get("vision"):
                auto_notes.append(f"💡 Scope: {str(state['vision'])[:90]}")
            reqs = state.get("requirements") or []
            if reqs:
                req = reqs[0]
                req_title = req.get("title") if isinstance(req, dict) else str(req)
                auto_notes.append(f"📋 Requirement: {str(req_title)[:90]}")
            decs = state.get("decisions") or []
            if decs:
                dec = decs[0]
                dec_title = dec.get("title") or dec.get("text") if isinstance(dec, dict) else str(dec)
                auto_notes.append(f"💡 Decision: {str(dec_title)[:90]}")
            plan.notes = auto_notes or ["Domain architecture components and operational directives."]
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
