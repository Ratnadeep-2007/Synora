#!/usr/bin/env python3
"""Mem0 adoption-gate experiment (plan.md): native Synora retrieval vs the
optional Mem0 adapter on the same labeled claims/tasks.

Mem0 is chosen only if it demonstrates an advantage with lifecycle
guarantees. When the adapter is unavailable (no MEM0_API_KEY / SDK), that
is recorded honestly and only native results are reported. Canonical
memory stays in Synora's DB either way.

Usage (repo root):  python scripts/run_memory_experiment.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("SECRET_KEY", "eval-secret")
os.environ.setdefault("ENCRYPTION_KEY", "eval-encryption")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_PROVIDER", "deterministic")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.models.evidence import Evidence  # noqa: E402
from app.models.intelligence import CandidateKnowledge  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.services.memory_provider import Mem0AdapterProvider, SynoraNativeProvider  # noqa: E402


def main() -> int:
    data = json.loads((ROOT / "fixtures" / "eval" / "memory_retrieval_v1.json").read_text(encoding="utf-8"))
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        for spec in data["projects"]:
            db.add(Project(id=spec["id"], workspace_id="ws_default", name=spec["name"], description=spec["description"]))
        for spec in data["claims"]:
            db.add(CandidateKnowledge(
                id=spec["id"], project_id=spec["project_id"], title=spec["title"],
                content=spec["content"], category="knowledge", classification="Requirement",
                status=spec["status"], evidence_ids_json=json.dumps(spec["evidence_ids"]),
            ))
        for spec in data["evidence"]:
            db.add(Evidence(id=spec["id"], project_id=spec["project_id"], source="eval", source_event_id=f"sev_{spec['id']}", content=spec["content"]))
        db.commit()

        def evaluate(provider, mirror=None):
            if mirror:
                claims = db.query(CandidateKnowledge).all()
                mirrored = 0
                for claim in claims:
                    try:
                        mirror(claim)
                        mirrored += 1
                    except Exception:
                        pass
            else:
                mirrored = None
            rows, latencies, traceable, total_hits = [], [], 0, 0
            for task in data["tasks"]:
                started = time.perf_counter()
                hits = provider.search(db, task["project_id"], task["query"], limit=5)
                latencies.append((time.perf_counter() - started) * 1000)
                got = {hit.get("claim_id") for hit in hits if hit.get("claim_id")}
                for hit in hits:
                    total_hits += 1
                    traceable += 1 if hit.get("evidence_ids") else 0
                expected = set(task["expected_claim_ids"])
                rows.append({
                    "task_id": task["id"], "scenario": task["scenario"],
                    "expected_claim_ids": sorted(expected),
                    "got_claim_ids": sorted(c for c in got if c),
                    "recall_hit": bool(expected & got) if expected else not got,
                    "scope_violation": bool(got - expected) if not expected else False,
                })
            positive = [r for r in rows if r["expected_claim_ids"]]
            return {
                "tasks": len(rows),
                "recall_at_k": sum(1 for r in positive if r["recall_hit"]) / len(positive) if positive else 1.0,
                "negative_tasks_clean": sum(1 for r in rows if not r["expected_claim_ids"] and r["recall_hit"]) / max(1, sum(1 for r in rows if not r["expected_claim_ids"])),
                "scope_violations": sum(1 for r in rows if r["scope_violation"]),
                "traceability": (traceable / total_hits) if total_hits else 1.0,
                "mean_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
                "mirrored_claims": mirrored,
                "rows": rows,
            }

        native = SynoraNativeProvider()
        results = {"synora": evaluate(native)}

        adapter = Mem0AdapterProvider()
        health = adapter.health()
        results["mem0"] = {"health": health}
        if health["available"]:
            results["mem0"].update(evaluate(adapter, mirror=adapter.mirror_claim))
        else:
            results["mem0"]["status"] = "unavailable_not_evaluated"

        report = {
            "dataset_version": data["dataset_version"],
            "gate": "Adopt Mem0 only if it beats native recall/traceability with zero scope violations and lifecycle propagation; otherwise stay native.",
            "results": results,
        }
        out = ROOT / "fixtures" / "eval" / "memory_experiment_report_v1.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in results.items()}, indent=2))
        print("report:", out)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
