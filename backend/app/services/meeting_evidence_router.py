"""
Per-evidence project routing for meetings that span several projects.

A meeting can discuss more than one project, but Evidence.project_id is
non-nullable, so each evidence row must be filed under exactly one project.
This routes each row independently through the existing ContextResolution
resolver, which is the same machinery WhatsApp already uses.

Deliberately conservative. The resolver only returns a project when the top
candidate clears both CONTEXT_RESOLUTION_MIN_CONFIDENCE and
CONTEXT_RESOLUTION_MIN_MARGIN over the runner-up. When two projects are
similarly plausible it returns no project, and the evidence is left where it
landed rather than being guessed at. Guessing here would silently file a
requirement under the wrong project, which is worse than leaving it for review.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.project import Project

logger = logging.getLogger(__name__)


class MeetingEvidenceRouter:
    """Files each evidence row of a meeting under its best-matching project."""

    def __init__(self, resolver=None):
        # Imported lazily: the resolver pulls in the LLM client, and this module
        # is imported by routes that do not always need it.
        if resolver is None:
            from app.services.context_resolution_service import ContextResolutionService

            resolver = ContextResolutionService()
        self.resolver = resolver

    def route_meeting_evidence(
        self,
        meeting_id: str,
        candidate_project_ids: List[str],
        db: Session,
        tenant_id: str = "default_tenant",
        actor_id: str = "synora_agent",
        workspace_id: str = "ws_default",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        if not candidate_project_ids:
            raise ValueError("candidate_project_ids is required")

        projects = (
            db.query(Project)
            .filter(Project.id.in_(candidate_project_ids))
            .all()
        )
        found = {p.id for p in projects}
        missing = [pid for pid in candidate_project_ids if pid not in found]
        if missing:
            raise ValueError(f"Unknown project id(s): {', '.join(missing)}")
        allowed_ids = {p.id for p in projects}

        evidence = (
            db.query(Evidence)
            .filter(Evidence.meeting_id == meeting_id)
            .order_by(Evidence.occurred_at.asc(), Evidence.created_at.asc())
            .all()
        )
        if not evidence:
            return {
                "meeting_id": meeting_id,
                "candidates": candidate_project_ids,
                "total": 0,
                "routed": 0,
                "unresolved": 0,
                "assignments": [],
                "dry_run": dry_run,
            }

        assignments: List[Dict[str, Any]] = []
        routed = 0
        unresolved = 0

        for row in evidence:
            text = (row.content or "").strip()
            if not text:
                continue

            try:
                result = self.resolver.resolve_context(
                    source="meeting",
                    content=text,
                    candidate_projects=projects,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    db=db,
                    record=not dry_run,
                )
            except Exception as exc:
                logger.warning("meeting_evidence_route_failed: %s error=%s", row.id, exc)
                unresolved += 1
                assignments.append(
                    {
                        "evidence_id": row.id,
                        "content": text[:80],
                        "from_project_id": row.project_id,
                        "to_project_id": None,
                        "decision": "error",
                        "confidence": 0.0,
                        "reason": str(exc)[:160],
                    }
                )
                continue

            target = getattr(result, "project_id", None)
            decision = getattr(result, "decision", None)
            confidence = float(getattr(result, "confidence", 0.0) or 0.0)
            reason = getattr(result, "reason", "") or ""

            # The caller named the projects this meeting may legitimately touch.
            # The resolver treats that list as a hint and still considers the
            # whole workspace, so without this guard evidence can be filed under
            # a project nobody nominated. That is exactly the failure the
            # candidate set exists to prevent.
            if target and target not in allowed_ids:
                proposed = target
                logger.info(
                    "meeting_evidence_route_rejected_out_of_scope: evidence=%s "
                    "resolver_project=%s not_in=%s",
                    row.id, proposed, candidate_project_ids,
                )
                target = None
                decision = f"{decision or 'resolved'}_out_of_scope"
                reason = (
                    f"Resolver proposed '{proposed}', which is outside the projects "
                    f"this meeting was scoped to. Left unmoved."
                )

            moved = bool(target) and target != row.project_id
            if target and not moved:
                # Already on the winning project; nothing to do.
                assignments.append(
                    {
                        "evidence_id": row.id,
                        "content": text[:80],
                        "from_project_id": row.project_id,
                        "to_project_id": target,
                        "decision": decision,
                        "confidence": confidence,
                        "reason": reason,
                        "changed": False,
                    }
                )
                continue

            if target and moved:
                assignments.append(
                    {
                        "evidence_id": row.id,
                        "content": text[:80],
                        "from_project_id": row.project_id,
                        "to_project_id": target,
                        "decision": decision,
                        "confidence": confidence,
                        "reason": reason,
                        "changed": True,
                    }
                )
                if not dry_run:
                    row.project_id = target
                routed += 1
            else:
                unresolved += 1
                assignments.append(
                    {
                        "evidence_id": row.id,
                        "content": text[:80],
                        "from_project_id": row.project_id,
                        "to_project_id": None,
                        "decision": decision,
                        "confidence": confidence,
                        "reason": reason,
                        "changed": False,
                    }
                )

        if not dry_run and routed:
            db.commit()

        by_project: Dict[str, int] = {}
        for a in assignments:
            if a.get("to_project_id"):
                by_project[a["to_project_id"]] = by_project.get(a["to_project_id"], 0) + 1

        logger.info(
            "meeting_evidence_routed: meeting=%s total=%s routed=%s unresolved=%s by_project=%s",
            meeting_id, len(evidence), routed, unresolved, by_project,
        )

        return {
            "meeting_id": meeting_id,
            "candidates": candidate_project_ids,
            "total": len(evidence),
            "routed": routed,
            "unresolved": unresolved,
            "by_project": by_project,
            "assignments": assignments,
            "dry_run": dry_run,
        }
