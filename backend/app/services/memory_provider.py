"""Memory retrieval provider interface (plan.md Mem0 decision).

Canonical evidence, claims, and project state stay in Synora's DB. The
native provider serves production reads. Mem0 is an optional experiment
adapter: it only mirrors authorized, provenance-linked claims (Synora
claim/evidence IDs stay canonical, deletion/correction propagated), is
never an authoritative write path, and the read path falls back to the
native provider when the adapter is unavailable (no key/SDK/API error).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Protocol

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.services.memory_retrieval import INACTIVE_STATUSES, query_groups, relevance

logger = logging.getLogger(__name__)


class MemoryProviderUnavailable(Exception):
    """Raised by an adapter that cannot serve reads/writes right now."""


class MemoryRetrievalProvider(Protocol):
    name: str

    def health(self) -> Dict[str, Any]:
        ...

    def search(self, db: Session, project_id: str, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        ...


def _claim_text(claim: CandidateKnowledge) -> str:
    return f"{claim.title or ''} {claim.content or ''}".strip()


def _evidence_ids(claim: CandidateKnowledge) -> List[str]:
    try:
        return [str(v) for v in json.loads(claim.evidence_ids_json or "[]") if v]
    except (TypeError, ValueError):
        return []


class SynoraNativeProvider:
    """Production provider: project-scoped claims + evidence in Synora's DB.

    Uses the offline lexical-expansion retrieval (query term families, e.g.
    "swap" matching "exchange") with approved status outranking recency.
    Callers must verify workspace/project access before calling.
    """

    name = "synora"

    def health(self) -> Dict[str, Any]:
        return {"provider": self.name, "available": True, "reason": "canonical Synora DB retrieval"}

    def search(self, db: Session, project_id: str, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        groups = query_groups(query)
        hits: List[Dict[str, Any]] = []
        claims = (
            db.query(CandidateKnowledge)
            .filter(CandidateKnowledge.project_id == project_id)
            .order_by(CandidateKnowledge.created_at.desc())
            .limit(200)
            .all()
        )
        for claim in claims:
            if (claim.status or "").lower() in INACTIVE_STATUSES:
                continue
            score = relevance(_claim_text(claim), groups) if groups else 0.1
            if groups and score <= 0:
                continue
            hits.append({
                "provider": self.name,
                "kind": "claim",
                "claim_id": claim.id,
                "evidence_ids": _evidence_ids(claim),
                "project_id": project_id,
                "status": claim.status,
                "title": claim.title,
                "text": claim.content or claim.title or "",
                "score": round(score + (0.05 if (claim.status or "").lower() == "approved" else 0.0), 4),
            })
        evidence_rows = (
            db.query(Evidence)
            .filter(Evidence.project_id == project_id)
            .order_by(Evidence.occurred_at.desc())
            .limit(200)
            .all()
        )
        for row in evidence_rows:
            score = relevance(row.content or "", groups) if groups else 0.0
            if groups and score <= 0:
                continue
            hits.append({
                "provider": self.name,
                "kind": "evidence",
                "claim_id": None,
                "evidence_ids": [row.id],
                "project_id": project_id,
                "status": "evidence",
                "title": None,
                "text": row.content or "",
                "score": round(score * 0.9, 4),
            })
        hits.sort(key=lambda hit: hit["score"], reverse=True)
        return hits[:limit]


class Mem0AdapterProvider:
    """Optional Mem0 experiment adapter (never authoritative).

    Mirrors only provenance-linked, non-inactive claims. Mem0 ids are
    disposable; Synora claim/evidence IDs in metadata stay canonical.
    Every failure degrades to unavailable — it never fabricates results.
    Scope isolation is by construction: the Mem0 user id is the project.
    """

    name = "mem0"

    def __init__(self, client: Optional[Any] = None):
        self._client = client
        self._availability: Optional[Dict[str, Any]] = None

    @staticmethod
    def _scope(project_id: str) -> str:
        return f"project:{project_id}"

    def _connect(self) -> Any:
        if self._client is not None:
            return self._client
        if not (settings.MEM0_API_KEY or "").strip():
            raise MemoryProviderUnavailable("MEM0_API_KEY is not configured")
        try:
            from mem0 import MemoryClient
        except ImportError as exc:
            raise MemoryProviderUnavailable(f"mem0ai SDK is not installed: {exc}") from exc
        kwargs: Dict[str, Any] = {"api_key": settings.MEM0_API_KEY}
        if (settings.MEM0_BASE_URL or "").strip():
            kwargs["host"] = settings.MEM0_BASE_URL
        self._client = MemoryClient(**kwargs)
        return self._client

    def health(self) -> Dict[str, Any]:
        if self._availability is not None:
            return self._availability
        try:
            self._connect()
            self._availability = {"provider": self.name, "available": True, "reason": "Mem0 adapter configured (experiment)"}
        except MemoryProviderUnavailable as exc:
            self._availability = {"provider": self.name, "available": False, "reason": str(exc)}
        return self._availability

    def _require(self) -> Any:
        if not self.health()["available"]:
            raise MemoryProviderUnavailable(self.health()["reason"])
        return self._connect()

    def mirror_claim(self, claim: CandidateKnowledge) -> Dict[str, Any]:
        """Mirror one provenance-linked claim. Refuses anything else."""
        evidence_ids = _evidence_ids(claim)
        if not evidence_ids:
            raise MemoryProviderUnavailable("refusing to mirror a claim with no evidence links")
        if (claim.status or "").lower() in INACTIVE_STATUSES:
            raise MemoryProviderUnavailable("refusing to mirror an inactive claim")
        client = self._require()
        messages = [{"role": "system", "content": f"[CLAIM {claim.id}] {_claim_text(claim)}"}]
        metadata = {
            "synora_claim_id": claim.id,
            "synora_project_id": claim.project_id,
            "evidence_ids": ",".join(evidence_ids),
            "status": claim.status or "",
            "type": "synora_claim_mirror",
        }
        result = client.add(messages, user_id=self._scope(claim.project_id), metadata=metadata)
        return {"mirrored": True, "claim_id": claim.id, "mem0_result": str(result)[:200]}

    def delete_claim(self, db_project_id: str, claim_id: str) -> Dict[str, Any]:
        """Propagate a deletion/correction: drop the mirror for this claim."""
        client = self._require()
        envelope = client.get_all(filters={"user_id": self._scope(db_project_id)}) or {}
        deleted = 0
        for item in envelope.get("results", []):
            metadata = item.get("metadata") or {}
            if metadata.get("synora_claim_id") == claim_id and item.get("id"):
                client.delete(item["id"])
                deleted += 1
        return {"deleted": deleted, "claim_id": claim_id}

    def search(self, db: Session, project_id: str, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        client = self._require()
        results = client.search(query, filters={"user_id": self._scope(project_id)}, top_k=limit) or []
        hits = []
        for item in results:
            metadata = item.get("metadata") or {}
            hits.append({
                "provider": self.name,
                "kind": "claim",
                "claim_id": metadata.get("synora_claim_id"),
                "evidence_ids": [v for v in str(metadata.get("evidence_ids") or "").split(",") if v],
                "project_id": project_id,
                "status": metadata.get("status"),
                "title": None,
                "text": item.get("memory", ""),
                "score": float(item.get("score") or 0.0),
            })
        return hits


def get_retrieval_provider(db: Optional[Session] = None) -> MemoryRetrievalProvider:
    """Factory honoring MEMORY_PROVIDER with safe fallback to native."""
    requested = str(settings.MEMORY_PROVIDER or "synora").strip().lower()
    if requested == "mem0":
        adapter = Mem0AdapterProvider()
        health = adapter.health()
        if health["available"]:
            return adapter
        logger.warning("mem0_adapter_unavailable_falling_back_to_native: %s", health["reason"])
    return SynoraNativeProvider()


def provider_health() -> Dict[str, Any]:
    native = SynoraNativeProvider().health()
    mem0 = Mem0AdapterProvider().health()
    active = "mem0" if str(settings.MEMORY_PROVIDER or "").lower() == "mem0" and mem0["available"] else "synora"
    return {"active": active, "requested": str(settings.MEMORY_PROVIDER or "synora"), "synora": native, "mem0": mem0}
