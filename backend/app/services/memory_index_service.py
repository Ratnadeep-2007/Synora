"""Persisted keyword and vector indexes; source rows remain authoritative."""

import json
import math
from collections import Counter
from typing import Protocol
from sqlalchemy import func
from app.models.memory_engine import MemoryIndex, MemoryTerm
from app.models.evidence import Evidence
from app.models.intelligence import CandidateKnowledge
from app.models.source_event import SourceEvent
from app.services.embedding_service import GeminiEmbeddingService
from app.services.memory_events import fingerprint
from app.services.memory_retrieval import query_groups, words


class MemorySearchProvider(Protocol):
    def search(self, query, project_id, tenant_id, db, kind="claim", limit=40): ...


_embedding_client = None


def embedding_client():
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = GeminiEmbeddingService()
    return _embedding_client


def cosine(left, right):
    if len(left) != len(right) or not left:
        return 0.0
    denominator = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    return sum(x*y for x, y in zip(left, right)) / denominator if denominator else 0.0


class MemoryIndexService:
    def __init__(self, embeddings=None):
        self.embeddings = embeddings

    def remove(self, kind, entity_id, db):
        ids = [row[0] for row in db.query(MemoryIndex.id).filter_by(kind=kind, entity_id=entity_id).all()]
        if ids:
            db.query(MemoryTerm).filter(MemoryTerm.record_id.in_(ids)).delete(synchronize_session=False)
            db.query(MemoryIndex).filter(MemoryIndex.id.in_(ids)).delete(synchronize_session=False)

    def index(self, kind, entity_id, db):
        entity = db.get(CandidateKnowledge if kind == "claim" else Evidence, entity_id)
        if entity and (kind == "evidence" or entity.status == "approved"):
            existing = db.query(MemoryIndex).filter_by(kind=kind, entity_id=entity_id).all()
            embeddings = self.embeddings or embedding_client()
            api_key = getattr(embeddings, "api_key", "")
            expected_provider = None if api_key and not api_key.startswith("your-") else "lexical_hash"
            if existing and all(
                record.content_hash == fingerprint(entity)
                and record.model == embeddings.model_name
                and (expected_provider is None or record.provider == expected_provider)
                for record in existing
            ):
                return {"indexed": len(existing), "unchanged": True}
        self.remove(kind, entity_id, db)
        if not entity or (kind == "claim" and (entity.status != "approved" or entity.classification in {"Rejected", "Superseded"})):
            return {"indexed": 0, "entity_id": entity_id}
        source_ids = json.loads(entity.evidence_ids_json or "[]") if kind == "claim" else [entity.id]
        sources = db.query(SourceEvent.tenant_id).join(Evidence, Evidence.source_event_id == SourceEvent.event_id).filter(
            Evidence.id.in_(source_ids), Evidence.project_id == entity.project_id,
        ).all()
        tenants = {row[0] for row in sources}
        if not tenants:
            return {"indexed": 0, "entity_id": entity_id, "reason": "missing_provenance"}
        if tenants <= {"tenant_default", "default_tenant"}:
            tenants = {"default_tenant"}
        if len(tenants) != 1:
            return {"indexed": 0, "entity_id": entity_id, "reason": "mixed_tenants"}
        tenant_id = next(iter(tenants))
        text = entity.content or ""
        title = getattr(entity, "title", "") or ""
        embeddings = self.embeddings or embedding_client()
        chunk_count = 0
        # Each chunk is a separate durable job. An entity job writes terms and
        # enqueues vector work, so a long document never makes a burst of calls.
        from app.services.memory_jobs import enqueue_job
        for start in range(0, len(text), 2400):
            content = text[start:start + 2800]
            record = MemoryIndex(
                id=f"{kind}:{entity.id}:{start}", entity_id=entity.id, kind=kind,
                tenant_id=tenant_id, project_id=entity.project_id, content_hash=fingerprint(entity),
                content=content, offset_start=start, offset_end=start + len(content),
                provider="pending", model=embeddings.model_name, vector_json="[]",
            )
            db.add(record)
            db.flush()
            counts = Counter(words(title + " " + content))
            for term, count in counts.items():
                db.add(MemoryTerm(record_id=record.id, term=term[:128], weight=min(8, count)))
            enqueue_job(db, "memory_vector", {"record_id": record.id, "hash": record.content_hash},
                        entity.project_id, tenant_id, key=record.id + ":" + record.content_hash, requeue=True)
            chunk_count += 1
        return {"indexed": chunk_count, "entity_id": entity_id}

    def embed_record(self, payload, db):
        record = db.get(MemoryIndex, payload["record_id"])
        if not record or record.content_hash != payload["hash"]:
            return {"skipped": "stale_index"}
        client = self.embeddings or embedding_client()
        record.vector_json = json.dumps(client.embed_text(record.content))
        record.provider = getattr(client, "last_provider", "gemini")
        record.model = client.model_name
        return {"record_id": record.id, "provider": record.provider}

    def search(self, query, project_id, tenant_id, db, kind="claim", limit=40):
        if not query or not query.strip():
            return []
        tenants = ["default_tenant", "tenant_default"] if tenant_id in {"default_tenant", "tenant_default"} else [tenant_id]
        scope = db.query(MemoryIndex).filter(MemoryIndex.project_id == project_id,
            MemoryIndex.tenant_id.in_(tenants), MemoryIndex.kind == kind)
        terms = {term for group in query_groups(query) for term in group}
        ranked = {}
        if terms:
            keyword = scope.join(MemoryTerm, MemoryTerm.record_id == MemoryIndex.id).filter(
                MemoryTerm.term.in_(terms)
            ).with_entities(MemoryIndex.id, func.sum(MemoryTerm.weight)).group_by(MemoryIndex.id).order_by(
                func.sum(MemoryTerm.weight).desc()
            ).limit(limit * 2).all()
            for position, (record_id, _) in enumerate(keyword):
                ranked[record_id] = 1 / (30 + position)
        # A hash-vector fallback is useful lexical data, but is never reported
        # as semantic retrieval. Compare only real, matching embedding models.
        client = self.embeddings or embedding_client()
        semantic_rows = scope.filter(MemoryIndex.provider == "gemini", MemoryIndex.model == client.model_name).limit(2500).all()
        if semantic_rows:
            vector = client.embed_text(query)
            if getattr(client, "last_provider", "gemini") == "gemini":
                scores = sorted(((cosine(vector, json.loads(row.vector_json)), row.id) for row in semantic_rows), reverse=True)
                for position, (similarity, record_id) in enumerate(scores[:limit * 2]):
                    if similarity >= 0.55:
                        ranked[record_id] = ranked.get(record_id, 0) + 1 / (30 + position)
        rows = {row.id: row for row in scope.filter(MemoryIndex.id.in_(ranked)).all()} if ranked else {}
        hits = []
        seen = set()
        for record_id in sorted(ranked, key=ranked.get, reverse=True):
            row = rows.get(record_id)
            if not row or row.entity_id in seen:
                continue
            entity = db.get(CandidateKnowledge if kind == "claim" else Evidence, row.entity_id)
            if not entity or entity.project_id != project_id or fingerprint(entity) != row.content_hash:
                continue
            if kind == "claim" and entity.status != "approved":
                continue
            hits.append({"id": row.entity_id, "rank": ranked[record_id], "start": row.offset_start,
                         "end": row.offset_end, "provider": row.provider, "model": row.model})
            seen.add(row.entity_id)
            if len(hits) >= limit:
                break
        return hits


class Mem0SearchAdapter:
    """Optional experiment adapter. Synora still validates every returned ID."""
    def __init__(self, client):
        self.client = client

    def search(self, query, project_id, tenant_id, db, kind="claim", limit=40):
        result = self.client.search(query, filters={"AND": [
            {"user_id": f"{tenant_id}:{project_id}"}, {"metadata": {"kind": kind}}
        ]}, top_k=limit)
        rows = result.get("results", []) if isinstance(result, dict) else result
        hits = []
        for row in rows:
            metadata = row.get("metadata") or {}
            entity_id = metadata.get("entity_id")
            entity = db.get(CandidateKnowledge if kind == "claim" else Evidence, entity_id) if entity_id else None
            if entity and entity.project_id == project_id and metadata.get("content_hash") == fingerprint(entity):
                hits.append({"id": entity.id, "rank": float(row.get("score", 0)), "provider": "mem0"})
        return hits[:limit]
