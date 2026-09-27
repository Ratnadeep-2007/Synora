from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.exceptions import SynesisException
from app.models.agent_workforce import AgentExecution, AgentOutputType
from app.models.excalidraw import ExcalidrawArtifact
from app.models.project import Project, ProjectAgent, Workspace, WorkspaceAgent
from app.models.project_state import ProjectState
from app.schemas.project_agent import ProjectAgentRead, SpecialistCapabilityRead, WorkspaceAgentRead
from app.services.ai_workforce import AIWorkforceService
from app.services.excalidraw_service import ExcalidrawService
from app.services.project_state_service import ProjectStateService

logger = logging.getLogger(__name__)


class ProjectAgentException(SynesisException):
    """Base exception for Project Agent operations."""
    pass


class ProjectAgentService:
    """
    Project Agent Service implementing:
    ONE PROJECT = ONE LOGICAL PROJECT AGENT.

    Responsibilities:
    1. Automatic provisioning of Project Agent when a project is created or accessed.
    2. Logical isolation: each agent has its own project_id, memory context, state,
       permissions, connected tools, and Excalidraw living workspace.
    3. Coordination of specialist capabilities (BA, Planning, Functional, Tech, Frappe).
    4. Continuous synchronization of the project's living Excalidraw workspace.
    """

    DEFAULT_CAPABILITIES = [
        "ba_agent",
        "project_planner_agent",
        "functional_agent",
        "tech_agent",
        "frappe_agent",
    ]

    #: Canonical source/provider IDs selectable during project creation.
    #: google_meet and excalidraw are platform sources; whatsapp maps to the
    #: existing WhatsApp/Baileys connector (provider_name "whatsapp").
    PROJECT_SOURCE_IDS = ("google_meet", "whatsapp", "excalidraw")

    DEFAULT_TOOLS = [
        "google_meet",
        "whatsapp",
        "excalidraw",
    ]

    def __init__(
        self,
        state_service: Optional[ProjectStateService] = None,
        workforce_service: Optional[AIWorkforceService] = None,
        excal_service: Optional[ExcalidrawService] = None,
    ):
        self.state_service = state_service or ProjectStateService()
        self.workforce_service = workforce_service or AIWorkforceService(state_service=self.state_service)
        self.excal_service = excal_service or ExcalidrawService()

    def get_or_create_workspace(
        self,
        workspace_id: str,
        db: Session,
        name: str = "Default Workspace",
    ) -> Workspace:
        """Ensures the parent organizational workspace exists."""
        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if not ws:
            ws = Workspace(
                id=workspace_id,
                name=name,
                description="Primary workspace container for Synesis projects.",
            )
            db.add(ws)
            db.commit()
            db.refresh(ws)
            logger.info(f"Created Workspace '{workspace_id}'")
        return ws

    def get_or_create_project(
        self,
        project_id: str,
        db: Session,
        workspace_id: str = "ws_default",
        name: Optional[str] = None,
        description: str = "",
        sources: Optional[List[str]] = None,
    ) -> Project:
        """Retrieves or creates a Project, guaranteeing Project Agent provisioning."""
        self.get_or_create_workspace(workspace_id, db)

        proj = db.query(Project).filter(Project.id == project_id).first()
        if not proj:
            project_name = name or f"Project {project_id}"
            proj = Project(
                id=project_id,
                workspace_id=workspace_id,
                name=project_name,
                description=description,
            )
            db.add(proj)
            db.commit()
            db.refresh(proj)
            logger.info(f"Created Project '{project_id}' in workspace '{workspace_id}'")

        # Auto-provision Project Agent if missing
        self.get_or_provision_project_agent(
            project_id=project_id, db=db, workspace_id=workspace_id, sources=sources
        )
        return proj

    @classmethod
    def validate_sources(cls, sources: Optional[List[str]]) -> List[str]:
        """Validate and normalize project source selections.

        Unknown provider IDs raise ValueError; duplicates are removed while
        preserving order. ``whatsapp`` is the canonical ID for the existing
        WhatsApp/Baileys connector — no new connector is created here.
        """
        if sources is None:
            return list(cls.DEFAULT_TOOLS)
        validated: List[str] = []
        for source in sources:
            normalized = (source or "").strip().lower()
            if not normalized:
                continue
            if normalized not in cls.PROJECT_SOURCE_IDS:
                raise ValueError(
                    f"Unknown project source '{source}'. "
                    f"Allowed sources: {', '.join(cls.PROJECT_SOURCE_IDS)}."
                )
            if normalized not in validated:
                validated.append(normalized)
        return validated

    def get_or_provision_project_agent(
        self,
        project_id: str,
        db: Session,
        workspace_id: str = "ws_default",
        name: Optional[str] = None,
        sources: Optional[List[str]] = None,
    ) -> ProjectAgent:
        """
        Auto-provisions the dedicated logical Project Agent for a project.
        Enforces 1:1 relationship between Project and Project Agent.
        """
        agent = db.query(ProjectAgent).filter(ProjectAgent.project_id == project_id).first()
        connected_tools = self.validate_sources(sources) if sources is not None else list(self.DEFAULT_TOOLS)
        if agent:
            # Keep the stored tool set aligned with the validated selection so
            # the creation selector is honored even on re-provisioning paths.
            agent.connected_tools_json = json.dumps(connected_tools)
            db.commit()
            db.refresh(agent)
            return agent
        if not agent:
            # 1. Ensure Project record exists
            proj = db.query(Project).filter(Project.id == project_id).first()
            if not proj:
                proj_name = name or f"Project {project_id}"
                self.get_or_create_workspace(workspace_id, db)
                proj = Project(id=project_id, workspace_id=workspace_id, name=proj_name)
                db.add(proj)
                db.commit()
                db.refresh(proj)

            # 2. Ensure Project State exists
            state = self.state_service.get_or_create_state(project_id, db)

            # 3. Ensure Excalidraw living workspace artifact exists
            excal_artifact = self.excal_service.get_or_create_artifact(
                project_id=project_id,
                db=db,
                name=f"{proj.name} Living Architecture Canvas",
            )

            agent_name = f"{proj.name} Project Agent"
            agent = ProjectAgent(
                project_id=project_id,
                workspace_id=proj.workspace_id,
                name=agent_name,
                identity_json=json.dumps({
                    "role": "Project Intelligence Coordinator",
                    "persona": "Central intelligence entity responsible for project state alignment, context brokering, and specialist capability coordination.",
                    "prompt_version": "v2.0-coordinator",
                }),
                memory_context_json=json.dumps({
                    "key_decisions_summary": [],
                    "active_priorities": [
                        "Maintain evidence-backed authoritative Project State",
                        "Coordinate specialist capabilities (BA, Planning, Functional, Tech, Frappe)",
                        "Keep living Excalidraw workspace synchronized with decisions",
                    ],
                    "recent_milestones": ["Project Agent provisioned and workspace linked"],
                    "context_notes": f"Initialized isolated context boundary for project '{project_id}'.",
                }),
                capabilities_json=json.dumps(self.DEFAULT_CAPABILITIES),
                connected_tools_json=json.dumps(connected_tools),
                excalidraw_workspace_id=excal_artifact.id,
                status="active",
            )
            db.add(agent)
            db.commit()
            db.refresh(agent)
            logger.info(f"Auto-provisioned ProjectAgent '{agent.id}' for project '{project_id}'")

        return agent

    def dispatch_capability(
        self,
        project_id: str,
        capability_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
        task_description: Optional[str] = None,
        custom_query: Optional[str] = None,
    ) -> AgentExecution:
        """
        Coordinates specialist capability execution through the Project Agent.
        The Project Agent enforces context boundaries and logs execution lineage.
        """
        agent = self.get_or_provision_project_agent(project_id, db)
        allowed_capabilities = json.loads(agent.capabilities_json) if agent.capabilities_json else []

        alias_map = {
            "ba_specialist": "ba_agent",
            "planning_specialist": "project_planner_agent",
            "functional_specialist": "functional_agent",
            "tech_specialist": "tech_agent",
            "frappe_specialist": "frappe_agent",
        }
        target_capability = alias_map.get(capability_id, capability_id)

        if target_capability not in allowed_capabilities and capability_id not in allowed_capabilities:
            raise ProjectAgentException(
                f"Capability '{capability_id}' is not configured for Project Agent '{agent.id}'."
            )

        # Update Project Agent status
        agent.status = "coordinating"
        db.commit()

        try:
            # Delegate to specialist capability via workforce service
            execution = self.workforce_service.run_agent(
                agent_id=target_capability,
                project_id=project_id,
                db=db,
                tenant_id=tenant_id,
                task_description=task_description,
                custom_query=custom_query,
            )

            # Update Project Agent working memory with execution summary
            self._update_memory_on_execution(agent=agent, execution=execution, db=db)

            agent.status = "active"
            db.commit()
            return execution

        except Exception as exc:
            agent.status = "active"
            db.commit()
            raise

    def _update_memory_on_execution(
        self,
        agent: ProjectAgent,
        execution: AgentExecution,
        db: Session,
    ) -> None:
        """Records recent execution outcome into Project Agent memory context."""
        try:
            mem = json.loads(agent.memory_context_json) if agent.memory_context_json else {}
            milestones = mem.get("recent_milestones", [])
            output_payload = json.loads(execution.output_payload_json) if execution.output_payload_json else {}
            summary = output_payload.get("summary", f"Executed {execution.agent_id} ({execution.output_type})")

            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            milestones.insert(0, f"[{timestamp}] {execution.agent_id}: {summary}")
            mem["recent_milestones"] = milestones[:8]  # Keep 8 most recent milestones

            agent.memory_context_json = json.dumps(mem)
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to update Project Agent memory: {e}")

    def update_agent_memory(
        self,
        project_id: str,
        db: Session,
        notes: Optional[str] = None,
        priorities: Optional[List[str]] = None,
        milestones: Optional[List[str]] = None,
        memory_updates: Optional[Dict[str, Any]] = None,
    ) -> ProjectAgent:
        """Manually updates the Project Agent's working memory context."""
        agent = self.get_or_provision_project_agent(project_id, db)
        mem = json.loads(agent.memory_context_json) if agent.memory_context_json else {}

        if notes is not None:
            mem["context_notes"] = notes
        if priorities is not None:
            mem["active_priorities"] = priorities
        if milestones is not None:
            mem["recent_milestones"] = milestones
        if memory_updates:
            mem.update(memory_updates)

        agent.memory_context_json = json.dumps(mem)
        agent.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(agent)
        return agent

    def sync_living_excalidraw_workspace(
        self,
        project_id: str,
        db: Session,
        tenant_id: str = "default_tenant",
    ) -> ExcalidrawArtifact:
        """
        Maintains compatibility with older callers without rebuilding the canvas
        from the removed agent_workflow model. Visual regeneration is delegated to
        the Excalidraw service's canonical project-state renderer.
        """
        state = self.state_service.get_or_create_state(project_id, db)
        artifact = self.excal_service.get_or_create_artifact(
            project_id=project_id,
            db=db,
            tenant_id=tenant_id,
        )
        return artifact

    def format_project_agent_read(self, agent: ProjectAgent, db: Session) -> ProjectAgentRead:
        """Formats the ProjectAgent domain model into a typed read DTO."""
        state = self.state_service.get_or_create_state(agent.project_id, db)
        identity = json.loads(agent.identity_json) if agent.identity_json else {}
        memory = json.loads(agent.memory_context_json) if agent.memory_context_json else {}
        capabilities_list = json.loads(agent.capabilities_json) if agent.capabilities_json else []
        tools_list = json.loads(agent.connected_tools_json) if agent.connected_tools_json else []

        # Get latest run info for each capability
        capabilities_dto: List[SpecialistCapabilityRead] = []
        for cap_id in capabilities_list:
            meta = self.workforce_service.AGENT_DEFINITIONS.get(cap_id, {
                "name": cap_id.replace("_", " ").title(),
                "role": "Specialist",
                "description": "",
                "capabilities": [],
            })

            last_run = (
                db.query(AgentExecution)
                .filter(
                    AgentExecution.project_id == agent.project_id,
                    AgentExecution.agent_id == cap_id,
                )
                .order_by(AgentExecution.created_at.desc())
                .first()
            )

            status = "ready"
            current_task = None
            last_run_at = None
            if last_run:
                status = "ready" if last_run.status == "completed" else last_run.status
                last_run_at = last_run.created_at
                payload = json.loads(last_run.output_payload_json) if last_run.output_payload_json else {}
                current_task = payload.get("summary")

            capabilities_dto.append(
                SpecialistCapabilityRead(
                    id=cap_id,
                    name=meta["name"],
                    role=meta["role"],
                    description=meta["description"],
                    capabilities=meta["capabilities"],
                    status=status,
                    last_run_at=last_run_at,
                    current_task=current_task,
                )
            )

        return ProjectAgentRead(
            id=agent.id,
            project_id=agent.project_id,
            workspace_id=agent.workspace_id,
            name=agent.name,
            status=agent.status,
            role=identity.get("role", "Project Intelligence Coordinator"),
            identity=identity,
            memory_context=memory,
            capabilities=capabilities_dto,
            connected_tools=tools_list,
            excalidraw_workspace_id=agent.excalidraw_workspace_id,
            current_project_state_version=state.current_version,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    # ==============================================================================
    # Central Workspace Super-Agent Methods (One Central Agent Handling All Projects)
    # ==============================================================================

    def get_or_provision_workspace_agent(
        self,
        workspace_id: str = "ws_default",
        db: Session = None,
        name: Optional[str] = None,
    ) -> WorkspaceAgent:
        """
        Auto-provisions the central Workspace Agent for the workspace.
        This agent handles and oversees all projects across the organization.
        """
        self.get_or_create_workspace(workspace_id, db)
        agent = db.query(WorkspaceAgent).filter(WorkspaceAgent.workspace_id == workspace_id).first()
        if not agent:
            ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
            agent_name = name or (f"{ws.name} Central Agent" if ws else "Synesis Central Workspace Agent")
            agent = WorkspaceAgent(
                workspace_id=workspace_id,
                name=agent_name,
                identity_json=json.dumps({
                    "role": "Central Workspace Intelligence Coordinator",
                    "persona": "Omniscient portfolio architect managing all organizational projects, aligning cross-project dependencies, and coordinating specialist capabilities.",
                    "prompt_version": "v3.0-workspace-central",
                }),
                memory_context_json=json.dumps({
                    "portfolio_priorities": [
                        "Maintain cross-project coherence and governance",
                        "Ensure individual Project States stay synchronized with evidence",
                        "Maintain living visual Excalidraw workspaces for each project",
                    ],
                    "recent_milestones": ["Central Workspace Agent initialized to oversee all projects"],
                    "cross_project_insights": [],
                }),
                capabilities_json=json.dumps(self.DEFAULT_CAPABILITIES),
                connected_tools_json=json.dumps(self.DEFAULT_TOOLS),
                status="active",
            )
            db.add(agent)
            db.commit()
            db.refresh(agent)
            logger.info(f"Auto-provisioned central WorkspaceAgent '{agent.id}' for workspace '{workspace_id}'")
        return agent

    def format_workspace_agent_read(self, agent: WorkspaceAgent, db: Session) -> WorkspaceAgentRead:
        """Formats the central WorkspaceAgent into a typed read DTO with managed projects portfolio."""
        identity = json.loads(agent.identity_json) if agent.identity_json else {}
        memory = json.loads(agent.memory_context_json) if agent.memory_context_json else {}
        capabilities_list = json.loads(agent.capabilities_json) if agent.capabilities_json else []
        tools_list = json.loads(agent.connected_tools_json) if agent.connected_tools_json else []

        # List all projects in this workspace
        projects = db.query(Project).filter(Project.workspace_id == agent.workspace_id).all()
        managed_projects = []
        for p in projects:
            p_state = self.state_service.get_or_create_state(p.id, db)
            managed_projects.append({
                "id": p.id,
                "name": p.name,
                "current_state_version": p_state.current_version if p_state else 1,
                "description": p.description,
            })

        capabilities_dto: List[SpecialistCapabilityRead] = []
        for cap_id in capabilities_list:
            meta = self.workforce_service.AGENT_DEFINITIONS.get(cap_id, {
                "name": cap_id.replace("_", " ").title(),
                "role": "Specialist",
                "description": "",
                "capabilities": [],
            })
            # Find most recent execution across any project in workspace
            last_run = (
                db.query(AgentExecution)
                .filter(AgentExecution.agent_id == cap_id)
                .order_by(AgentExecution.created_at.desc())
                .first()
            )
            status = "ready"
            current_task = None
            last_run_at = None
            if last_run:
                status = "ready" if last_run.status == "completed" else last_run.status
                last_run_at = last_run.created_at
                payload = json.loads(last_run.output_payload_json) if last_run.output_payload_json else {}
                current_task = payload.get("summary") or getattr(last_run, "output_type", None)

            capabilities_dto.append(
                SpecialistCapabilityRead(
                    id=cap_id,
                    name=meta["name"],
                    role=meta["role"],
                    description=meta["description"],
                    capabilities=meta.get("capabilities", []),
                    status=status,
                    last_run_at=last_run_at,
                    current_task=current_task,
                )
            )

        return WorkspaceAgentRead(
            id=agent.id,
            workspace_id=agent.workspace_id,
            name=agent.name,
            status=agent.status,
            role=identity.get("role", "Central Workspace Intelligence Coordinator"),
            identity=identity,
            memory_context=memory,
            capabilities=capabilities_dto,
            connected_tools=tools_list,
            projects_count=len(projects),
            managed_projects=managed_projects,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    def dispatch_workspace_capability(
        self,
        workspace_id: str,
        capability_id: str,
        db: Session,
        project_id: Optional[str] = None,
        task_description: Optional[str] = None,
        custom_query: Optional[str] = None,
        tenant_id: str = "default_tenant",
    ) -> AgentExecution:
        """Dispatches a specialist capability coordinated by the central Workspace Agent."""
        agent = self.get_or_provision_workspace_agent(workspace_id=workspace_id, db=db)

        # If project_id is provided, execute within that project context; otherwise pick first project or default
        target_project_id = project_id
        if not target_project_id:
            first_proj = db.query(Project).filter(Project.workspace_id == workspace_id).first()
            target_project_id = first_proj.id if first_proj else "proj_default"

        # Execute specialist capability
        execution = self.dispatch_capability(
            project_id=target_project_id,
            capability_id=capability_id,
            db=db,
            task_description=task_description,
            custom_query=custom_query,
            tenant_id=tenant_id,
        )

        # Record into central Workspace Agent portfolio memory
        try:
            mem = json.loads(agent.memory_context_json) if agent.memory_context_json else {}
            milestones = mem.get("recent_milestones", [])
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            milestones.insert(0, f"[{timestamp}] [{target_project_id}] {execution.agent_id}: {execution.output_type}")
            mem["recent_milestones"] = milestones[:12]
            agent.memory_context_json = json.dumps(mem)
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to update Workspace Agent memory: {e}")

        return execution

    def update_workspace_agent_memory(
        self,
        workspace_id: str,
        db: Session,
        priorities: Optional[List[str]] = None,
        milestones: Optional[List[str]] = None,
        insights: Optional[List[str]] = None,
        memory_updates: Optional[Dict[str, Any]] = None,
    ) -> WorkspaceAgent:
        """Updates portfolio memory context for the central Workspace Agent."""
        agent = self.get_or_provision_workspace_agent(workspace_id=workspace_id, db=db)
        mem = json.loads(agent.memory_context_json) if agent.memory_context_json else {}
        if priorities is not None:
            mem["portfolio_priorities"] = priorities
        if milestones is not None:
            mem["recent_milestones"] = milestones
        if insights is not None:
            mem["cross_project_insights"] = insights
        if memory_updates:
            mem.update(memory_updates)
        agent.memory_context_json = json.dumps(mem)
        agent.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(agent)
        return agent
