from datetime import datetime, timezone
import json
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_workspace_id() -> str:
    return f"ws_{uuid.uuid4().hex[:12]}"


def generate_project_id() -> str:
    return f"proj_{uuid.uuid4().hex[:12]}"


def generate_project_agent_id() -> str:
    return f"pagent_{uuid.uuid4().hex[:12]}"


def generate_workspace_agent_id() -> str:
    return f"wagent_{uuid.uuid4().hex[:12]}"


class Workspace(Base):
    """
    Top-level organizational tenant workspace.
    Contains multiple projects, with a central Workspace Agent overseeing all projects.
    """
    __tablename__ = "workspaces"

    id = Column(String(64), primary_key=True, default=generate_workspace_id)
    name = Column(String(255), default="Default Workspace", nullable=False)
    description = Column(Text, default="", nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    projects = relationship("Project", back_populates="workspace", cascade="all, delete-orphan")
    workspace_agent = relationship("WorkspaceAgent", back_populates="workspace", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Workspace id={self.id} name='{self.name}'>"


class WorkspaceAgent(Base):
    """DEPRECATED compatibility record (legacy multi-agent era).

    Synora has exactly ONE shared agent; a project is a context boundary, not an
    agent. This table is retained only so existing rows and endpoints keep
    working, and is excluded from the product model and UI.
    """
    __tablename__ = "workspace_agents"

    id = Column(String(64), primary_key=True, default=generate_workspace_agent_id)
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    name = Column(String(255), default="Synesis Central Workspace Agent", nullable=False)

    # Central Agent Identity & Persona
    identity_json = Column(
        Text,
        default=json.dumps({
            "role": "Central Workspace Intelligence Coordinator",
            "persona": "Omniscient portfolio architect managing all organizational projects, aligning cross-project dependencies, and coordinating specialist capabilities.",
            "prompt_version": "v3.0-workspace-central",
        }),
        nullable=False,
    )

    # Global Portfolio Memory & Cross-Project Learnings
    memory_context_json = Column(
        Text,
        default=json.dumps({
            "portfolio_priorities": [
                "Maintain cross-project coherence and governance",
                "Ensure individual Project States stay synchronized with evidence",
                "Maintain living visual Excalidraw workspaces for each project",
            ],
            "recent_milestones": ["Central Workspace Agent initialized"],
            "cross_project_insights": [],
        }),
        nullable=False,
    )

    # Specialist Execution Capabilities
    capabilities_json = Column(
        Text,
        default=json.dumps([
            "ba_agent",
            "project_planner_agent",
            "functional_agent",
            "tech_agent",
            "frappe_agent",
        ]),
        nullable=False,
    )

    # Connected Tools
    connected_tools_json = Column(
        Text,
        default=json.dumps([
            "google_meet",
            "slack",
            "excalidraw",
        ]),
        nullable=False,
    )

    status = Column(String(32), default="active", nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    workspace = relationship("Workspace", back_populates="workspace_agent")

    def __repr__(self) -> str:
        return f"<WorkspaceAgent id={self.id} workspace_id={self.workspace_id} name='{self.name}'>"


#: Canonical ID of the reserved system project that holds unresolved source
#: evidence. It is never a candidate during project matching and is never
#: listed as an ordinary user project.
SYSTEM_UNKNOWN_CONTEXT_PROJECT_ID = "proj_unknown_context"


class Project(Base):
    """
    Project entity.

    A project is a context, security, and state boundary. It is NOT an agent:
    Synora has exactly one shared agent that operates inside a project context.
    """
    __tablename__ = "projects"

    id = Column(String(64), primary_key=True, default=generate_project_id)
    workspace_id = Column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False, default="ws_default")
    name = Column(String(255), default="Synora Project", nullable=False)
    description = Column(Text, default="", nullable=False)
    # System projects (e.g. Unknown Context) are infrastructure, not user projects.
    is_system = Column(Boolean, default=False, index=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    workspace = relationship("Workspace", back_populates="projects")
    project_agent = relationship("ProjectAgent", back_populates="project", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project id={self.id} name='{self.name}'>"


class ProjectAgent(Base):
    """DEPRECATED compatibility record (legacy multi-agent era).

    Historically one Project Agent per project. Synora now has a single shared
    agent that operates inside a project's context; the BA/Planning/Functional/
    Technical/Frappe modules are capabilities, not agents. Retained only so
    existing rows and endpoints keep working.
    """
    __tablename__ = "project_agents"

    id = Column(String(64), primary_key=True, default=generate_project_agent_id)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    workspace_id = Column(String(64), default="ws_default", nullable=False)
    name = Column(String(255), default="Project Agent", nullable=False)
    
    # Logical Agent Identity & Persona
    identity_json = Column(
        Text,
        default=json.dumps({
            "role": "Project Intelligence Coordinator",
            "persona": "Objective, evidence-backed project architect and coordinator",
            "prompt_version": "v2.0-coordinator",
        }),
        nullable=False,
    )
    
    # Isolated Project Memory & Working Context Boundary
    memory_context_json = Column(
        Text,
        default=json.dumps({
            "key_decisions_summary": [],
            "active_priorities": [],
            "recent_milestones": [],
            "context_notes": "Initialized isolated project memory boundary.",
        }),
        nullable=False,
    )

    # Subordinate Specialist Execution Capabilities
    capabilities_json = Column(
        Text,
        default=json.dumps([
            "ba_agent",
            "project_planner_agent",
            "functional_agent",
            "tech_agent",
            "frappe_agent",
        ]),
        nullable=False,
    )

    # Active Connected Tools (Google Meet, Slack, Excalidraw, extensible to WhatsApp/Zoom)
    connected_tools_json = Column(
        Text,
        default=json.dumps(["google_meet", "slack", "excalidraw"]),
        nullable=False,
    )

    # Living Excalidraw Workspace Association
    excalidraw_workspace_id = Column(String(64), nullable=True)

    status = Column(String(32), default="active", nullable=False)  # active, coordinating, idle
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    project = relationship("Project", back_populates="project_agent")

    @property
    def living_workspace_artifact_id(self):
        return self.excalidraw_workspace_id

    @property
    def workspace_sync_status(self) -> str:
        return "synchronized" if self.excalidraw_workspace_id else "pending"

    __table_args__ = (
        Index("ix_project_agent_ws_proj", "workspace_id", "project_id"),
    )

    def __repr__(self) -> str:
        return f"<ProjectAgent id={self.id} project={self.project_id} status={self.status}>"
