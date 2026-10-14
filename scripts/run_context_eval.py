#!/usr/bin/env python3
"""Phase 0 baseline: run the labeled context-routing corpus (plan.md).

Offline and reproducible: the semantic provider is stubbed per case, so this
measures routing policy (deterministic signals, thresholds, margins, safe
abstention), not a live LLM. Writes fixtures/eval/baseline_report_v1.json.

Usage (repo root):  python scripts/run_context_eval.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("SECRET_KEY", "eval-secret")
os.environ.setdefault("ENCRYPTION_KEY", "eval-encryption")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LLM_PROVIDER", "deterministic")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.services.context_eval import compute_routing_metrics, run_eval_corpus  # noqa: E402


def main() -> int:
    corpus = json.loads((ROOT / "fixtures" / "eval" / "context_eval_v1.json").read_text(encoding="utf-8"))
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        rows = run_eval_corpus(session, corpus)
    finally:
        session.close()

    metrics = compute_routing_metrics(rows)
    report = {
        "dataset_version": corpus["dataset_version"],
        "semantic_provider": "stubbed_per_case (routing policy only, not a live LLM)",
        "metrics": metrics,
        "rows": rows,
    }
    out = ROOT / "fixtures" / "eval" / "baseline_report_v1.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("dataset:", corpus["dataset_version"], "cases:", metrics["cases"])
    print("auto_route_precision:", metrics["auto_route_precision"])
    print("routable_recall:", metrics["routable_recall"])
    print("abstention_accuracy:", metrics["abstention_accuracy"])
    print("wrong_route_rate:", metrics["wrong_route_rate"])
    print("expected_calibration_error:", metrics["expected_calibration_error"])
    for failure in metrics["failures"]:
        print("FAIL", failure["case_id"], "expected", failure["expected"], "actual", failure["actual"])
    print("report:", out)
    return 0 if metrics["wrong_route_rate"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
