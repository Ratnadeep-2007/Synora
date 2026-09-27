import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_ai_workforce_service,
    get_conflict_service,
    get_current_user,
    get_db,
    get_excalidraw_service,
    get_pipeline_coordinator,
    get_project_agent_service,
    get_project_state_service,
)
from app.core.exceptions import SynesisException
from app.models.agent_workforce import AgentExecution
from app.models.project import Project, ProjectAgent, Workspace
from app.models.conflict import Conflict
from app.models.evidence import Evidence
from app.models.excalidraw import ExcalidrawArtifact, ExcalidrawProposal, ExcalidrawRevision
from app.models.intelligence import AgentRun, CandidateKnowledge
from app.models.project_state import (
    ApprovalStatus,
    ProjectState,
    ProjectStateVersion,
    StateChange,
)
from app.models.user import User
from app.schemas.agent_workforce import (
    AgentDefinitionRead,
    AgentExecutionRead,
    AgentRunTriggerRequest,
    AgentRunTriggerResponse,
)
from app.schemas.conflict import ConflictRead, ConflictReviewRequest, ConflictReviewResponse
from app.schemas.excalidraw import (
    AiGenerateDiagramRequest,
    ExcalidrawArtifactRead,
    ExcalidrawIngestRequest,
    ExcalidrawProposalRead,
    ExcalidrawProposalReviewRequest,
    ExcalidrawRevisionRead,
    ExcalidrawRevisionDiffRead,
)
from app.schemas.intelligence import AgentRunRead, CandidateKnowledgeRead
from app.services.context_resolver import ContextResolverService, UNKNOWN_CONTEXT_ID
from app.schemas.project_state import (
    ProjectStateRead,
    ProjectStateVersionRead,
    ProposalApprovalRequest,
    ProposalRejectRequest,
    RollbackRequest,
    StateChangeRead,
)
from app.schemas.project_agent import (
    ProjectAgentRead,
    ProjectAgentDispatchRequest,
    ProjectAgentMemoryUpdate,
    ProjectCreateRequest,
    ProjectRead,
    WorkspaceAgentRead,
    WorkspaceAgentDispatchRequest,
    WorkspaceAgentMemoryUpdate,
)
from app.schemas.source_event import EvidenceRead
from app.services.ai_workforce import (
    AIWorkforceService,
    AgentOutputValidationError,
    AgentPermissionError,
)
from app.services.conflict_service import (
    ConflictService,
    PermissionDeniedError,
    StaleProposalError,
)
from app.services.excalidraw_service import ExcalidrawError, ExcalidrawService
from app.services.pipeline_coordinator import PipelineCoordinator, PipelineExecutionResult
from app.services.project_agent_service import ProjectAgentException, ProjectAgentService
from app.services.project_state_service import ConcurrencyError, ProjectStateService, StateTransitionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Project State & Knowledge Pipeline"])


# ==============================================================================
# Workspace, Project & Project Agent Endpoints (One Project = One Project Agent)
# ==============================================================================

@router.post(
    "",
    response_model=ProjectRead,
    summary="Create Project & Auto-provision Project Agent",
    description="Creates a new project within a workspace and automatically provisions its dedicated Project Agent and Excalidraw living workspace.",
)
async def create_project(
    body: ProjectCreateRequest,
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import uuid
    from app.schemas.project_agent import PROJECT_SOURCE_IDS
    from app.services.project_agent_service import ProjectAgentService as _PAS

    sources = body.sources
    if sources is not None:
        try:
            sources = _PAS.validate_sources(sources)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_source",
                    "message": str(exc),
                    "allowed_sources": list(PROJECT_SOURCE_IDS),
                },
            )
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    proj = project_agent_service.get_or_create_project(
        project_id=project_id,
        db=db,
        workspace_id=body.workspace_id or "ws_default",
        name=body.name,
        description=body.description or "",
        sources=sources,
    )
    agent = project_agent_service.get_or_provision_project_agent(project_id, db)
    return ProjectRead(
        id=proj.id,
        workspace_id=proj.workspace_id,
        name=proj.name,
        description=proj.description,
        project_agent_id=agent.id,
        created_at=proj.created_at,
        updated_at=proj.updated_at,
    )


@router.get(
    "",
    response_model=List[ProjectRead],
    summary="List Projects",
    description="Lists all projects in the workspace with their associated Project Agent ID.",
)
async def list_projects(
    workspace_id: str = Query("ws_default", description="Workspace ID filter"),
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    projects = db.query(Project).filter(Project.workspace_id == workspace_id).order_by(Project.created_at.desc()).all()
    results = []
    for p in projects:
        agent = db.query(ProjectAgent).filter(ProjectAgent.project_id == p.id).first()
        results.append(
            ProjectRead(
                id=p.id,
                workspace_id=p.workspace_id,
                name=p.name,
                description=p.description,
                project_agent_id=agent.id if agent else None,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
        )
    return results


@router.get(
    "/{project_id}/agent",
    response_model=ProjectAgentRead,
    summary="Get Logical Project Agent",
    description="Retrieves the dedicated logical Project Agent for a project, including its isolated working memory, subordinate capabilities, and connected tools.",
)
async def get_project_agent(
    project_id: str,
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = project_agent_service.get_or_provision_project_agent(project_id, db)
    return project_agent_service.format_project_agent_read(agent, db)


@router.post(
    "/{project_id}/agent/dispatch",
    response_model=AgentRunTriggerResponse,
    summary="Project Agent Capability Dispatch",
    description="The Project Agent coordinates and executes a specialist capability (BA, Planning, Functional, Tech, Frappe) within the project's isolated context boundary.",
)
async def dispatch_project_agent_capability(
    project_id: str,
    body: ProjectAgentDispatchRequest,
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    workforce_service: AIWorkforceService = Depends(get_ai_workforce_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    try:
        execution = project_agent_service.dispatch_capability(
            project_id=project_id,
            capability_id=body.capability_id,
            db=db,
            tenant_id=tenant_id,
            task_description=body.task_description,
            custom_query=body.custom_query,
        )
        return AgentRunTriggerResponse(
            execution=workforce_service.format_execution_read(execution),
            message=f"Project Agent successfully coordinated and executed '{body.capability_id}'.",
        )
    except ProjectAgentException as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"Project Agent capability dispatch error: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get(
    "/{project_id}/agent/memory",
    summary="Get Project Agent Memory",
    description="Retrieves the isolated working memory, active priorities, and recent milestones for the Project Agent.",
)
async def get_project_agent_memory(
    project_id: str,
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = project_agent_service.get_or_provision_project_agent(project_id, db)
    return {
        "project_id": project_id,
        "agent_id": agent.id,
        "memory_context": json.loads(agent.memory_context_json) if agent.memory_context_json else {},
        "updated_at": agent.updated_at.isoformat(),
    }


@router.post(
    "/{project_id}/agent/memory",
    summary="Update Project Agent Memory",
    description="Updates notes, priorities, or milestones in the Project Agent's isolated context boundary.",
)
async def update_project_agent_memory(
    project_id: str,
    body: ProjectAgentMemoryUpdate,
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = project_agent_service.update_agent_memory(
        project_id=project_id,
        db=db,
        notes=body.notes,
        priorities=body.priorities,
        milestones=body.milestones,
        memory_updates=body.memory_updates,
    )
    return {
        "ok": True,
        "agent_id": agent.id,
        "memory_context": json.loads(agent.memory_context_json) if agent.memory_context_json else {},
    }


@router.post(
    "/{project_id}/agent/sync-excalidraw",
    response_model=ExcalidrawArtifactRead,
    summary="Project Agent Sync Living Visual Workspace",
    description="The Project Agent synchronizes the project's living Excalidraw visual workspace, rendering decisions, evidence references, requirements, and architecture pipeline nodes.",
)
async def sync_project_agent_excalidraw(
    project_id: str,
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    artifact = project_agent_service.sync_living_excalidraw_workspace(
        project_id=project_id,
        db=db,
        tenant_id=tenant_id,
    )
    return excal_service.format_artifact_read(artifact)


# ==============================================================================
# Project State Endpoints
# ==============================================================================

@router.get(
    "/{project_id}/state",
    response_model=ProjectStateRead,
    summary="Get Authoritative Project State",
    description="Retrieves the current authoritative, evidence-backed Project State.",
)
async def get_project_state(
    project_id: str,
    db: Session = Depends(get_db),
    state_service: ProjectStateService = Depends(get_project_state_service),
    current_user: User = Depends(get_current_user),
):
    state = state_service.get_or_create_state(project_id, db)
    return state_service.format_state_read(state)


@router.get(
    "/{project_id}/state/history",
    response_model=List[ProjectStateVersionRead],
    summary="Get Project State Version History",
    description="Retrieves the immutable version history and audit snapshots for a project.",
)
async def get_project_state_history(
    project_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    versions = (
        db.query(ProjectStateVersion)
        .filter(ProjectStateVersion.project_id == project_id)
        .order_by(ProjectStateVersion.version_number.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    results = []
    for v in versions:
        results.append(
            ProjectStateVersionRead(
                id=v.id,
                project_id=v.project_id,
                version_number=v.version_number,
                snapshot=json.loads(v.snapshot_json),
                reason=v.reason,
                change_summary=json.loads(v.change_summary_json),
                actor_id=v.actor_id,
                created_at=v.created_at,
            )
        )
    return results


# ==============================================================================
# Proposal Approval, Rejection & Rollback Endpoints
# ==============================================================================

@router.get(
    "/{project_id}/state/proposals",
    response_model=List[StateChangeRead],
    summary="List Pending State Proposals",
    description="Lists all state change proposals currently awaiting human review and approval.",
)
async def list_state_proposals(
    project_id: str,
    approval_status: str = Query(ApprovalStatus.PROPOSED.value, description="Filter by status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    changes = (
        db.query(StateChange)
        .filter(
            StateChange.project_id == project_id,
            StateChange.approval_status == approval_status,
        )
        .order_by(StateChange.created_at.desc())
        .all()
    )
    results = []
    for chg in changes:
        val = json.loads(chg.value_json) if chg.value_json else None
        ev_ids = json.loads(chg.evidence_ids_json) if chg.evidence_ids_json else []
        results.append(
            StateChangeRead(
                id=chg.id,
                project_id=chg.project_id,
                candidate_id=chg.candidate_id,
                state_version_before=chg.state_version_before,
                state_version_after=chg.state_version_after,
                operation=chg.operation,
                target_section=chg.target_section,
                value=val,
                reason=chg.reason,
                actor_id=chg.actor_id,
                evidence_ids=ev_ids,
                approval_status=chg.approval_status,
                created_at=chg.created_at,
                resolved_at=chg.resolved_at,
            )
        )
    return results


@router.post(
    "/{project_id}/state/proposals/{proposal_id}/approve",
    response_model=ProjectStateVersionRead,
    summary="Approve Proposed State Change",
    description="Explicitly approves a proposed change, advancing the Authoritative Project State to a new version.",
)
async def approve_proposal(
    project_id: str,
    proposal_id: str,
    body: ProposalApprovalRequest,
    state_service: ProjectStateService = Depends(get_project_state_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        actor = body.actor_id or current_user.id
        version_record = state_service.approve_state_change(
            change_id=proposal_id,
            actor_id=actor,
            db=db,
            note=body.note,
        )
        return ProjectStateVersionRead(
            id=version_record.id,
            project_id=version_record.project_id,
            version_number=version_record.version_number,
            snapshot=json.loads(version_record.snapshot_json),
            reason=version_record.reason,
            change_summary=json.loads(version_record.change_summary_json),
            actor_id=version_record.actor_id,
            created_at=version_record.created_at,
        )
    except ConcurrencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "concurrency_conflict", "message": str(exc)},
        )
    except StateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_transition", "message": str(exc)},
        )


@router.post(
    "/{project_id}/state/proposals/{proposal_id}/reject",
    response_model=StateChangeRead,
    summary="Reject Proposed State Change",
    description="Explicitly rejects a proposed change. Project State remains unmodified.",
)
async def reject_proposal(
    project_id: str,
    proposal_id: str,
    body: ProposalRejectRequest,
    state_service: ProjectStateService = Depends(get_project_state_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        actor = body.actor_id or current_user.id
        change = state_service.reject_state_change(
            change_id=proposal_id,
            actor_id=actor,
            reason=body.reason,
            db=db,
        )
        val = json.loads(change.value_json) if change.value_json else None
        ev_ids = json.loads(change.evidence_ids_json) if change.evidence_ids_json else []
        return StateChangeRead(
            id=change.id,
            project_id=change.project_id,
            candidate_id=change.candidate_id,
            state_version_before=change.state_version_before,
            state_version_after=change.state_version_after,
            operation=change.operation,
            target_section=change.target_section,
            value=val,
            reason=change.reason,
            actor_id=change.actor_id,
            evidence_ids=ev_ids,
            approval_status=change.approval_status,
            created_at=change.created_at,
            resolved_at=change.resolved_at,
        )
    except StateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_transition", "message": str(exc)},
        )


@router.post(
    "/{project_id}/state/rollback",
    response_model=ProjectStateVersionRead,
    summary="Rollback Project State to Previous Version",
    description="Restores Project State to an earlier version, creating a new explicit version snapshot.",
)
async def rollback_project_state(
    project_id: str,
    body: RollbackRequest,
    state_service: ProjectStateService = Depends(get_project_state_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        actor = body.actor_id or current_user.id
        version_record = state_service.rollback_to_version(
            project_id=project_id,
            target_version=body.target_version,
            actor_id=actor,
            reason=body.reason,
            db=db,
        )
        return ProjectStateVersionRead(
            id=version_record.id,
            project_id=version_record.project_id,
            version_number=version_record.version_number,
            snapshot=json.loads(version_record.snapshot_json),
            reason=version_record.reason,
            change_summary=json.loads(version_record.change_summary_json),
            actor_id=version_record.actor_id,
            created_at=version_record.created_at,
        )
    except StateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "rollback_failed", "message": str(exc)},
        )


@router.get(
    "/{project_id}/state/{version}",
    response_model=ProjectStateVersionRead,
    summary="Get Specific Project State Version",
    description="Retrieves a historical snapshot of Project State at a specific version.",
)
async def get_project_state_at_version(
    project_id: str,
    version: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    v = (
        db.query(ProjectStateVersion)
        .filter(
            ProjectStateVersion.project_id == project_id,
            ProjectStateVersion.version_number == version,
        )
        .first()
    )
    if not v:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version} not found for project '{project_id}'.",
        )

    return ProjectStateVersionRead(
        id=v.id,
        project_id=v.project_id,
        version_number=v.version_number,
        snapshot=json.loads(v.snapshot_json),
        reason=v.reason,
        change_summary=json.loads(v.change_summary_json),
        actor_id=v.actor_id,
        created_at=v.created_at,
    )


# ==============================================================================
# Conflict Engine Endpoints (Phase 6)
# ==============================================================================

@router.get(
    "/{project_id}/conflicts",
    response_model=List[ConflictRead],
    summary="List Project Conflicts",
    description="Lists all detected contradictions, workflow conflicts, and decision reversals.",
)
async def list_conflicts(
    project_id: str,
    status: Optional[str] = Query(None, description="Filter by status: open, under_review, approved, rejected, unresolved"),
    conflict_service: ConflictService = Depends(get_conflict_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    conflicts = conflict_service.get_conflicts(
        project_id=project_id,
        db=db,
        tenant_id=tenant_id,
        status=status,
    )
    return [conflict_service.format_conflict_read(c) for c in conflicts]


@router.get(
    "/{project_id}/conflicts/{conflict_id}",
    response_model=ConflictRead,
    summary="Get Conflict Detail",
    description="Retrieves a specific conflict by ID with provenance references.",
)
async def get_conflict(
    project_id: str,
    conflict_id: str,
    conflict_service: ConflictService = Depends(get_conflict_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    try:
        conflict = conflict_service.get_conflict_by_id(conflict_id=conflict_id, db=db, tenant_id=tenant_id)
        if not conflict or conflict.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found.")
        return conflict_service.format_conflict_read(conflict)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/{project_id}/conflicts/{conflict_id}/review",
    response_model=ConflictReviewResponse,
    summary="Human Review Conflict",
    description="Approve, reject, or mark unresolved a project conflict. High impact changes require approval.",
)
async def review_conflict(
    project_id: str,
    conflict_id: str,
    body: ConflictReviewRequest,
    conflict_service: ConflictService = Depends(get_conflict_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    actor = body.actor_id or current_user.id

    try:
        if body.action == "approve":
            res = conflict_service.approve_conflict(
                conflict_id=conflict_id,
                actor_id=actor,
                db=db,
                tenant_id=tenant_id,
                note=body.note,
            )
            return ConflictReviewResponse(
                conflict=conflict_service.format_conflict_read(res["conflict"]),
                message=res["message"],
                project_state_version=res["new_version"],
            )

        elif body.action == "reject":
            rejected_conflict = conflict_service.reject_conflict(
                conflict_id=conflict_id,
                actor_id=actor,
                reason=body.reason or "Rejected by human reviewer",
                db=db,
                tenant_id=tenant_id,
            )
            return ConflictReviewResponse(
                conflict=conflict_service.format_conflict_read(rejected_conflict),
                message="Conflict rejected. Authoritative state remains unchanged.",
                project_state_version=None,
            )

        elif body.action == "mark_unresolved":
            unresolved_conflict = conflict_service.mark_unresolved(
                conflict_id=conflict_id,
                actor_id=actor,
                db=db,
                tenant_id=tenant_id,
                note=body.note,
            )
            return ConflictReviewResponse(
                conflict=conflict_service.format_conflict_read(unresolved_conflict),
                message="Conflict marked unresolved. Preserved for future team discussion.",
                project_state_version=None,
            )
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid action '{body.action}'.")

    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except StaleProposalError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (StateTransitionError, ConcurrencyError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ==============================================================================
# Evidence & Candidate Knowledge Endpoints
# ==============================================================================

@router.get(
    "/{project_id}/evidence",
    response_model=List[EvidenceRead],
    summary="List Evidence Records",
    description="Lists all immutable evidence fragments supporting project knowledge for this project.",
)
async def list_project_evidence(
    project_id: str,
    source: Optional[str] = Query(None, description="Filter by source, e.g. google_meet"),
    meeting_id: Optional[str] = Query(None, description="Filter by meeting ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Evidence).filter(Evidence.project_id == project_id)
    if source:
        query = query.filter(Evidence.source == source)
    if meeting_id:
        query = query.filter(Evidence.meeting_id == meeting_id)

    records = query.order_by(Evidence.occurred_at.desc()).offset(offset).limit(limit).all()
    return [EvidenceRead.model_validate(e) for e in records]


@router.get(
    "/{project_id}/intelligence/candidates",
    response_model=List[CandidateKnowledgeRead],
    include_in_schema=False,
)
@router.get(
    "/{project_id}/knowledge",
    response_model=List[CandidateKnowledgeRead],
    summary="List Candidate Knowledge",
    description="Lists extracted candidate knowledge items (Proposals, Decisions, Requirements, Questions).",
)
async def list_candidate_knowledge(
    project_id: str,
    category: Optional[str] = Query(None, description="Filter by category: proposal, decision_candidate, etc."),
    candidate_status: Optional[str] = Query(None, alias="status", description="candidate, proposed, approved, rejected"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(CandidateKnowledge).filter(CandidateKnowledge.project_id == project_id)
    if category:
        query = query.filter(CandidateKnowledge.category == category)
    if candidate_status:
        query = query.filter(CandidateKnowledge.status == candidate_status)

    candidates = query.order_by(CandidateKnowledge.created_at.desc()).offset(offset).limit(limit).all()
    results = []
    for c in candidates:
        ev_ids = json.loads(c.evidence_ids_json) if c.evidence_ids_json else []
        results.append(
            CandidateKnowledgeRead(
                id=c.id,
                project_id=c.project_id,
                meeting_id=c.meeting_id,
                category=c.category,
                classification=c.classification,
                title=c.title,
                content=c.content,
                confidence=c.confidence,
                evidence_ids=ev_ids,
                status=c.status,
                agent_run_id=c.agent_run_id,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )
    return results


@router.get(
    "/{project_id}/meetings/{meeting_id}/intelligence",
    summary="Get Meeting Intelligence & Agent Runs",
    description="Retrieves candidate knowledge and agent runs extracted for a specific meeting.",
)
async def get_meeting_intelligence(
    project_id: str,
    meeting_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidates = (
        db.query(CandidateKnowledge)
        .filter(CandidateKnowledge.project_id == project_id, CandidateKnowledge.meeting_id == meeting_id)
        .all()
    )
    agent_runs = (
        db.query(AgentRun)
        .filter(AgentRun.project_id == project_id, AgentRun.meeting_id == meeting_id)
        .all()
    )

    return {
        "project_id": project_id,
        "meeting_id": meeting_id,
        "total_candidates": len(candidates),
        "candidates": [
            {
                "id": c.id,
                "category": c.category,
                "classification": c.classification,
                "title": c.title,
                "content": c.content,
                "confidence": c.confidence,
                "evidence_ids": json.loads(c.evidence_ids_json),
                "status": c.status,
            }
            for c in candidates
        ],
        "agent_runs": [
            {
                "agent_run_id": r.agent_run_id,
                "model": r.model,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat(),
            }
            for r in agent_runs
        ],
    }


# ==============================================================================
# Pipeline Trigger Endpoint
# ==============================================================================

@router.post(
    "/{project_id}/meetings/{meeting_id}/process",
    response_model=PipelineExecutionResult,
    summary="Process Meeting Knowledge Pipeline",
    description="Ingests meeting transcript entries, creates evidence, extracts candidate knowledge, and creates proposals.",
)
async def process_meeting_pipeline(
    project_id: str,
    meeting_id: str,
    coordinator: PipelineCoordinator = Depends(get_pipeline_coordinator),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = coordinator.process_meeting(
            meeting_id=meeting_id,
            project_id=project_id,
            db=db,
            actor_id=current_user.id,
        )
        return result
    except Exception as exc:
        logger.error(f"Pipeline error for meeting '{meeting_id}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Pipeline processing failed: {str(exc)}",
        )


# ==============================================================================
# AI Workforce Endpoints (Phase 8)
# ==============================================================================

@router.get(
    "/{project_id}/agents",
    response_model=List[AgentDefinitionRead],
    summary="List AI Workforce Agents",
    description="Lists all 5 workforce agents (BA, Project, Functional, Tech, Frappe) and their status.",
)
async def list_workforce_agents(
    project_id: str,
    workforce_service: AIWorkforceService = Depends(get_ai_workforce_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    return workforce_service.list_agents(project_id=project_id, db=db, tenant_id=tenant_id)


@router.post(
    "/{project_id}/agents/{agent_id}/run",
    response_model=AgentRunTriggerResponse,
    summary="Trigger Agent Run",
    description="Executes a specific workforce agent against current authoritative Project State.",
)
async def trigger_agent_run(
    project_id: str,
    agent_id: str,
    body: AgentRunTriggerRequest,
    workforce_service: AIWorkforceService = Depends(get_ai_workforce_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    try:
        execution = workforce_service.run_agent(
            agent_id=agent_id,
            project_id=project_id,
            db=db,
            tenant_id=tenant_id,
            task_description=body.task_description,
            custom_query=body.custom_context_query,
        )
        return AgentRunTriggerResponse(
            execution=workforce_service.format_execution_read(execution),
            message=f"Agent '{agent_id}' completed execution successfully.",
        )
    except AgentPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except AgentOutputValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.error(f"Agent execution error: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Agent run failed: {str(exc)}")


@router.get(
    "/{project_id}/agents/{agent_id}/runs",
    response_model=List[AgentExecutionRead],
    summary="List Agent Executions",
    description="Retrieves audit run history for an agent.",
)
async def list_agent_runs(
    project_id: str,
    agent_id: str,
    limit: int = Query(20, ge=1, le=50),
    workforce_service: AIWorkforceService = Depends(get_ai_workforce_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    runs = (
        db.query(AgentExecution)
        .filter(
            AgentExecution.project_id == project_id,
            AgentExecution.tenant_id == tenant_id,
            AgentExecution.agent_id == agent_id,
        )
        .order_by(AgentExecution.created_at.desc())
        .limit(limit)
        .all()
    )
    return [workforce_service.format_execution_read(r) for r in runs]


@router.get(
    "/{project_id}/agents/coordinator-briefing",
    summary="Get Project Agent Coordinator Briefing",
    description="Retrieves the holistic coordinator briefing from the logical Project Agent, summarizing state version and 5 specialist agent statuses.",
)
async def get_coordinator_briefing(
    project_id: str,
    workforce_service: AIWorkforceService = Depends(get_ai_workforce_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    return workforce_service.get_project_coordinator_briefing(
        project_id=project_id,
        db=db,
        tenant_id=tenant_id,
    )


# ==============================================================================
# Excalidraw Visual Architecture Endpoints
# ==============================================================================

@router.get(
    "/{project_id}/excalidraw",
    response_model=ExcalidrawArtifactRead,
    summary="Get Excalidraw Architecture Artifact",
    description="Retrieves the current authoritative visual architecture diagram artifact for a project.",
)
async def get_excalidraw_artifact(
    project_id: str,
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    artifact = excal_service.get_or_create_artifact(
        project_id=project_id,
        db=db,
        tenant_id=tenant_id,
    )
    return excal_service.format_artifact_read(artifact)


@router.post(
    "/{project_id}/excalidraw/ingest",
    response_model=ExcalidrawArtifactRead,
    summary="Ingest Excalidraw Scene (Role A - Input)",
    description="Ingests visual diagram elements as authoritative architectural evidence. Emits a SourceEvent and Evidence record.",
)
async def ingest_excalidraw_diagram(
    project_id: str,
    body: ExcalidrawIngestRequest,
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    artifact, evidence = excal_service.ingest_diagram(
        project_id=project_id,
        req=body,
        db=db,
        tenant_id=tenant_id,
    )
    return excal_service.format_artifact_read(artifact)


@router.get(
    "/{project_id}/excalidraw/proposals",
    response_model=List[ExcalidrawProposalRead],
    summary="List Excalidraw Proposals",
    description="Lists visual architecture modification proposals and their diff previews.",
)
async def list_excalidraw_proposals(
    project_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    proposals = excal_service.list_proposals(
        project_id=project_id,
        db=db,
        tenant_id=tenant_id,
        status=status_filter,
    )
    return [excal_service.format_proposal_read(p) for p in proposals]


@router.post(
    "/{project_id}/excalidraw/proposals/generate",
    response_model=ExcalidrawProposalRead,
    summary="Generate Excalidraw Change Proposal (Role B - Output)",
    description="Derives a proposed visual architecture modification with structured diff preview from an approved Project State.",
)
async def generate_excalidraw_proposal(
    project_id: str,
    state_version: Optional[int] = Query(None, description="State version to derive diagram from"),
    reason: Optional[str] = Query(None, description="Optional justification"),
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    state_service: ProjectStateService = Depends(get_project_state_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    state = state_service.get_or_create_state(project_id, db)
    target_version = state_version or state.current_version

    proposal = excal_service.generate_proposal_from_state(
        project_id=project_id,
        state_version=target_version,
        db=db,
        tenant_id=tenant_id,
        reason=reason,
    )
    return excal_service.format_proposal_read(proposal)


@router.post(
    "/{project_id}/excalidraw/ai-generate",
    summary="AI Visual Architecture Generator (Excalidraw)",
    description="Synthesizes an intelligent, multi-tier system architecture diagram with DeepSeek AI, Living Decisions, and Core Services.",
)
async def ai_generate_excalidraw_diagram(
    project_id: str,
    body: Optional[AiGenerateDiagramRequest] = None,
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    focus = body.focus_prompt if body else None
    direct = body.direct_apply if body else False

    proposal, artifact = excal_service.generate_ai_visual_architecture(
        project_id=project_id,
        db=db,
        tenant_id=tenant_id,
        focus_prompt=focus,
        direct_apply=direct,
        actor_id=current_user.id,
    )
    return {
        "proposal": excal_service.format_proposal_read(proposal),
        "artifact": excal_service.format_artifact_read(artifact) if artifact else None,
        "direct_applied": direct,
        "message": "AI Visual Architecture diagram generated successfully for Excalidraw.",
    }




@router.get(
    "/{project_id}/excalidraw/revisions",
    response_model=List[ExcalidrawRevisionRead],
    summary="List Excalidraw Visual Revisions",
)
async def list_excalidraw_revisions(
    project_id: str,
    limit: int = Query(50, ge=1, le=100),
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    revisions = excal_service.list_revisions(project_id, db, tenant_id=tenant_id, limit=limit)
    return [excal_service.format_revision_read(r) for r in revisions]


@router.get(
    "/{project_id}/excalidraw/revisions/{revision_number}",
    response_model=ExcalidrawRevisionRead,
    summary="Get Excalidraw Visual Revision",
)
async def get_excalidraw_revision(
    project_id: str,
    revision_number: int,
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    revision = excal_service.get_revision(project_id, revision_number, db, tenant_id=tenant_id)
    return excal_service.format_revision_read(revision)


@router.get(
    "/{project_id}/excalidraw/compare",
    response_model=ExcalidrawRevisionDiffRead,
    summary="Compare Excalidraw Visual Revisions",
)
async def compare_excalidraw_revisions(
    project_id: str,
    from_revision: int = Query(..., ge=1),
    to_revision: int = Query(..., ge=1),
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    return excal_service.compare_revisions(
        project_id,
        from_revision,
        to_revision,
        db,
        tenant_id=tenant_id,
    )


@router.get(
    "/{project_id}/unknown-context",
    summary="List Unknown Context Items",
)
async def list_unknown_context(
    project_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if project_id != UNKNOWN_CONTEXT_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown Context is a system-managed project.")
    records = (
        db.query(Evidence)
        .filter(Evidence.project_id == UNKNOWN_CONTEXT_ID)
        .order_by(Evidence.created_at.desc())
        .limit(limit)
        .all()
    )
    results = []
    for ev in records:
        metadata = json.loads(ev.metadata_json or "{}")
        results.append({
            "evidence_id": ev.id,
            "source": ev.source,
            "content": ev.content,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
            "context_status": metadata.get("context_status", "unknown"),
            "context_candidates": metadata.get("context_candidates", []),
            "reasoning": metadata.get("reasoning"),
        })
    return results


@router.post(
    "/{project_id}/unknown-context/{evidence_id}/assign",
    summary="Assign Unknown Context Evidence to Project",
)
async def assign_unknown_context_evidence(
    project_id: str,
    evidence_id: str,
    target_project_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if project_id != UNKNOWN_CONTEXT_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown Context is a system-managed project.")
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    service = ContextResolverService()
    try:
        return service.move_unknown_evidence_to_project(
            evidence_id=evidence_id,
            target_project_id=target_project_id,
            db=db,
            actor_id=current_user.id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/{project_id}/excalidraw/proposals/{proposal_id}/review",
    summary="Review Excalidraw Proposal (Human Gate)",
    description="Human review gate: Approves or rejects a visual architecture change proposal. Strictly enforces Output Safety.",
)
async def review_excalidraw_proposal(
    project_id: str,
    proposal_id: str,
    body: ExcalidrawProposalReviewRequest,
    excal_service: ExcalidrawService = Depends(get_excalidraw_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", "default_tenant")
    try:
        proposal, artifact = excal_service.review_proposal(
            proposal_id=proposal_id,
            action=body.action,
            actor_id=current_user.id,
            db=db,
            tenant_id=tenant_id,
            reason=body.reason,
        )
        return {
            "proposal": excal_service.format_proposal_read(proposal),
            "artifact": excal_service.format_artifact_read(artifact) if artifact else None,
            "message": f"Proposal '{proposal_id}' was successfully {proposal.status}.",
        }
    except ExcalidrawError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"Proposal review failed: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Review failed: {str(exc)}")


# ==============================================================================
# Central Workspace Super-Agent Endpoints (One Central Agent Handling All Projects)
# ==============================================================================

workspace_router = APIRouter(tags=["Workspace Central Agent"])


@workspace_router.get(
    "/workspace/agent",
    response_model=WorkspaceAgentRead,
    summary="Get Central Workspace Agent",
    description="Retrieves the single central Workspace Agent that handles and oversees all projects across the organization.",
)
async def get_default_workspace_agent(
    workspace_id: str = Query("ws_default", description="Workspace ID"),
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = project_agent_service.get_or_provision_workspace_agent(workspace_id=workspace_id, db=db)
    return project_agent_service.format_workspace_agent_read(agent, db)


@workspace_router.get(
    "/workspaces/{workspace_id}/agent",
    response_model=WorkspaceAgentRead,
    summary="Get Workspace Central Agent by ID",
    description="Retrieves the central Workspace Agent for a specific workspace.",
)
async def get_workspace_agent_by_id(
    workspace_id: str,
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = project_agent_service.get_or_provision_workspace_agent(workspace_id=workspace_id, db=db)
    return project_agent_service.format_workspace_agent_read(agent, db)


@workspace_router.post(
    "/workspace/agent/dispatch",
    summary="Dispatch Capability via Central Workspace Agent",
    description="Dispatches a specialist capability coordinated by the central Workspace Agent, with optional project target focus.",
)
async def dispatch_workspace_agent_capability(
    body: WorkspaceAgentDispatchRequest,
    workspace_id: str = Query("ws_default", description="Workspace ID"),
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    execution = project_agent_service.dispatch_workspace_capability(
        workspace_id=workspace_id,
        capability_id=body.capability_id,
        project_id=body.project_id,
        task_description=body.task_description,
        custom_query=body.custom_query,
        db=db,
    )
    return {
        "status": "success",
        "message": f"Central Workspace Agent coordinated execution of '{body.capability_id}'",
        "execution": AgentExecutionRead.model_validate(execution),
    }


@workspace_router.post(
    "/workspace/agent/memory",
    summary="Update Central Workspace Agent Portfolio Memory",
    description="Updates portfolio memory context and cross-project priorities for the central Workspace Agent.",
)
async def update_workspace_agent_memory(
    body: WorkspaceAgentMemoryUpdate,
    workspace_id: str = Query("ws_default", description="Workspace ID"),
    project_agent_service: ProjectAgentService = Depends(get_project_agent_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = project_agent_service.update_workspace_agent_memory(
        workspace_id=workspace_id,
        priorities=body.priorities,
        milestones=body.milestones,
        insights=body.insights,
        memory_updates=body.memory_updates,
        db=db,
    )
    return json.loads(agent.memory_context_json) if agent.memory_context_json else {}



