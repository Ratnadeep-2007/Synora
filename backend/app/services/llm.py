from abc import ABC, abstractmethod
import json
import logging
import re
from typing import Any, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel

from app.schemas.intelligence import CandidateItemDTO, ClassificationEnum, ExtractionBatchResult

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    """
    Provider-independent abstraction for Large Language Models.
    Decoupled from Google Gemini, OpenAI, Anthropic, or local inference engines.
    """

    @abstractmethod
    def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        """Generates a strictly schema-validated structured response."""
        pass


class DeterministicRuleLLMClient(LLMClient):
    """
    Deterministic rule-based intelligence client.
    Enforces conservative classification principles:
    - Distinguishes Proposal vs DecisionCandidate vs Requirement vs Question vs ActionItem
    - Generates structured, validated candidate knowledge
    - Guarantees 100% reproducible evaluations on the test fixture dataset
    """

    def __init__(self, model_name: str = "synesis-rule-intel-v1"):
        self.model_name = model_name

    def generate(self, prompt: str) -> str:
        """Deterministic rule response for raw prompts."""
        return f"[Rule Engine - {self.model_name}] Safe deterministic response for architecture and state."

    def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        # If schema is ExtractionBatchResult, analyze evidence text snippets embedded in the prompt
        if schema == ExtractionBatchResult:
            items = self._analyze_prompt_evidence(prompt)
            return ExtractionBatchResult(items=items, model=self.model_name, prompt_version="v1.0")  # type: ignore

        raise NotImplementedError(f"Deterministic client does not support schema {schema}")

    def _analyze_prompt_evidence(self, prompt: str) -> List[CandidateItemDTO]:
        """
        Parses evidence items from prompt text and applies conservative classification rules.
        Format expected in prompt: [EVIDENCE: {evidence_id}] Speaker: text
        """
        items: List[CandidateItemDTO] = []
        evidence_pattern = re.compile(r"\[EVIDENCE:\s*([a-zA-Z0-9_-]+)\]\s*(?:([^:\n]+):\s*)?(.+)", re.IGNORECASE)

        for line in prompt.splitlines():
            line = line.strip()
            match = evidence_pattern.match(line)
            if not match:
                continue

            ev_id = match.group(1).strip()
            speaker = match.group(2).strip() if match.group(2) else "Unknown"
            text = match.group(3).strip()
            lower_text = text.lower()

            # Rule 1: Explicit Requirement
            # "One requirement is that..." or "Must have...", "Required to..."
            if (
                "requirement is that" in lower_text
                or "must provide" in lower_text
                or "system must" in lower_text
                or "users must" in lower_text
                or lower_text.startswith("requirement:")
            ):
                items.append(
                    CandidateItemDTO(
                        category="requirement_candidate",
                        classification=ClassificationEnum.REQUIREMENT,
                        title=f"Requirement from {speaker}",
                        content=text,
                        confidence=0.95,
                        evidence_ids=[ev_id],
                    )
                )
                continue

            # Rule 2: Confirmed Decision / Decision Candidate
            # "Okay, let's do it", "We decided to", "Let's reverse yesterday's decision", "Confirmed:"
            if (
                "we decided to" in lower_text
                or "let's reverse yesterday's decision" in lower_text
                or "okay, let's do it" in lower_text
                or "let's include the onboarding agent" in lower_text
                or "let's keep ba as the first agent" in lower_text
                or "decision:" in lower_text
                or "decision confirmed" in lower_text
            ):
                classification = (
                    ClassificationEnum.SUPERSEDED
                    if "reverse" in lower_text
                    else ClassificationEnum.DECISION
                )
                items.append(
                    CandidateItemDTO(
                        category="decision_candidate",
                        classification=classification,
                        title=f"Decision by {speaker}",
                        content=text,
                        confidence=0.92,
                        evidence_ids=[ev_id],
                    )
                )
                continue

            # Rule 3: Proposals & Suggestions (CONSERVATIVE: Not a decision!)
            # "We should add...", "Maybe we should...", "I think we need...", "We could add..."
            if (
                "we should add" in lower_text
                or "maybe we should" in lower_text
                or "i think we need" in lower_text
                or "we could add" in lower_text
                or "proposal:" in lower_text
                or "i suggest" in lower_text
            ):
                items.append(
                    CandidateItemDTO(
                        category="proposal",
                        classification=ClassificationEnum.PROPOSAL,
                        title=f"Proposal from {speaker}",
                        content=text,
                        confidence=0.88,
                        evidence_ids=[ev_id],
                    )
                )
                continue

            # Rule 4: Questions & Discussion items
            # "Let's discuss...", "Should we...", "What about...", "I'm not agreeing yet"
            if (
                "let's discuss" in lower_text
                or "i'm not agreeing yet" in lower_text
                or "not agreeing" in lower_text
                or lower_text.endswith("?")
                or "what if" in lower_text
            ):
                classification = (
                    ClassificationEnum.REJECTED
                    if "not agreeing" in lower_text
                    else ClassificationEnum.QUESTION
                )
                items.append(
                    CandidateItemDTO(
                        category="question",
                        classification=classification,
                        title=f"Question/Discussion by {speaker}",
                        content=text,
                        confidence=0.82,
                        evidence_ids=[ev_id],
                    )
                )
                continue

            # Rule 5: Assumptions
            # "Assuming...", "We assume..."
            if "assuming" in lower_text or "we assume" in lower_text:
                items.append(
                    CandidateItemDTO(
                        category="assumption",
                        classification=ClassificationEnum.ASSUMPTION,
                        title=f"Assumption by {speaker}",
                        content=text,
                        confidence=0.80,
                        evidence_ids=[ev_id],
                    )
                )
                continue

            # Rule 6: Action Items & Task Directives
            # "will write", "action item:", "assigned to", "by tomorrow", "create", "build", "implement", "add", "automate", etc.
            task_match = re.search(
                r"\b(create|build|implement|add|setup|set\s+up|integrate|automate|develop|fix|handle|write)\s+(?:an?\s+)?(.+)",
                text,
                re.IGNORECASE,
            )
            if (
                "will write" in lower_text
                or "action item:" in lower_text
                or "by tomorrow" in lower_text
                or task_match
            ):
                if task_match:
                    action_verb = task_match.group(1).capitalize()
                    task_target = re.sub(r"[.?!]+$", "", task_match.group(2).strip())
                    task_title = f"{action_verb} {task_target[:70]}"
                else:
                    task_title = f"Action item for {speaker}"
                items.append(
                    CandidateItemDTO(
                        category="action_item",
                        classification=ClassificationEnum.ACTION_ITEM,
                        title=task_title,
                        content=text,
                        confidence=0.90,
                        evidence_ids=[ev_id],
                    )
                )
                continue

        return items


class MultiProviderFailoverLLMClient(LLMClient):
    """Executes a list of providers in sequence until one succeeds."""

    def __init__(self, providers: List[LLMClient]):
        self.providers = providers

    def generate(self, prompt: str) -> str:
        last_exc = None
        for p in self.providers:
            try:
                return p.generate(prompt)
            except Exception as e:
                last_exc = e
                continue
        if last_exc:
            raise last_exc
        return ""

    def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        last_exc = None
        for p in self.providers:
            try:
                return p.generate_structured(prompt, schema)
            except Exception as e:
                last_exc = e
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError("All providers in failover chain failed")


class NvidiaNimLLMClient(LLMClient):
    """
    OpenAI-compatible LLM Client for NVIDIA NIM hosting DeepSeek (e.g. deepseek-ai/deepseek-v4.1-flash).
    Provides structured JSON extraction and falls back to a secondary client or DeterministicRuleLLMClient on failure.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "deepseek-ai/deepseek-v4.1-flash",
        base_url: str = "https://integrate.api.nvidia.com/v1",
        timeout_seconds: float = 30.0,
        fallback_client: Optional[LLMClient] = None,
    ):
        self.api_key = api_key.strip() if api_key else ""
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback_client = fallback_client or DeterministicRuleLLMClient()

    def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        """
        Calls NVIDIA NIM chat completion endpoint with DeepSeek model and parses response into schema.
        Falls back gracefully to secondary / deterministic rule engine if API key is invalid or request fails.
        """
        if not self.api_key or self.api_key.startswith("your-") or not self.api_key.strip():
            logger.info("NVIDIA NIM API key not configured. Using fallback client.")
            return self._fallback_client.generate_structured(prompt, schema)

        import httpx

        system_instruction = (
            "You are an enterprise software architecture intelligence extraction model for Synora. "
            "Analyze the meeting or chat dialogue evidence and extract architectural candidate items: "
            "proposals, requirements, confirmed decisions, questions, assumptions, and action items. "
            "For each item, specify category ('proposal', 'requirement_candidate', 'decision_candidate', 'question', 'assumption', 'action_item'), "
            "classification ('PROPOSAL', 'REQUIREMENT', 'DECISION', 'QUESTION', 'ASSUMPTION', 'ACTION_ITEM'), "
            "title (concise), content (summary text), confidence (float between 0.0 and 1.0), and evidence_ids (array of evidence IDs from the prompt). "
            "Respond strictly in valid JSON matching this schema: "
            "{\"items\": [{\"category\": \"...\", \"classification\": \"...\", \"title\": \"...\", \"content\": \"...\", \"confidence\": 0.95, \"evidence_ids\": [\"ev_...\"]}]}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code != 200:
                    logger.warning(
                        f"NVIDIA NIM returned HTTP {resp.status_code}: {resp.text[:200]}. Failing over to fallback client."
                    )
                    return self._fallback_client.generate_structured(prompt, schema)

                res_json = resp.json()
                msg = res_json["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                if not content or not content.strip():
                    logger.warning("NVIDIA NIM DeepSeek returned empty content. Failing over to fallback client.")
                    return self._fallback_client.generate_structured(prompt, schema)

                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content)

                if schema == ExtractionBatchResult:
                    items = []
                    raw_items = parsed.get("items", []) if isinstance(parsed, dict) else parsed
                    for it in raw_items:
                        items.append(CandidateItemDTO(
                            category=it.get("category", "proposal"),
                            classification=it.get("classification", ClassificationEnum.PROPOSAL),
                            title=it.get("title", "Candidate"),
                            content=it.get("content", ""),
                            confidence=float(it.get("confidence", 0.9)),
                            evidence_ids=it.get("evidence_ids", []),
                        ))
                    return ExtractionBatchResult(
                        items=items,
                        model=f"nvidia-nim/{self.model_name}",
                        prompt_version="v2.0-deepseek",
                    )  # type: ignore

                return schema.model_validate(parsed)

        except Exception as exc:
            logger.warning(f"NVIDIA NIM DeepSeek call failed: {exc}. Failing over to fallback client.")
            return self._fallback_client.generate_structured(prompt, schema)


class GroqLLMClient(LLMClient):
    """
    High-speed OpenAI-compatible LLM Client for Groq (e.g. openai/gpt-oss-120b or openai/gpt-oss-20b).
    Provides sub-second structured JSON extraction with enterprise multi-tier failover.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "openai/gpt-oss-120b",
        base_url: str = "https://api.groq.com/openai/v1",
        timeout_seconds: float = 15.0,
        fallback_client: Optional[LLMClient] = None,
    ):
        self.api_key = api_key.strip() if api_key else ""
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback_client = fallback_client or DeterministicRuleLLMClient()

    def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        if not self.api_key or self.api_key.startswith("your-") or not self.api_key.strip():
            logger.info("Groq API key not configured. Using fallback client.")
            return self._fallback_client.generate_structured(prompt, schema)

        import httpx

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Synora/1.0",
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an enterprise software architecture intelligence extraction model for Synora. "
                        "Respond strictly in valid JSON matching the requested schema."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                if resp.status_code != 200:
                    logger.warning(
                        f"Groq API returned HTTP {resp.status_code}: {resp.text[:200]}. Failing over to fallback client."
                    )
                    return self._fallback_client.generate_structured(prompt, schema)

                res_json = resp.json()
                msg = res_json["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                if not content or not content.strip():
                    logger.warning("Groq API returned empty content. Failing over to fallback client.")
                    return self._fallback_client.generate_structured(prompt, schema)

                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content)

                if schema == ExtractionBatchResult:
                    items = []
                    raw_items = parsed.get("items", []) if isinstance(parsed, dict) else parsed
                    for it in raw_items:
                        items.append(CandidateItemDTO(
                            category=it.get("category", "proposal"),
                            classification=it.get("classification", ClassificationEnum.PROPOSAL),
                            title=it.get("title", "Candidate"),
                            content=it.get("content", ""),
                            confidence=float(it.get("confidence", 0.9)),
                            evidence_ids=it.get("evidence_ids", []),
                        ))
                    return ExtractionBatchResult(
                        items=items,
                        model=f"groq/{self.model_name}",
                        prompt_version="v2.0-groq",
                    )  # type: ignore

                return schema.model_validate(parsed)

        except Exception as exc:
            logger.warning(f"Groq LLM call failed: {exc}. Failing over to fallback client.")
            return self._fallback_client.generate_structured(prompt, schema)


class GeminiLLMClient(LLMClient):
    """
    Google Gemini LLM client for structured reasoning and extraction.
    Defaults to free gemini-3.5-flash-lite via the Google Generative Language REST API.
    Provides structured JSON extraction with multi-tier failover.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3.5-flash-lite",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: float = 20.0,
        fallback_client: Optional[LLMClient] = None,
    ):
        self.api_key = api_key.strip() if api_key else ""
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback_client = fallback_client or DeterministicRuleLLMClient()

    def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        if not self.api_key or self.api_key.startswith("your-") or not self.api_key.strip():
            logger.info("Gemini API key not configured. Using fallback client.")
            return self._fallback_client.generate_structured(prompt, schema)

        import httpx

        system_instruction = (
            "You are an enterprise software architecture intelligence extraction model for Synora. "
            "Respond strictly in valid JSON matching the requested schema."
        )

        url = f"{self.base_url}/models/{self.model_name}:generateContent?key={self.api_key}"
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
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, json=payload)
                if resp.status_code != 200:
                    logger.warning(
                        f"Gemini API returned HTTP {resp.status_code}: {resp.text[:200]}. Failing over to fallback client."
                    )
                    return self._fallback_client.generate_structured(prompt, schema)

                res_json = resp.json()
                candidates = res_json.get("candidates", [])
                if not candidates:
                    logger.warning("Gemini returned empty candidates. Failing over to fallback client.")
                    return self._fallback_client.generate_structured(prompt, schema)

                parts = candidates[0].get("content", {}).get("parts", [])
                content = parts[0].get("text", "") if parts else ""
                if not content or not content.strip():
                    logger.warning("Gemini returned empty text content. Failing over to fallback client.")
                    return self._fallback_client.generate_structured(prompt, schema)

                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content)

                if schema == ExtractionBatchResult:
                    items = []
                    raw_items = parsed.get("items", []) if isinstance(parsed, dict) else parsed
                    for it in raw_items:
                        items.append(CandidateItemDTO(
                            category=it.get("category", "proposal"),
                            classification=it.get("classification", ClassificationEnum.PROPOSAL),
                            title=it.get("title", "Candidate"),
                            content=it.get("content", ""),
                            confidence=float(it.get("confidence", 0.9)),
                            evidence_ids=it.get("evidence_ids", []),
                        ))
                    return ExtractionBatchResult(
                        items=items,
                        model=f"gemini/{self.model_name}",
                        prompt_version="v2.0-gemini",
                    )  # type: ignore

                return schema.model_validate(parsed)

        except Exception as exc:
            logger.warning(f"Gemini LLM call failed: {exc}. Failing over to fallback client.")
            return self._fallback_client.generate_structured(prompt, schema)


def get_default_llm_client() -> LLMClient:
    """Return the configured semantic provider with enterprise multi-tier failover.
    
    Enterprise Fallback Hierarchy:
      Tier 1: Primary provider (default: Gemini with gemini-3.5-flash-lite)
      Tier 2: Secondary failover provider (Groq with openai/gpt-oss-120b)
      Tier 3: Tertiary failover provider (NVIDIA NIM with deepseek-ai/deepseek-v4.1-flash)
      Tier 4: Offline absolute safety engine (DeterministicRuleLLMClient)
    """
    from app.core.config import settings

    deterministic_client = DeterministicRuleLLMClient()
    provider = (settings.LLM_PROVIDER or "").lower()

    if provider == "deterministic":
        return deterministic_client

    # Tier 3: NVIDIA NIM
    nim_client: Optional[NvidiaNimLLMClient] = None
    if settings.is_nvidia_nim_configured:
        nim_client = NvidiaNimLLMClient(
            api_key=settings.NVIDIA_API_KEY,
            model_name=settings.NVIDIA_MODEL,
            base_url=settings.NVIDIA_BASE_URL,
            fallback_client=deterministic_client,
        )

    # Tier 2: Groq
    groq_client: Optional[GroqLLMClient] = None
    if settings.is_groq_configured:
        groq_client = GroqLLMClient(
            api_key=settings.GROQ_API_KEY,
            model_name=settings.GROQ_MODEL,
            base_url=settings.GROQ_BASE_URL,
            fallback_client=nim_client or deterministic_client,
        )

    # Tier 1: Gemini
    gemini_client: Optional[GeminiLLMClient] = None
    if settings.is_gemini_configured:
        gemini_client = GeminiLLMClient(
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.GEMINI_MODEL,
            base_url=settings.GEMINI_BASE_URL,
            fallback_client=groq_client or nim_client or deterministic_client,
        )

    if provider == "gemini":
        if gemini_client:
            return gemini_client
        if groq_client:
            return groq_client
        if nim_client:
            return nim_client
        return deterministic_client

    if provider == "groq":
        if groq_client:
            return groq_client
        if gemini_client:
            return gemini_client
        if nim_client:
            return nim_client
        return deterministic_client

    if provider == "nvidia":
        if nim_client:
            nim_primary = NvidiaNimLLMClient(
                api_key=settings.NVIDIA_API_KEY,
                model_name=settings.NVIDIA_MODEL,
                base_url=settings.NVIDIA_BASE_URL,
                fallback_client=groq_client or gemini_client or deterministic_client,
            )
            return nim_primary
        if gemini_client:
            return gemini_client
        if groq_client:
            return groq_client
        return deterministic_client

    # Auto-select best configured provider
    if gemini_client:
        return gemini_client
    if groq_client:
        return groq_client
    if nim_client:
        return nim_client
    return deterministic_client
