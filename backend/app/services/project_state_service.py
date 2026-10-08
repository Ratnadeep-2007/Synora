from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.intelligence import CandidateKnowledge
from app.models.project_state import (
    ApprovalStatus,
    ChangeOperation,
    ProjectState,
    ProjectStateVersion,
    StateChange,
)
from app.schemas.project_state import ProjectStateRead

logger = logging.getLogger(__name__)


class ConcurrencyError(SynesisException):
    """Raised when an optimistic concurrency conflict occurs during state mutation."""
    pass


class StateTransitionError(SynesisException):
    """Raised when an invalid state transition or unauthorized mutation is attempted."""
    pass


class ProjectStateService:
    """
    Authoritative Project State Service.
    Enforces the core product principle:
    - Candidate Knowledge is NOT Authoritative Project State.
    - Project State is strictly versioned and immutable across versions.
    - State mutations require explicit operations (insert, update, delete, supersede).
    - High-impact changes require explicit human approval.
    - Optimistic concurrency protection prevents race condition overwrites.
    """

    def get_or_create_state(self, project_id: str, db: Session, title: str = "Project") -> ProjectState:
        """Retrieves existing ProjectState or initializes Version 1 baseline."""
        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        if not state:
            state = ProjectState(
                project_id=project_id,
                current_version=1,
                title=title,
                vision="Build an evidence-backed software product.",
                requirements_json="[]",
                architecture_json="[]",
                agent_workflow_json='["BA", "Project", "Functional", "Tech", "Frappe"]',
                decisions_json="[]",
                constraints_json="[]",
                assumptions_json="[]",
                open_questions_json="[]",
            )
            db.add(state)
            db.flush()

            # Create initial immutable snapshot v1
            snapshot = self._dump_state_dict(state)
            v1 = ProjectStateVersion(
                project_id=project_id,
                version_number=1,
                snapshot_json=json.dumps(snapshot),
                reason="Initial baseline project state created",
                change_summary_json=json.dumps({"action": "initialize"}),
                actor_id="system",
            )
            db.add(v1)
            db.commit()
            db.refresh(state)
            logger.info(f"Initialized ProjectState v1 for project '{project_id}'")

        return state

    def _dump_state_dict(self, state: ProjectState) -> Dict[str, Any]:
        """Serializes current state into a plain dictionary."""
        return {
            "project_id": state.project_id,
            "version": state.current_version,
            "title": state.title,
            "vision": state.vision,
            "requirements": json.loads(state.requirements_json),
            "architecture": json.loads(state.architecture_json),
            "agent_workflow": json.loads(state.agent_workflow_json),
            "decisions": json.loads(state.decisions_json),
            "constraints": json.loads(state.constraints_json),
            "assumptions": json.loads(state.assumptions_json),
            "open_questions": json.loads(state.open_questions_json),
            "updated_at": state.updated_at.isoformat() if state.updated_at else None,
        }

    def format_state_read(self, state: ProjectState) -> ProjectStateRead:
        """Converts database model to typed public DTO."""
        d = self._dump_state_dict(state)
        return ProjectStateRead(
            project_id=d["project_id"],
            current_version=d["version"],
            title=d["title"],
            vision=d["vision"],
            requirements=d["requirements"],
            architecture=d["architecture"],
            agent_workflow=d["agent_workflow"],
            decisions=d["decisions"],
            constraints=d["constraints"],
            assumptions=d["assumptions"],
            open_questions=d["open_questions"],
            updated_at=state.updated_at,
        )

    def propose_change(
        self,
        project_id: str,
        section: str,
        operation: Any,
        proposed_value: Any,
        reason: str,
        actor_id: str = "human_reviewer",
        evidence_ids: Optional[List[str]] = None,
        db: Optional[Session] = None,
        candidate_id: Optional[str] = None,
    ) -> StateChange:
        """
        Creates an explicit proposed StateChange for a target section.
        Authoritative Project State remains completely untouched until approval!
        """
        state = self.get_or_create_state(project_id, db)
        op_val = operation.value if hasattr(operation, "value") else str(operation)
        change = StateChange(
            project_id=project_id,
            candidate_id=candidate_id,
            state_version_before=state.current_version,
            operation=op_val,
            target_section=section,
            value_json=json.dumps(proposed_value) if not isinstance(proposed_value, str) else proposed_value,
            reason=reason,
            actor_id=actor_id,
            evidence_ids_json=json.dumps(evidence_ids or []),
            approval_status=ApprovalStatus.PROPOSED.value,
        )
        db.add(change)
        db.commit()
        db.refresh(change)
        logger.info(f"Proposed StateChange {change.id} for section '{section}' (reason: {reason})")
        return change

    def propose_change_from_candidate(
        self,
        candidate: CandidateKnowledge,
        db: Session,
        actor_id: str = "system_intelligence",
    ) -> StateChange:
        """
        Creates an explicit proposed StateChange from extracted CandidateKnowledge.
        Authoritative Project State remains completely untouched!

        Idempotent: a candidate with an already-open proposal reuses it.
        Reprocessing a meeting must not stack duplicate proposals for the
        same candidate. Verified live 2026-10-08: two pipeline re-runs
        doubled MediQueue's proposals (8 -> 16) before this guard.
        """
        existing = (
            db.query(StateChange)
            .filter(
                StateChange.candidate_id == candidate.id,
                StateChange.approval_status == ApprovalStatus.PROPOSED.value,
            )
            .order_by(StateChange.created_at.desc())
            .first()
        )
        if existing:
            logger.info(
                "proposal_reused_open: candidate=%s change=%s",
                candidate.id,
                existing.id,
            )
            return existing

        state = self.get_or_create_state(candidate.project_id, db)

        # Map candidate category to target section
        target_section = "decisions"
        operation = ChangeOperation.INSERT.value

        content_lower = candidate.content.lower()
        if "onboarding" in content_lower and ("workflow" in content_lower or "before ba" in content_lower or "pipeline" in content_lower):
            target_section = "agent_workflow"
            operation = ChangeOperation.REORDER.value
        elif candidate.category == "requirement_candidate":
            target_section = "requirements"
        elif candidate.category == "question":
            target_section = "open_questions"
        elif candidate.category == "assumption":
            target_section = "assumptions"

        # Proposed value structure
        value_data = {
            "title": candidate.title,
            "content": candidate.content,
            "category": candidate.category,
            "classification": candidate.classification,
            "evidence_ids": json.loads(candidate.evidence_ids_json),
        }

        change = StateChange(
            project_id=candidate.project_id,
            candidate_id=candidate.id,
            state_version_before=state.current_version,
            operation=operation,
            target_section=target_section,
            value_json=json.dumps(value_data),
            reason=f"Candidate {candidate.classification} extracted from meeting {candidate.meeting_id or 'unknown'}",
            actor_id=actor_id,
            evidence_ids_json=candidate.evidence_ids_json,
            approval_status=ApprovalStatus.PROPOSED.value,
        )
        db.add(change)
        candidate.status = "proposed"
        db.commit()
        db.refresh(change)
        logger.info(f"Proposed StateChange {change.id} for section '{target_section}' from candidate {candidate.id}")
        return change

    def approve_state_change(
        self,
        change_id: str,
        actor_id: str,
        db: Session,
        note: Optional[str] = None,
    ) -> ProjectStateVersion:
        """
        Atomically approves a proposed StateChange:
        1. Optimistic concurrency check (version before must match current version)
        2. Applies mutation to the target section
        3. Increments current_version (e.g. v1 -> v2)
        4. Saves new immutable ProjectStateVersion snapshot
        5. Updates StateChange and CandidateKnowledge status to 'approved'
        """
        change = db.query(StateChange).filter(StateChange.id == change_id).first()
        if not change:
            raise StateTransitionError(f"StateChange '{change_id}' not found.")

        if change.approval_status != ApprovalStatus.PROPOSED.value:
            raise StateTransitionError(
                f"Cannot approve StateChange in '{change.approval_status}' state (must be 'proposed')."
            )

        state = db.query(ProjectState).filter(ProjectState.project_id == change.project_id).first()
        if not state:
            raise StateTransitionError(f"ProjectState for '{change.project_id}' not found.")

        # Optimistic concurrency check
        if change.state_version_before != state.current_version:
            raise ConcurrencyError(
                f"Optimistic concurrency violation: Change was proposed against v{change.state_version_before}, "
                f"but current state is v{state.current_version}. Please re-evaluate against current state."
            )

        value = json.loads(change.value_json)
        section = change.target_section

        # Mutate target section explicitly
        if section == "agent_workflow":
            if isinstance(value, list):
                state.agent_workflow_json = json.dumps(value)
            else:
                workflow = json.loads(state.agent_workflow_json)
                if "onboarding" in str(value).lower():
                    if "Onboarding" not in workflow:
                        workflow.insert(0, "Onboarding")
                state.agent_workflow_json = json.dumps(workflow)

        elif section == "decisions":
            decisions = json.loads(state.decisions_json)
            dec_text = value.get("text") or value.get("content") if isinstance(value, dict) else str(value)
            decisions.append({
                "id": f"dec_{len(decisions)+1:03d}",
                "text": dec_text,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "evidence_ids": json.loads(change.evidence_ids_json),
                "approved_by": actor_id,
            })
            state.decisions_json = json.dumps(decisions)

        elif section == "requirements":
            reqs = json.loads(state.requirements_json)
            reqs.append({
                "id": f"req_{len(reqs)+1:03d}",
                "title": value.get("title", "Requirement"),
                "content": value.get("content", str(value)),
                "evidence_ids": json.loads(change.evidence_ids_json),
            })
            state.requirements_json = json.dumps(reqs)

        elif section == "open_questions":
            questions = json.loads(state.open_questions_json)
            questions.append(value.get("content", str(value)))
            state.open_questions_json = json.dumps(questions)

        elif section == "assumptions":
            assumptions = json.loads(state.assumptions_json)
            assumptions.append(value.get("content", str(value)))
            state.assumptions_json = json.dumps(assumptions)

        # Advance authoritative version
        new_version_num = state.current_version + 1
        state.current_version = new_version_num
        state.updated_at = datetime.now(timezone.utc)

        # Create new version snapshot
        snapshot = self._dump_state_dict(state)
        reason_text = f"Approved change {change.id}: {change.reason}"
        if note:
            reason_text += f" (Note: {note})"

        version_record = ProjectStateVersion(
            project_id=state.project_id,
            version_number=new_version_num,
            snapshot_json=json.dumps(snapshot),
            reason=reason_text,
            change_summary_json=json.dumps({
                "change_id": change.id,
                "section": section,
                "operation": change.operation,
                "actor": actor_id,
            }),
            actor_id=actor_id,
        )
        db.add(version_record)

        # Update change record
        change.approval_status = ApprovalStatus.APPROVED.value
        change.state_version_after = new_version_num
        change.actor_id = actor_id
        change.resolved_at = datetime.now(timezone.utc)

        # Update candidate knowledge if linked
        if change.candidate:
            change.candidate.status = "approved"

        db.commit()
        db.refresh(version_record)
        db.refresh(state)

        logger.info(
            f"Approved StateChange {change.id} -> ProjectState transitioned v{change.state_version_before} -> v{new_version_num}"
        )
        return version_record

    def reject_state_change(
        self,
        change_id: str,
        actor_id: str,
        reason: str,
        db: Session,
    ) -> StateChange:
        """Explicitly rejects a proposed StateChange. Authoritative state remains untouched."""
        change = db.query(StateChange).filter(StateChange.id == change_id).first()
        if not change:
            raise StateTransitionError(f"StateChange '{change_id}' not found.")

        if change.approval_status != ApprovalStatus.PROPOSED.value:
            raise StateTransitionError(f"Cannot reject StateChange in '{change.approval_status}' status.")

        change.approval_status = ApprovalStatus.REJECTED.value
        change.actor_id = actor_id
        change.reason = f"{change.reason} [REJECTED: {reason}]"
        change.resolved_at = datetime.now(timezone.utc)

        if change.candidate:
            change.candidate.status = "rejected"

        db.commit()
        db.refresh(change)
        logger.info(f"Rejected StateChange {change.id} by {actor_id}: {reason}")
        return change

    def rollback_to_version(
        self,
        project_id: str,
        target_version: int,
        actor_id: str,
        reason: str,
        db: Session,
    ) -> ProjectStateVersion:
        """
        Reverts Project State to a previous version snapshot.
        Enforces auditability: Does NOT delete history; creates a new version with the restored snapshot!
        """
        state = db.query(ProjectState).filter(ProjectState.project_id == project_id).first()
        if not state:
            raise StateTransitionError(f"ProjectState for '{project_id}' not found.")

        target_ver_record = (
            db.query(ProjectStateVersion)
            .filter(
                ProjectStateVersion.project_id == project_id,
                ProjectStateVersion.version_number == target_version,
            )
            .first()
        )
        if not target_ver_record:
            raise StateTransitionError(f"Version {target_version} not found for project '{project_id}'.")

        snapshot = json.loads(target_ver_record.snapshot_json)

        # Restore state attributes
        state.title = snapshot.get("title", state.title)
        state.vision = snapshot.get("vision", state.vision)
        state.requirements_json = json.dumps(snapshot.get("requirements", []))
        state.architecture_json = json.dumps(snapshot.get("architecture", []))
        state.agent_workflow_json = json.dumps(snapshot.get("agent_workflow", []))
        state.decisions_json = json.dumps(snapshot.get("decisions", []))
        state.constraints_json = json.dumps(snapshot.get("constraints", []))
        state.assumptions_json = json.dumps(snapshot.get("assumptions", []))
        state.open_questions_json = json.dumps(snapshot.get("open_questions", []))

        # Advance version number
        new_version_num = state.current_version + 1
        state.current_version = new_version_num
        state.updated_at = datetime.now(timezone.utc)

        # Explicit rollback version record
        new_version_record = ProjectStateVersion(
            project_id=project_id,
            version_number=new_version_num,
            snapshot_json=json.dumps(self._dump_state_dict(state)),
            reason=f"Rollback to v{target_version}: {reason}",
            change_summary_json=json.dumps({
                "action": "rollback",
                "restored_version": target_version,
                "actor": actor_id,
            }),
            actor_id=actor_id,
        )
        db.add(new_version_record)

        # Record explicit StateChange audit entry
        audit_change = StateChange(
            project_id=project_id,
            state_version_before=state.current_version - 1,
            state_version_after=new_version_num,
            operation=ChangeOperation.SUPERSEDE.value,
            target_section="full_state",
            value_json=json.dumps({"restored_version": target_version}),
            reason=f"Rollback to v{target_version}: {reason}",
            actor_id=actor_id,
            approval_status=ApprovalStatus.APPROVED.value,
            resolved_at=datetime.now(timezone.utc),
        )
        db.add(audit_change)

        db.commit()
        db.refresh(new_version_record)
        logger.info(f"Rolled back project '{project_id}' to v{target_version}, advancing to v{new_version_num}")
        return new_version_record
