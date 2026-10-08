import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.schemas.visual_plan import NoteBlock, NoteSection, NotesDocument, VisualNode, VisualPlan, VisualRelationship

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

        schema = (
            '{"title": str, '
            '"canvas_strategy": "text|mixed|diagram", '
            '"layout_direction": "horizontal|vertical", '
            '"grouping_intent": [str], '
            '"nodes": [{"id": str, "label": str, "node_type": str, "group": str|null, '
            '"emphasis": str|null, "annotations": [str], "evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"relationships": [{"source": str, "target": str, "label": str|null, "style": str|null, '
            '"evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"notes_document": {"title": str, "subtitle": str|null, '
            '"sections": [{"id": str, "title": str, "order": int, '
            '"blocks": [{"id": str, "block_type": str, "text": str, "items": [str], "rows": [[str]], '
            '"title": str|null, "level": int, "tone": str|null, "evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"updated_label": str|null}, '
            '"visualizations": [{"id": str, "kind": str, "title": str|null, "purpose": str|null, '
            '"elements": [{"id": str, "primitive_type": str, "text": str|null, "title": str|null, '
            '"source": str|null, "target": str|null, "group": str|null, "width": number|null, "height": number|null, '
            '"style": object, "metadata": object, "evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"content": object, "evidence_ids": [str], "support_type": "explicit|inferred"}], '
            '"preserve": [str], "add": [str], "change": [str], "remove": [str]}'
        )

        free_mode = bool(free or settings.visual_design_free)
        prompt_lines = [
            f"You are the visual canvas designer for '{project_title}'.",
            "Your output is the living visual workspace for ONE project or ONE scoped conversation.",
            "",
            "CONTENT AND REPRESENTATION ARE OPEN-ENDED.",
            "There is NO required note-taking structure, no mandatory sections, no fixed note categories, no fixed diagram type, and no minimum number of diagrams.",
            "Choose the representation that best communicates the information: prose, headings, bullets, tables, callouts, sketches, timelines, flows, hierarchies, matrices, or a custom composition.",
            "Do not force unrelated information into categories merely because a schema offers them.",
            "For project work, keep useful context understandable as a maintained working canvas and evolve obsolete material instead of blindly accumulating duplicates.",
            "For meeting work, capture only the meeting discussion and do not import project-wide facts from elsewhere.",
            "",
            "VISUAL MODELING.",
            "Use diagrams or visual compositions when they add meaning; omit them when text is clearer.",
            "You may invent any semantic visualization form. There is no fixed visualization vocabulary.",
            "You may choose semantic primitive types, labels, dimensions, grouping, connectors, typography, shapes, emphasis, and visual semantics.",
            "NEVER provide x, y, position, canvas coordinates, or absolute placement. The renderer/compiler handles geometry and collision avoidance.",
            "Never emit raw Excalidraw JSON.",
            "",
            "CURRENT CANVAS.",
            "Treat the current canvas as an existing working document. Preserve useful content, update stale representations, and avoid pointless duplication.",
        ]

        if free_mode:
            prompt_lines += [
                "",
                "DESIGN FREEDOM: use your strongest judgment. There is no requirement to create a diagram or visualization, and no fixed taxonomy for visual form.",
                "The only layout restriction is that you must not choose coordinates; all placement is handled after you return the semantic plan.",
            ]
        else:
            prompt_lines += [
                "",
                "GROUNDING: cite evidence_ids whenever a claim is directly supported by the supplied evidence. Mark reasoning as inferred rather than pretending it was stated.",
                "Do not invent project-specific facts. Prefer a smaller accurate visual model over a larger speculative one.",
            ]

        prompt_lines += [
            "",
            f"Return ONLY JSON matching this schema: {schema}",
            "",
            "--- CURRENT PROJECT MEMORY ---",
            json.dumps(state_summary, default=str)[:7000],
            "",
            "--- CURRENT CANVAS SUMMARY ---",
            json.dumps(current_nodes, default=str)[:2500],
        ]

        if evidence_snippets:
            prompt_lines += ["", "--- RECENT PROJECT EVIDENCE ---"]
            prompt_lines += [
                f"- [EVIDENCE: {_evidence_id_of(s)}] {_snippet_text(s)[:700]}"
                for s in evidence_snippets[:16]
            ]

        if constraints:
            prompt_lines += ["", "--- SYSTEM CANVAS CONSTRAINTS ---"] + [f"- {c}" for c in constraints]
        if focus_prompt:
            prompt_lines += ["", f"--- REQUESTED FOCUS --- {focus_prompt}"]

        return "\n".join(prompt_lines)

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
        """Guarantee a coherent document notebook even when an LLM omits one."""
        if not plan:
            return None

        if plan.notes_document is None:
            raw_sections: List[Dict[str, Any]] = []

            def _value(item: Any, *keys: str) -> str:
                if isinstance(item, dict):
                    for key in keys:
                        value = item.get(key)
                        if value:
                            return str(value).strip()
                    return ""
                return str(item).strip() if item is not None else ""

            vision = str(state.get("vision") or state.get("description") or "").strip()
            if vision:
                raw_sections.append({
                    "id": "project_overview",
                    "title": "Overview",
                    "order": 0,
                    "blocks": [{
                        "id": "overview_summary",
                        "block_type": "paragraph",
                        "text": vision[:1800],
                        "evidence_ids": [],
                        "support_type": "inferred",
                    }],
                })

            for order, (state_key, section_id, section_title) in enumerate([
                ("goals", "goals", "Goals"),
                ("requirements", "requirements", "Requirements"),
                ("architecture", "architecture", "Current Architecture"),
                ("decisions", "key_decisions", "Key Decisions"),
                ("constraints", "constraints", "Constraints"),
                ("risks", "risks", "Risks"),
                ("open_questions", "open_questions", "Open Questions"),
                ("actions", "actions", "Actions"),
                ("milestones", "milestones", "Milestones"),
            ], start=1):
                entries = state.get(state_key) or []
                blocks: List[Dict[str, Any]] = []
                for index, item in enumerate(entries[:10]):
                    value = _value(item, "title", "text", "content", "detail", "description", "component", "name")
                    if not value:
                        continue
                    block_type = "bullets"
                    if isinstance(item, dict) and item.get("type") in ("checklist", "numbered", "paragraph", "callout"):
                        block_type = str(item["type"])
                    blocks.append({
                        "id": f"{section_id}_item_{index}",
                        "block_type": block_type,
                        "items": [value] if block_type in ("bullets", "numbered", "checklist") else [],
                        "text": value if block_type not in ("bullets", "numbered", "checklist") else "",
                        "evidence_ids": list(item.get("evidence_ids") or [])[:4] if isinstance(item, dict) else [],
                        "support_type": "explicit" if isinstance(item, dict) and item.get("evidence_ids") else "inferred",
                    })
                if blocks:
                    raw_sections.append({
                        "id": section_id,
                        "title": section_title,
                        "order": order,
                        "blocks": blocks,
                    })

            if not raw_sections and plan.notes:
                blocks = []
                for index, item in enumerate(plan.notes[:12]):
                    text_value = _value(item, "text", "content")
                    if text_value:
                        blocks.append({
                            "id": f"legacy_note_{index}",
                            "block_type": "paragraph",
                            "text": text_value[:500],
                            "evidence_ids": list(item.get("evidence_ids") or [])[:4] if isinstance(item, dict) else [],
                            "support_type": "explicit" if isinstance(item, dict) and item.get("evidence_ids") else "inferred",
                        })
                if blocks:
                    raw_sections.append({
                        "id": "recent_context",
                        "title": "Recent Context",
                        "order": 20,
                        "blocks": blocks,
                    })

            if focus:
                raw_sections.append({
                    "id": "latest_context",
                    "title": "Latest Context",
                    "order": 30,
                    "blocks": [{
                        "id": "latest_context_text",
                        "block_type": "paragraph",
                        "text": str(focus).strip()[:1500],
                        "evidence_ids": [],
                        "support_type": "inferred",
                    }],
                })

            if not raw_sections:
                raw_sections = [{
                    "id": "project_notes",
                    "title": "Project Notes",
                    "order": 0,
                    "blocks": [{
                        "id": "project_identity",
                        "block_type": "paragraph",
                        "text": str(state.get("title") or "Project").strip(),
                        "evidence_ids": [],
                        "support_type": "inferred",
                    }],
                }]

            plan.notes_document = NotesDocument(
                title=str(state.get("title") or "PROJECT NOTES").strip(),
                subtitle="Living project notebook maintained from project memory",
                sections=[NoteSection.model_validate(section) for section in raw_sections],
                updated_label="Maintained automatically from project memory",
            )

        # Keep the older notes_sections API populated for existing callers.
        if not plan.notes_sections:
            plan.notes_sections = list(plan.notes_document.sections)

        return plan

    def _call_client(self, state, nodes, evidence, focus, constraints) -> Optional[VisualPlan]:
        prompt = self._build_prompt(state, nodes, evidence, focus, constraints, free=settings.visual_design_free)
        try:
            content = self.client.generate_visual_plan(prompt)
        except Exception as exc:
            logger.warning("visual_plan_client_failed: %s", exc)
            return None
        if not content:
            return None
        plan = self._parse(content, model=getattr(self.client, "model_name", "client"))
        return plan if settings.visual_design_free else self._ensure_efficient_notes(plan, state, focus)

    def _call_gemini(self, state, nodes, evidence, focus, constraints) -> Optional[VisualPlan]:
        if not settings.is_gemini_configured:
            return None
        import httpx

        prompt = self._build_prompt(state, nodes, evidence, focus, constraints, free=settings.visual_design_free)
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
        return plan if settings.visual_design_free else self._ensure_efficient_notes(plan, state, focus)

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
        return plan if settings.visual_design_free else self._ensure_efficient_notes(plan, state, focus)

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
        return plan if settings.visual_design_free else self._ensure_efficient_notes(plan, state, focus)

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
        # In free design mode, an unavailable model must not silently fall back to
        # the old fixed architecture template. Preserve the user's content as a
        # plain derived notebook entry instead of fabricating a diagram.
        if settings.visual_design_free:
            project_title = str(state_summary.get("title") or "Project Notes")
            source_text = " ".join(
                _snippet_text(item) for item in (evidence_snippets or []) if _snippet_text(item).strip()
            ).strip()
            source_text = source_text or str(
                focus_prompt or state_summary.get("vision") or state_summary.get("description") or ""
            ).strip()
            source_text = " ".join(source_text.split())[:5000]
            return VisualPlan(
                title=project_title,
                canvas_strategy="text",
                model="deterministic",
                prompt_version="visual-plan-text-deterministic-v2",
                notes_document=NotesDocument(
                    title=project_title,
                    subtitle="Deterministic fallback — semantic design provider unavailable",
                    sections=[
                        NoteSection(
                            id="notes",
                            title="Notes",
                            order=0,
                            blocks=[
                                NoteBlock(
                                    id="notes_content",
                                    block_type="paragraph",
                                    text=source_text or "No source content available yet.",
                                    evidence_ids=[_evidence_id_of(item) for item in (evidence_snippets or []) if _evidence_id_of(item)][:8],
                                    support_type="explicit" if evidence_snippets else "inferred",
                                )
                            ],
                        )
                    ],
                    updated_label="Deterministic fallback",
                ),
            )

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
