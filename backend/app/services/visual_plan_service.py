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

        provider = (settings.LLM_PROVIDER or "").lower()
        if provider in ("deterministic", "mock", "test"):
            return self._deterministic_plan(state_summary, current_nodes or [], focus_prompt, evidence_snippets), AI_STATUS_DETERMINISTIC

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
        if settings.is_groq_configured:
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
            return self._plan_from_text_deterministic(text, clean_title), AI_STATUS_DETERMINISTIC

        if provider == "groq" and settings.is_groq_configured:
            plan = self._call_groq(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI

        if provider == "nvidia" and settings.is_nvidia_nim_configured:
            plan = self._call_nim(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI

        if settings.is_groq_configured:
            plan = self._call_groq(state_summary, [], [text], text, None)
            if plan is not None:
                return plan, AI_STATUS_AI
        elif settings.is_nvidia_nim_configured:
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
        project_title = state_summary.get("title") or "Project"
        is_synora_project = project_title.strip().lower() in ("synora", "synesis")

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
            '"group": str|null, "emphasis": "normal|primary|muted", "annotations": [str]}], '
            '"relationships": [{"source": str, "target": str, "label": str|null, "style": "solid|dashed"}], '
            '"preserve": [str], "add": [str], "change": [str], "remove": [str], "notes": [str], "conversation_notes": [str]}'
        )
        lines = [
            f"You are the Synora visual architecture planner for the project: '{project_title}'.",
            "Produce a STRUCTURED, PRODUCTION-GRADE VISUAL PLAN (pure JSON, never Excalidraw JSON).",
            "",
            "CRITICAL ARCHITECTURAL DIRECTIVES:",
            f"1. DOMAIN FOCUS: Model the concrete domain architecture of '{project_title}' (e.g. client apps, core services, autonomous agents, datastores, message queues, external APIs).",
            "2. ZERO PLATFORM BOILERPLATE: NEVER emit internal Synora platform meta-nodes ('Synora Agent', 'Project State', 'Living Workspace', 'Evidence', or generic 'BA'/'Tech'/'Frappe' nodes). Every node must be a functional component of the target project.",
            "3. HIGH-EFFICIENCY ARCHITECTURAL NOTES: You MUST provide 2 to 4 concise, high-signal, actionable notes in the 'notes' array. Each note must state a concrete architectural decision, integration specification, technical constraint, or operational scope (e.g. 'Event-driven message stream for real-time order dispatch', 'Autonomous table ordering with QR token verification'). Do NOT leave 'notes' empty.",
            "4. NODE LABELS: Keep node labels short, crisp, and professional (2-4 words, e.g. 'Table Ordering Agent', 'Kitchen Display API', 'Order DB', 'Customer Web App').",
            "5. RELATIONSHIPS: Connect components logically with directional data flow relationships.",
            "6. CONVERSATION NOTES: Convert each relevant evidence snippet into one concise note. Preserve the meaning and speaker/source wording when available. Do not merge separate messages into one note. Return at most 8 notes, ordered chronologically as provided. These will be rendered one below another.",
            "7. VISUAL HIERARCHY: Prefer a clear architecture flow with clients at the edge, core services in the middle, data/external systems downstream, and grouped sections where useful.",

            "",
            f"Respond with ONLY JSON matching: {schema}",
            "",
            "--- CURRENT PROJECT STATE ---",
            json.dumps(state_summary, default=str)[:4000],
            "",
            f"--- CURRENT CANVAS NODES --- {json.dumps(clean_current_nodes)[:800]}",
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
        evidence_snippets: Optional[List[str]] = None,
    ) -> VisualPlan:
        nodes: List[VisualNode] = []
        relationships: List[VisualRelationship] = []
        notes_list: List[str] = []

        def add(node_id: str, label: str, node_type: str, group: Optional[str] = None, emphasis: str = "normal", annotations: Optional[List[str]] = None):
            if any(n.id == node_id or n.label.lower() == label.lower() for n in nodes):
                return
            nodes.append(
                VisualNode(id=node_id, label=label[:40], node_type=node_type, group=group, emphasis=emphasis, annotations=annotations or [])
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

        text_corpus = (focus_prompt or "") + " " + " ".join(evidence_snippets or []) + " " + (state_summary.get("vision") or "")
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
            # Concrete domain architecture for user projects (e.g. Dinein, Solana, etc.)
            is_dinein = "dinein" in project_title.lower() or "dinein" in lower_corpus or "table ordering" in lower_corpus
            if is_dinein:
                add("client_qr", "Table QR Web App", "client", group="frontend")
                add("agent_table", "Table Ordering Agent", "service", group="core", emphasis="primary", annotations=["Autonomous order processing", "Validates item availability"])
                add("svc_kds", "Kitchen Display API", "service", group="core", annotations=["Real-time ticket dispatch"])
                add("svc_pos", "POS Integration Service", "service", group="external", annotations=["Bill settlement"])
                add("db_orders", "Orders & Menu Database", "datastore", group="storage", annotations=["PostgreSQL ledger"])

                relationships.extend([
                    VisualRelationship(source="client_qr", target="agent_table"),
                    VisualRelationship(source="agent_table", target="db_orders"),
                    VisualRelationship(source="agent_table", target="svc_kds"),
                    VisualRelationship(source="agent_table", target="svc_pos"),
                ])
                notes_list.append("⚡ Table Ordering Agent: Autonomously validates table orders, calculates bills, and dispatches to kitchen.")
                notes_list.append("📋 Real-time KDS: WebSocket push stream to Kitchen Display System for zero-latency ticket display.")
                notes_list.append("💡 POS Integration: Direct sync with POS ledger avoiding manual cashier re-entry.")
            else:
                # Domain decomposition based on project title
                add("client_app", f"{project_title} Client", "client")
                add("core_svc", f"{project_title} Core Service", "service", emphasis="primary")
                add("primary_db", f"{project_title} Database", "datastore")
                relationships.extend([
                    VisualRelationship(source="client_app", target="core_svc"),
                    VisualRelationship(source="core_svc", target="primary_db"),
                ])
                notes_list.append(f"Core service architecture and data persistence for {project_title}.")

        # Incorporate explicit architecture components from project state
        architecture = state_summary.get("architecture") or []
        for index, entry in enumerate(architecture[:6]):
            label = (
                entry.get("component")
                if isinstance(entry, dict)
                else str(entry)
            ) or f"Component {index + 1}"
            add(f"arch_{index}", str(label), "service", group="architecture")

        # Incorporate requirements & decisions as domain nodes or notes
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

        # Extract actionable directives into high-efficiency notes
        import re
        task_match = re.search(r"\b(add|create|build|implement|deploy|integrate)\s+(?:an?\s+)?([^.\n\r]{3,40})", text_corpus, re.IGNORECASE)
        if task_match and not any("⚡" in n for n in notes_list):
            directive_label = f"{task_match.group(1).capitalize()} {task_match.group(2).strip()}"[:45]
            notes_list.append(f"⚡ Directive: {directive_label}")

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

    def _plan_from_text_deterministic(self, text: str, title: str) -> VisualPlan:
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
            nodes.append(VisualNode(id=nid, label=label, node_type=ntype))
            if idx > 0:
                relationships.append(VisualRelationship(source=f"node_{idx-1}", target=nid))

        notes = []
        if "agent" in lower_text or "automated" in lower_text:
            notes.append("⚡ Automated Agent: Autonomously handles processing and service orchestration without manual intervention.")
        if "table ordering" in lower_text or "dinein" in lower_text:
            notes.append("📋 Direct table ordering stream with automated kitchen dispatch and POS integration.")
        if not notes:
            notes.append(f"Architectural components synthesized from: {text[:60]}")

        return VisualPlan(
            title=title,
            layout_direction="horizontal",
            grouping_intent=["system"],
            nodes=nodes,
            relationships=relationships,
            preserve=[],
            notes=notes,
            conversation_notes=[str(s).strip()[:280] for s in [text] if str(s).strip()][:8],
            model="deterministic",
            prompt_version="visual-plan-text-deterministic-v2",
        )
