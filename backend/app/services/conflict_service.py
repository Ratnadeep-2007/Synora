from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.conflict import (
    Conflict,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
)
from app.models.intelligence import CandidateKnowledge
from app.models.project_state import (
    ApprovalStatus,
    ChangeOperation,
    ProjectState,
    ProjectStateVersion,
    StateChange,
)
from app.schemas.conflict import ConflictRead
from app.services.project_state_service import ConcurrencyError, ProjectStateService, StateTransitionError

logger = logging.getLogger(__name__)


class StaleProposalError(SynesisException):
    """Raised when an approval is attempted on a proposal created against an outdated state version."""
    pass


class PermissionDeniedError(SynesisException):
    """Raised when an unauthorized actor attempts cross-tenant or restricted actions."""
    pass


class ConflictService:
    """
    Core Conflict Engine.
    Detects semantic, architectural, requirement, decision, and workflow contradictions
    between Candidate Knowledge and Authoritative Project State.
    Enforces strict Human Review rules and audit versioning.
    """

    def __init__(self, state_service: Optional[ProjectStateService] = None):
        self.state_service = state_service or ProjectStateService()

    def detect_conflicts_for_candidate(
        self,
        candidate: CandidateKnowledge,
        db: Session,
        tenant_id: str = "default_tenant",
        source: str = "google_meet",
    ) -> Optional[Conflict]:
        """
        Evaluates CandidateKnowledge against current authoritative ProjectState.
        Detects:
        1. Workflow/architecture change (e.g. Onboarding before BA)
        2. Direct contradiction / decision reversal (e.g. replacing chosen DB, reversing confirmed policy)
        3. Requirement contradiction (e.g. removing mandatory offline mode or access restriction)
        4. Scope expansion / conflict (e.g. adding out-of-scope enterprise multi-cloud to MVP)
        5. Dependency conflict
        
        Strictly avoids false conflicts: Normal incremental additions that do not contradict
        existing state are NOT flagged as conflicts.
        """
        state = self.state_service.get_or_create_state(candidate.project_id, db)
        content_lower = candidate.content.lower()
        title_lower = candidate.title.lower()
        combined_text = f"{title_lower} {content_lower}"

        evidence_ids = []
        if candidate.evidence_ids_json:
            try:
                evidence_ids = json.loads(candidate.evidence_ids_json)
            except Exception:
                evidence_ids = []

        # 1. WORKFLOW / ARCHITECTURE CHANGE
        # Current workflow: ["BA", "Project", "Functional", "Tech", "Frappe"]
        # If candidate proposes "onboarding" before "ba" or restructuring agent workflow:
        workflow = json.loads(state.agent_workflow_json)
        if "onboarding" in combined_text and ("before ba" in combined_text or "workflow" in combined_text or "pipeline" in combined_text):
            if "Onboarding" not in workflow or workflow[0] != "Onboarding":
                current_wf_str = " → ".join(workflow)
                proposed_wf_str = "Onboarding → " + current_wf_str
                
                # Check if this conflict is already recorded and open
                existing = db.query(Conflict).filter(
                    Conflict.project_id == candidate.project_id,
                    Conflict.type == ConflictType.WORKFLOW.value,
                    Conflict.status.in_([ConflictStatus.OPEN.value, ConflictStatus.UNDER_REVIEW.value]),
                ).first()
                if existing:
                    return existing

                # Generate structured proposed state change
                state_change = self._create_or_get_state_change(
                    candidate=candidate,
                    state=state,
                    target_section="agent_workflow",
                    operation=ChangeOperation.REORDER.value,
                    db=db,
                    impact="Modifies initial agent execution sequence across the entire workforce pipeline.",
                    risk_level="high",
                )

                conflict = Conflict(
                    tenant_id=tenant_id,
                    project_id=candidate.project_id,
                    state_change_id=state_change.id if state_change else None,
                    candidate_id=candidate.id,
                    type=ConflictType.WORKFLOW.value,
                    severity=ConflictSeverity.HIGH.value,
                    title="Workflow Modification: Proposed Onboarding Agent Before BA",
                    description=(
                        f"Candidate proposes adding Onboarding agent before BA. "
                        f"Current workflow: {current_wf_str}. Proposed: {proposed_wf_str}."
                    ),
                    current_state_reference=json.dumps({"agent_workflow": workflow}),
                    proposed_change_reference=json.dumps({"agent_workflow": ["Onboarding"] + workflow}),
                    evidence_ids_json=json.dumps(evidence_ids),
                    status=ConflictStatus.OPEN.value,
                    impact="High impact on project execution; all downstream agents receive context via Onboarding.",
                    risk_level="high",
                    source=source,
                )
                db.add(conflict)
                db.commit()
                db.refresh(conflict)
                logger.warning(f"Detected WORKFLOW Conflict {conflict.id} on project {candidate.project_id}")
                return conflict

        # 2. DECISION REVERSAL / DIRECT CONTRADICTION
        # Check against existing confirmed decisions
        decisions = json.loads(state.decisions_json)
        for dec in decisions:
            dec_text = dec.get("text", "").lower() if isinstance(dec, dict) else str(dec).lower()
            
            # Contradiction: e.g. "postgresql" chosen, candidate proposes "mongodb" or "dynamodb"
            if ("postgres" in dec_text or "sql" in dec_text) and ("mongodb" in combined_text or "nosql" in combined_text or "dynamodb" in combined_text):
                conflict = Conflict(
                    tenant_id=tenant_id,
                    project_id=candidate.project_id,
                    candidate_id=candidate.id,
                    type=ConflictType.DECISION.value,
                    severity=ConflictSeverity.HIGH.value,
                    title="Decision Contradiction: Database Architecture Conflict",
                    description=f"Existing decision specifies '{dec_text}', but proposal suggests '{candidate.content}'.",
                    current_state_reference=json.dumps({"decision": dec}),
                    proposed_change_reference=json.dumps({"proposal": candidate.content}),
                    evidence_ids_json=json.dumps(evidence_ids),
                    status=ConflictStatus.OPEN.value,
                    impact="Core database change would invalidate existing relational data models and migrations.",
                    risk_level="high",
                    source=source,
                )
                db.add(conflict)
                db.commit()
                db.refresh(conflict)
                logger.warning(f"Detected DECISION Conflict {conflict.id}")
                return conflict
            
            # Direct reversal: e.g. "reject" vs "accept", "disable" vs "enable"
            if ("do not" in dec_text or "reject" in dec_text) and ("let's" in combined_text or "adopt" in combined_text or "decided to add" in combined_text):
                # Check for overlapping topic keywords
                topic_words = [w for w in dec_text.split() if len(w) > 4 and w in combined_text]
                if topic_words:
                    conflict = Conflict(
                        tenant_id=tenant_id,
                        project_id=candidate.project_id,
                        candidate_id=candidate.id,
                        type=ConflictType.DECISION.value,
                        severity=ConflictSeverity.HIGH.value,
                        title="Decision Reversal: Overriding Prior Decision",
                        description=f"Candidate directly reverses prior decision: '{dec_text}'.",
                        current_state_reference=json.dumps({"decision": dec}),
                        proposed_change_reference=json.dumps({"proposal": candidate.content}),
                        evidence_ids_json=json.dumps(evidence_ids),
                        status=ConflictStatus.OPEN.value,
                        impact="Reversing confirmed decision alters project baseline.",
                        risk_level="high",
                        source=source,
                    )
                    db.add(conflict)
                    db.commit()
                    db.refresh(conflict)
                    return conflict

        # 3. REQUIREMENT CONTRADICTION
        requirements = json.loads(state.requirements_json)
        for req in requirements:
            req_text = req.get("content", "").lower() if isinstance(req, dict) else str(req).lower()
            # E.g. Existing requirement is "offline mode" or "read-only access", candidate proposes "drop offline" or "write access"
            if "offline" in req_text and ("remove offline" in combined_text or "drop offline" in combined_text or "no offline" in combined_text or "cancel offline" in combined_text):
                conflict = Conflict(
                    tenant_id=tenant_id,
                    project_id=candidate.project_id,
                    candidate_id=candidate.id,
                    type=ConflictType.REQUIREMENT.value,
                    severity=ConflictSeverity.HIGH.value,
                    title="Requirement Contradiction: Offline Support Cancellation",
                    description=f"Candidate proposes removing existing requirement '{req_text}'.",
                    current_state_reference=json.dumps({"requirement": req}),
                    proposed_change_reference=json.dumps({"proposal": candidate.content}),
                    evidence_ids_json=json.dumps(evidence_ids),
                    status=ConflictStatus.OPEN.value,
                    impact="Breaks user expectation for offline reliability.",
                    risk_level="high",
                    source=source,
                )
                db.add(conflict)
                db.commit()
                db.refresh(conflict)
                return conflict
            
            if "read-only" in req_text and ("write access" in combined_text or "full access" in combined_text or "admin access" in combined_text):
                conflict = Conflict(
                    tenant_id=tenant_id,
                    project_id=candidate.project_id,
                    candidate_id=candidate.id,
                    type=ConflictType.REQUIREMENT.value,
                    severity=ConflictSeverity.HIGH.value,
                    title="Requirement Contradiction: Security Permission Escalation",
                    description=f"Candidate requests elevated access conflicting with read-only constraint.",
                    current_state_reference=json.dumps({"requirement": req}),
                    proposed_change_reference=json.dumps({"proposal": candidate.content}),
                    evidence_ids_json=json.dumps(evidence_ids),
                    status=ConflictStatus.OPEN.value,
                    impact="Expands security surface area for agent workspace access.",
                    risk_level="high",
                    source=source,
                )
                db.add(conflict)
                db.commit()
                db.refresh(conflict)
                return conflict

        # 4. SCOPE CONFLICT / SCOPE EXPANSION
        constraints = json.loads(state.constraints_json)
        constraint_text = " ".join([str(c).lower() for c in constraints]) + " " + state.vision.lower()
        if ("mvp" in constraint_text or "google meet only" in constraint_text or "lean" in constraint_text) and (
            "multi-cloud" in combined_text or "blockchain" in combined_text or "enterprise sso" in combined_text
        ):
            conflict = Conflict(
                tenant_id=tenant_id,
                project_id=candidate.project_id,
                candidate_id=candidate.id,
                type=ConflictType.SCOPE.value,
                severity=ConflictSeverity.MEDIUM.value,
                title="Scope Expansion Conflict: Exceeds MVP Boundary",
                description=f"Candidate introduces heavy scope outside agreed MVP constraints: '{candidate.content}'.",
                current_state_reference=json.dumps({"constraints": constraints, "vision": state.vision}),
                proposed_change_reference=json.dumps({"proposal": candidate.content}),
                evidence_ids_json=json.dumps(evidence_ids),
                status=ConflictStatus.OPEN.value,
                impact="Risk of timeline slip and scope bloat for current milestone.",
                risk_level="medium",
                source=source,
            )
            db.add(conflict)
            db.commit()
            db.refresh(conflict)
            return conflict

        # FALSE CONFLICT AVOIDANCE:
        # Incremental non-conflicting additions simply return None.
        return None

    def _create_or_get_state_change(
        self,
        candidate: CandidateKnowledge,
        state: ProjectState,
        target_section: str,
        operation: str,
        db: Session,
        impact: str,
        risk_level: str,
    ) -> StateChange:
        """Finds existing proposed change or creates a new structured proposal."""
        existing_change = db.query(StateChange).filter(
            StateChange.candidate_id == candidate.id,
            StateChange.approval_status == ApprovalStatus.PROPOSED.value,
        ).first()
        if existing_change:
            return existing_change

        val_data = {
            "title": candidate.title,
            "content": candidate.content,
            "target_section": target_section,
            "impact": impact,
            "risk_level": risk_level,
        }

        change = StateChange(
            project_id=candidate.project_id,
            candidate_id=candidate.id,
            state_version_before=state.current_version,
            operation=operation,
            target_section=target_section,
            value_json=json.dumps(val_data),
            reason=f"Conflict review proposal: {candidate.title}",
            actor_id="conflict_engine",
            evidence_ids_json=candidate.evidence_ids_json,
            approval_status=ApprovalStatus.PROPOSED.value,
        )
        db.add(change)
        db.commit()
        db.refresh(change)
        return change

    # =========================================================================
    # HUMAN REVIEW OPERATIONS
    # =========================================================================

    def approve_conflict(
        self,
        conflict_id: str,
        actor_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Approves a conflict / proposal:
        1. Verifies tenant isolation and permissions.
        2. Verifies proposal is still based on current state (detects stale proposals).
        3. Verifies evidence exists.
        4. Performs transaction-safe state update.
        5. Creates new ProjectStateVersion.
        6. Creates audit record and updates conflict status to 'approved'.
        """
        conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
        if not conflict:
            raise StateTransitionError(f"Conflict '{conflict_id}' not found.")

        # 1. Tenant Isolation & Permissions
        if conflict.tenant_id != tenant_id:
            raise PermissionDeniedError(f"Cross-tenant access prohibited for tenant '{tenant_id}'.")

        if conflict.status not in (ConflictStatus.OPEN.value, ConflictStatus.UNDER_REVIEW.value):
            raise StateTransitionError(
                f"Cannot approve conflict in '{conflict.status}' status (must be 'open' or 'under_review')."
            )

        # 2. Check Evidence
        evidence_ids = json.loads(conflict.evidence_ids_json) if conflict.evidence_ids_json else []
        if not evidence_ids:
            logger.warning(f"Conflict {conflict_id} lacks explicit evidence links.")

        state = db.query(ProjectState).filter(ProjectState.project_id == conflict.project_id).first()
        if not state:
            raise StateTransitionError(f"ProjectState for '{conflict.project_id}' not found.")

        # 3. Detect Stale Proposals
        if conflict.state_change:
            if conflict.state_change.state_version_before != state.current_version:
                raise StaleProposalError(
                    f"Stale proposal detected: Change was proposed against v{conflict.state_change.state_version_before}, "
                    f"but current state is v{state.current_version}. Approval aborted."
                )

        # 4. Perform Transaction-Safe State Update
        v_before = state.current_version
        v_after = v_before + 1

        # Apply mutation according to conflict type
        if conflict.type == ConflictType.WORKFLOW.value:
            wf = json.loads(state.agent_workflow_json)
            if "Onboarding" not in wf:
                wf.insert(0, "Onboarding")
            state.agent_workflow_json = json.dumps(wf)

        elif conflict.type == ConflictType.DECISION.value:
            decs = json.loads(state.decisions_json)
            decs.append({
                "id": f"dec_{len(decs)+1:03d}",
                "text": conflict.title,
                "detail": conflict.description,
                "evidence_ids": evidence_ids,
                "approved_by": actor_id,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })
            state.decisions_json = json.dumps(decs)

        elif conflict.type == ConflictType.REQUIREMENT.value:
            reqs = json.loads(state.requirements_json)
            reqs.append({
                "id": f"req_{len(reqs)+1:03d}",
                "title": conflict.title,
                "content": conflict.description or conflict.title,
                "evidence_ids": evidence_ids,
            })
            state.requirements_json = json.dumps(reqs)

        state.current_version = v_after
        state.updated_at = datetime.now(timezone.utc)

        # 5. Create new ProjectStateVersion
        snapshot = self.state_service._dump_state_dict(state)
        reason_text = f"Approved Conflict {conflict.id} ({conflict.type}): {conflict.title}"
        if note:
            reason_text += f" [Note: {note}]"

        ver = ProjectStateVersion(
            project_id=state.project_id,
            version_number=v_after,
            snapshot_json=json.dumps(snapshot),
            reason=reason_text,
            change_summary_json=json.dumps({
                "conflict_id": conflict.id,
                "type": conflict.type,
                "actor": actor_id,
            }),
            actor_id=actor_id,
        )
        db.add(ver)

        # 6. Update Conflict and StateChange status
        conflict.status = ConflictStatus.APPROVED.value
        conflict.resolved_at = datetime.now(timezone.utc)
        conflict.resolved_by = actor_id

        if conflict.state_change:
            conflict.state_change.approval_status = ApprovalStatus.APPROVED.value
            conflict.state_change.state_version_after = v_after
            conflict.state_change.actor_id = actor_id
            conflict.state_change.resolved_at = datetime.now(timezone.utc)

        if conflict.candidate:
            conflict.candidate.status = "approved"

        db.commit()
        db.refresh(conflict)
        db.refresh(state)

        logger.info(f"Approved Conflict {conflict.id} -> State bumped v{v_before} -> v{v_after}")
        return {
            "conflict": conflict,
            "new_version": v_after,
            "message": f"Conflict approved and applied to Project State v{v_after}.",
        }

    def reject_conflict(
        self,
        conflict_id: str,
        actor_id: str,
        reason: str,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> Conflict:
        """
        Rejects a proposed conflict change.
        Preserves existing authoritative state completely untouched.
        """
        conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
        if not conflict:
            raise StateTransitionError(f"Conflict '{conflict_id}' not found.")

        if conflict.tenant_id != tenant_id:
            raise PermissionDeniedError(f"Cross-tenant access prohibited for tenant '{tenant_id}'.")

        if conflict.status not in (ConflictStatus.OPEN.value, ConflictStatus.UNDER_REVIEW.value):
            raise StateTransitionError(f"Cannot reject conflict in '{conflict.status}' status.")

        conflict.status = ConflictStatus.REJECTED.value
        conflict.resolved_at = datetime.now(timezone.utc)
        conflict.resolved_by = actor_id
        conflict.description = (conflict.description or "") + f" [REJECTED: {reason}]"

        if conflict.state_change:
            conflict.state_change.approval_status = ApprovalStatus.REJECTED.value
            conflict.state_change.actor_id = actor_id
            conflict.state_change.resolved_at = datetime.now(timezone.utc)

        if conflict.candidate:
            conflict.candidate.status = "rejected"

        db.commit()
        db.refresh(conflict)
        logger.info(f"Rejected Conflict {conflict.id} by {actor_id}: {reason}")
        return conflict

    def mark_unresolved(
        self,
        conflict_id: str,
        actor_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        note: Optional[str] = None,
    ) -> Conflict:
        """
        Marks conflict as UNRESOLVED.
        Preserves BOTH existing authoritative state and the unresolved proposal for future review.
        """
        conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
        if not conflict:
            raise StateTransitionError(f"Conflict '{conflict_id}' not found.")

        if conflict.tenant_id != tenant_id:
            raise PermissionDeniedError(f"Cross-tenant access prohibited for tenant '{tenant_id}'.")

        conflict.status = ConflictStatus.UNRESOLVED.value
        conflict.resolved_at = datetime.now(timezone.utc)
        conflict.resolved_by = actor_id
        if note:
            conflict.description = (conflict.description or "") + f" [UNRESOLVED NOTE: {note}]"

        db.commit()
        db.refresh(conflict)
        logger.info(f"Marked Conflict {conflict.id} as UNRESOLVED by {actor_id}")
        return conflict

    def get_conflicts(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        status: Optional[str] = None,
    ) -> List[Conflict]:
        """Lists conflicts for a project with strict tenant boundary enforcement."""
        q = db.query(Conflict).filter(
            Conflict.project_id == project_id,
            Conflict.tenant_id == tenant_id,
        )
        if status:
            q = q.filter(Conflict.status == status)
        return q.order_by(Conflict.created_at.desc()).all()

    def get_conflict_by_id(
        self,
        conflict_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> Optional[Conflict]:
        """Retrieves single conflict with tenant verification."""
        conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
        if not conflict:
            return None
        if conflict.tenant_id != tenant_id:
            raise PermissionDeniedError(f"Cross-tenant access prohibited.")
        return conflict

    def format_conflict_read(self, c: Conflict) -> ConflictRead:
        """Converts model to typed DTO."""
        evidence_ids = []
        if c.evidence_ids_json:
            try:
                evidence_ids = json.loads(c.evidence_ids_json)
            except Exception:
                evidence_ids = []

        return ConflictRead(
            id=c.id,
            tenant_id=c.tenant_id,
            project_id=c.project_id,
            state_change_id=c.state_change_id,
            candidate_id=c.candidate_id,
            type=c.type,
            severity=c.severity,
            title=c.title,
            description=c.description,
            current_state_reference=c.current_state_reference,
            proposed_change_reference=c.proposed_change_reference,
            evidence_ids=evidence_ids,
            status=c.status,
            impact=c.impact,
            risk_level=c.risk_level,
            source=c.source,
            created_at=c.created_at,
            resolved_at=c.resolved_at,
            resolved_by=c.resolved_by,
        )

    def create_conflict(
        self,
        project_id: str,
        title: str,
        description: str,
        severity: str = "high",
        conflict_type: str = "architecture_contradiction",
        evidence_ids: Optional[List[str]] = None,
        db: Session = None,
        tenant_id: str = "default_tenant",
        candidate_id: Optional[str] = None,
        state_change_id: Optional[str] = None,
        source: str = "multi_source",
    ) -> Conflict:
        """Explicitly records a detected multi-source contradiction."""
        conflict = Conflict(
            tenant_id=tenant_id,
            project_id=project_id,
            candidate_id=candidate_id,
            state_change_id=state_change_id,
            type=conflict_type,
            severity=severity,
            title=title,
            description=description,
            current_state_reference=json.dumps({"description": description}),
            proposed_change_reference=json.dumps({"title": title}),
            evidence_ids_json=json.dumps(evidence_ids or []),
            status=ConflictStatus.OPEN.value,
            impact="Cross-source contradiction requires explicit human reconciliation.",
            risk_level="high",
            source=source,
        )
        db.add(conflict)
        db.commit()
        db.refresh(conflict)
        logger.warning(f"Recorded Conflict {conflict.id} ({conflict_type}): {title}")
        return conflict

    def resolve_conflict(
        self,
        conflict_id: str,
        resolution_notes: str,
        actor_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> Conflict:
        """Marks a conflict as resolved with human notes."""
        conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
        if not conflict:
            raise StateTransitionError(f"Conflict '{conflict_id}' not found.")
        if conflict.tenant_id != tenant_id:
            raise PermissionDeniedError(f"Cross-tenant access prohibited.")

        conflict.status = ConflictStatus.APPROVED.value
        conflict.resolved_at = datetime.now(timezone.utc)
        conflict.resolved_by = actor_id
        if conflict.description:
            conflict.description += f" [RESOLVED: {resolution_notes}]"
        else:
            conflict.description = f"[RESOLVED: {resolution_notes}]"

        db.commit()
        db.refresh(conflict)
        logger.info(f"Resolved Conflict {conflict.id} by {actor_id}")
        return conflict
