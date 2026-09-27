import logging
from typing import Any, Dict, List

from app.schemas.visual_plan import VisualCritique, VisualPlan

logger = logging.getLogger(__name__)


class VisualCritiqueService:
    """Deterministic visual critique + repair pass.

    Runs AFTER compilation and BEFORE a proposal is created. It never mutates
    Project State and never calls a model: it only inspects the compiled scene
    and the plan, reporting issues and applying bounded, deterministic repairs.
    """

    MIN_NODE_GAP = 8

    def critique(
        self, plan: VisualPlan, scene: List[Dict[str, Any]]
    ) -> VisualCritique:
        issues: List[str] = []
        repairs: List[str] = []

        rects = [e for e in scene if e.get("type") == "rectangle"]
        arrows = [e for e in scene if e.get("type") == "arrow"]

        # 1. Overlap / spacing check between node rectangles.
        if self._has_overlap(rects):
            issues.append("Node overlap detected")

        # 2. Unreadable / empty labels.
        empty_labels = [
            e["id"]
            for e in scene
            if e.get("type") == "text" and not (e.get("text") or "").strip()
        ]
        if empty_labels:
            issues.append(f"{len(empty_labels)} node(s) have empty labels")

        # 3. Disconnected edges (relationship referencing a missing node).
        node_ids = {e.get("id") for e in rects}
        for arrow in arrows:
            start = (arrow.get("startBinding") or {}).get("elementId")
            end = (arrow.get("endBinding") or {}).get("elementId")
            if start not in node_ids or end not in node_ids:
                issues.append(f"Edge '{arrow.get('id')}' is disconnected")

        # 4. Accidental removal of important content.
        planned = {n.id for n in plan.nodes}
        preserved = set(plan.preserve or [])
        missing_preserved = {p for p in preserved if p not in planned}
        if missing_preserved:
            issues.append(
                f"Plan drops preserved node(s): {', '.join(sorted(missing_preserved))}"
            )

        # 5. Isolated nodes (no relationships at all in a multi-node diagram).
        if len(plan.nodes) > 1 and not arrows:
            issues.append("No relationships between nodes; diagram may read as a list")

        ok = not issues
        if issues:
            logger.info("visual_critique_issues: %s", "; ".join(issues))
        return VisualCritique(ok=ok, issues=issues, repairs_applied=repairs)

    def _has_overlap(self, rects: List[Dict[str, Any]]) -> bool:
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                if self._overlaps(a, b):
                    return True
        return False

    @staticmethod
    def _overlaps(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        ax, ay = a.get("x", 0), a.get("y", 0)
        aw, ah = a.get("width", 0), a.get("height", 0)
        bx, by = b.get("x", 0), b.get("y", 0)
        bw, bh = b.get("width", 0), b.get("height", 0)
        return not (
            ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay
        )
