"""Phase 0 (plan.md): labeled context-routing evaluation corpus.

The corpus is synthetic and privacy-safe (fixtures/eval/context_eval_v1.json).
The semantic provider is stubbed per case, so this fast suite measures the
routing policy — deterministic signals, confidence/margin thresholds, and
safe abstention — offline and reproducibly. It must never be made green by
auto-routing more: wrong_route_rate is the hard gate.
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.services.context_eval import compute_routing_metrics, run_eval_corpus

CORPUS_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "eval" / "context_eval_v1.json"


def _corpus():
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def test_corpus_is_versioned_and_well_formed():
    corpus = _corpus()
    assert corpus["dataset_version"] == "context_eval_v1"
    project_ids = {p["id"] for p in corpus["projects"]}
    assert len(project_ids) == len(corpus["projects"])
    case_ids = [c["id"] for c in corpus["cases"]]
    assert len(case_ids) == len(set(case_ids)) >= 15
    for case in corpus["cases"]:
        assert case["expected_decision"] in ("resolved", "unknown")
        if case["expected_decision"] == "resolved":
            assert case["expected_project"] in project_ids
        for item in case.get("semantic", []):
            assert item["project_id"] in project_ids
            assert 0.0 <= item["confidence"] <= 1.0


def test_eval_metrics_are_safe_abstention_first(db_session: Session):
    rows = run_eval_corpus(db_session, _corpus())
    metrics = compute_routing_metrics(rows)

    # The contamination gate: nothing may be routed to a wrong project.
    assert metrics["wrong_route_rate"] == 0.0, metrics["failures"]
    assert metrics["auto_route_precision"] == 1.0, metrics["failures"]
    # Every labeled-unknown case must abstain safely (unknown/ambiguous/casual).
    assert metrics["abstention_accuracy"] == 1.0, metrics["failures"]
    # Deterministic + strong-semantic routable cases should actually route.
    assert metrics["routable_recall"] >= 0.8, metrics["failures"]


def test_eval_metrics_math():
    rows = [
        {"case_id": "a", "expected_decision": "resolved", "expected_project": "p1",
         "actual_decision": "resolved", "actual_project": "p1", "confidence": 0.95, "scenario": ["x"]},
        {"case_id": "b", "expected_decision": "resolved", "expected_project": "p1",
         "actual_decision": "unknown", "actual_project": None, "confidence": 0.4, "scenario": ["x"]},
        {"case_id": "c", "expected_decision": "unknown", "expected_project": None,
         "actual_decision": "unknown", "actual_project": None, "confidence": 0.3, "scenario": ["y"]},
        {"case_id": "d", "expected_decision": "unknown", "expected_project": None,
         "actual_decision": "resolved", "actual_project": "p2", "confidence": 0.9, "scenario": ["y"]},
    ]
    metrics = compute_routing_metrics(rows)
    assert metrics["cases"] == 4
    assert metrics["auto_route_precision"] == 0.5
    assert metrics["routable_recall"] == 0.5
    assert metrics["abstention_accuracy"] == 0.5
    assert metrics["wrong_route_rate"] == 0.25
    assert metrics["expected_calibration_error"] > 0
    assert {f["case_id"] for f in metrics["failures"]} == {"b", "d"}
