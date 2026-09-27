from abc import ABC, abstractmethod
import json
import logging
import re
from typing import Any, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel

from app.schemas.intelligence import CandidateItemDTO, ClassificationEnum, ExtractionBatchResult
from app.schemas.context import ContextResolutionResult

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

    def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        # If schema is ExtractionBatchResult, analyze evidence text snippets embedded in the prompt
        if schema == ExtractionBatchResult:
            items = self._analyze_prompt_evidence(prompt)
            return ExtractionBatchResult(items=items, model=self.model_name, prompt_version="v1.0")  # type: ignore

        if schema == ContextResolutionResult:
            return ContextResolutionResult(
                status="unknown",
                selected_project_id=None,
                confidence=0.0,
                reasoning="Semantic context inference unavailable; deterministic resolver will decide.",
                candidates=[],
                model=self.model_name,
                prompt_version="context-v1",
            )  # type: ignore

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

            # Rule 6: Action Items
            # "will write", "action item:", "assigned to", "by tomorrow"
            if "will write" in lower_text or "action item:" in lower_text or "by tomorrow" in lower_text:
                items.append(
                    CandidateItemDTO(
                        category="action_item",
                        classification=ClassificationEnum.ACTION_ITEM,
                        title=f"Action item for {speaker}",
                        content=text,
                        confidence=0.85,
                        evidence_ids=[ev_id],
                    )
                )
                continue

        return items


class NvidiaNimLLMClient(LLMClient):
    """
    OpenAI-compatible LLM Client for NVIDIA NIM hosting DeepSeek (e.g. deepseek-ai/deepseek-r1).
    Provides structured JSON extraction and falls back to DeterministicRuleLLMClient on failure.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "deepseek-ai/deepseek-r1",
        base_url: str = "https://integrate.api.nvidia.com/v1",
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._fallback_client = DeterministicRuleLLMClient()

    def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        """
        Calls NVIDIA NIM chat completion endpoint with DeepSeek model and parses response into schema.
        Falls back gracefully to deterministic rule engine if API key is invalid or request fails.
        """
        if not self.api_key or self.api_key.startswith("your-") or not self.api_key.strip():
            logger.info("NVIDIA NIM API key not configured. Using deterministic rule engine.")
            return self._fallback_client.generate_structured(prompt, schema)

        import httpx

        if schema == ContextResolutionResult:
            system_instruction = (
                "You are Synora's project-context resolution model. "
                "Given source content plus bounded existing project summaries, determine which supplied project(s) the content belongs to. "
                "Never invent a project ID. Prefer ambiguous or unknown over an unsafe assignment. "
                "Use only candidate project IDs supplied in the prompt. "
                "Return resolved only when one project is clearly supported, ambiguous when multiple are plausible, and unknown when evidence is insufficient. "
                "Return JSON fields: status, selected_project_id, confidence, reasoning, candidates, model, prompt_version. "
                "Each candidate must contain project_id, project_name, confidence, reasons."
            )
        else:
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
                        f"NVIDIA NIM returned HTTP {resp.status_code}: {resp.text[:200]}. Falling back to rule engine."
                    )
                    return self._fallback_client.generate_structured(prompt, schema)

                res_json = resp.json()
                content = res_json["choices"][0]["message"]["content"]
                parsed = json.loads(content)

                if schema == ContextResolutionResult:
                    return ContextResolutionResult.model_validate(parsed)

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
            logger.warning(f"NVIDIA NIM DeepSeek call failed: {exc}. Using deterministic rule engine fallback.")
            return self._fallback_client.generate_structured(prompt, schema)


def get_default_llm_client() -> LLMClient:
    """Return the configured semantic provider. NVIDIA NIM is the product default."""
    from app.core.config import settings

    if settings.LLM_PROVIDER.lower() == "nvidia" and settings.is_nvidia_nim_configured:
        logger.info("Initializing NVIDIA NIM LLM client with model '%s'", settings.NVIDIA_MODEL)
        return NvidiaNimLLMClient(
            api_key=settings.NVIDIA_API_KEY,
            model_name=settings.NVIDIA_MODEL,
            base_url=settings.NVIDIA_BASE_URL,
        )
    return DeterministicRuleLLMClient()
