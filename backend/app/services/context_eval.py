"""Routing evaluation metrics (plan.md Phase 0).

Pure functions over labeled prediction rows so the same metrics power the
fast pytest regression suite and the standalone baseline report. A row is:
{case_id, expected_decision: "resolved"|"unknown", expected_project,
 actual_decision, actual_project, confidence, scenario: [tags]}.

Definitions (safe-abstention first; never optimise by auto-routing more):
- auto_route_precision: of cases the system resolved, fraction resolved to
  the labeled project.
- routable_recall: of cases labeled resolved, fraction resolved correctly.
- abstention_accuracy: of cases labeled unknown, fraction not resolved to
  any project (unknown/ambiguous/casual all count as safe abstention).
- wrong_route_rate: of all cases, fraction resolved to a project other
  than the label (the contamination metric that must stay at zero).
- expected_calibration_error: binned |confidence - accuracy| over every
  prediction, accuracy = resolved to the labeled project.
"""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

RESOLVED = "resolved"
_ECE_BINS = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


class _StubSemanticClient:
    """Deterministic semantic-provider stub: returns the case's labeled
    candidate slate so the eval measures routing policy offline."""

    def __init__(self, items: List[Dict[str, Any]]):
        self._items = items

    def generate_structured(self, prompt, schema):
        from app.schemas.context import ContextCandidateBatch, ContextCandidateItem

        if schema is ContextCandidateBatch:
            return ContextCandidateBatch(
                items=[
                    ContextCandidateItem(
                        project_id=item["project_id"],
                        confidence=float(item["confidence"]),
                        reasons=["eval_stub"],
                    )
                    for item in self._items
                ],
                is_casual=False,
                model="eval-stub",
                prompt_version="context_eval_v1",
            )
        raise NotImplementedError


def run_eval_corpus(db: Session, corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run every labeled case through the real resolver (stubbed semantic
    layer) and return prediction rows for compute_routing_metrics."""
    from app.models.project import Project
    from app.services.context_intelligence import ContextIntelligenceService

    for spec in corpus.get("projects", []):
        if not db.query(Project).filter(Project.id == spec["id"]).first():
            db.add(Project(
                id=spec["id"], workspace_id="ws_default",
                name=spec["name"], description=spec.get("description", ""),
            ))
    db.commit()

    rows: List[Dict[str, Any]] = []
    for case in corpus.get("cases", []):
        service = ContextIntelligenceService(
            llm_client=_StubSemanticClient(case.get("semantic") or [])
        )
        result = service.resolve(
            source=case.get("source", "whatsapp"),
            payload={"text": case["text"]},
            db=db,
            continuity_context=case.get("continuity"),
            record=False,
        )
        rows.append({
            "case_id": case["id"],
            "scenario": case.get("scenario", []),
            "expected_decision": case["expected_decision"],
            "expected_project": case.get("expected_project"),
            "actual_decision": result.decision,
            "actual_project": result.project_id,
            "confidence": float(result.confidence or 0.0),
            "margin": float(result.margin or 0.0),
        })
    return rows


def compute_routing_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    resolved_rows = [r for r in rows if r.get("actual_decision") == RESOLVED]
    routable = [r for r in rows if r.get("expected_decision") == RESOLVED]
    abstain_labeled = [r for r in rows if r.get("expected_decision") != RESOLVED]

    def _correct(row: Dict[str, Any]) -> bool:
        return (
            row.get("actual_decision") == RESOLVED
            and row.get("actual_project") is not None
            and row.get("actual_project") == row.get("expected_project")
        )

    correct_routes = sum(1 for r in resolved_rows if _correct(r))
    wrong_routes = sum(
        1
        for r in rows
        if r.get("actual_decision") == RESOLVED and not _correct(r)
    )
    safely_abstained = sum(
        1 for r in abstain_labeled if r.get("actual_decision") != RESOLVED
    )

    ece = 0.0
    if total:
        for low, high in _ECE_BINS:
            bucket = [
                r for r in rows if low <= float(r.get("confidence") or 0.0) < high
            ]
            if not bucket:
                continue
            accuracy = sum(1 for r in bucket if _correct(r)) / len(bucket)
            mean_confidence = sum(float(r.get("confidence") or 0.0) for r in bucket) / len(bucket)
            ece += (len(bucket) / total) * abs(mean_confidence - accuracy)

    by_scenario: Dict[str, Dict[str, int]] = {}
    for row in rows:
        for tag in row.get("scenario") or []:
            bucket = by_scenario.setdefault(tag, {"total": 0, "correct_or_safe": 0})
            bucket["total"] += 1
            if row.get("expected_decision") == RESOLVED:
                bucket["correct_or_safe"] += 1 if _correct(row) else 0
            else:
                bucket["correct_or_safe"] += 1 if row.get("actual_decision") != RESOLVED else 0

    return {
        "cases": total,
        "auto_route_precision": (correct_routes / len(resolved_rows)) if resolved_rows else 1.0,
        "routable_recall": (sum(1 for r in routable if _correct(r)) / len(routable)) if routable else 1.0,
        "abstention_accuracy": (safely_abstained / len(abstain_labeled)) if abstain_labeled else 1.0,
        "wrong_route_rate": (wrong_routes / total) if total else 0.0,
        "expected_calibration_error": round(ece, 4),
        "by_scenario": by_scenario,
        "failures": [
            {
                "case_id": r.get("case_id"),
                "expected": [r.get("expected_decision"), r.get("expected_project")],
                "actual": [r.get("actual_decision"), r.get("actual_project")],
                "confidence": r.get("confidence"),
            }
            for r in rows
            if not (
                _correct(r)
                if r.get("expected_decision") == RESOLVED
                else r.get("actual_decision") != RESOLVED
            )
        ],
    }
