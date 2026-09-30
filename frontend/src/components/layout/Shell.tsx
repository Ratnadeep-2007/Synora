"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  LayoutDashboard,
  Layers,
  PenTool,
  Video,
  Inbox,
  Plug,
  Settings as SettingsIcon,
  Bell,
  HelpCircle,
  ChevronDown,
  Plus,
  Check,
  X,
  Sparkles,
  FolderPlus,
  Trash2,
  AlertTriangle,
  User as UserIcon,
} from "lucide-react";
import { Project } from "@/lib/types";

export type NavTab =
  | "overview"
  | "state"
  | "excalidraw"
  | "meetings"
  | "unknown-context"
  | "sources"
  | "settings";

export interface NotificationItem {
  title: string;
  detail?: string;
}

interface ActiveProject {
  id: string;
  name: string;
  description?: string | null;
  workspace_id?: string;
}

interface ShellProps {
  currentTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  projectVersion: number;
  openConflictsCount: number;
  unknownContextCount?: number;
  projects?: Project[];
  currentProjectId?: string;
  activeProject?: ActiveProject | null;
  workspaceName?: string;
  currentUserName?: string;
  currentUserInitial?: string;
  notifications?: NotificationItem[];
  onSelectProject?: (projectId: string) => void;
  onCreateProject?: (name: string, description?: string, sources?: string[]) => Promise<void>;
  onDeleteProject?: (projectId: string) => Promise<void>;
  children: React.ReactNode;
}

const NAV_ITEMS: Array<{
  id: NavTab;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "state", label: "Project State", icon: Layers },
  { id: "excalidraw", label: "Excalidraw", icon: PenTool },
  { id: "meetings", label: "Meetings", icon: Video },
  { id: "unknown-context", label: "Unknown Context", icon: Inbox },
  { id: "sources", label: "Sources", icon: Plug },
  { id: "settings", label: "Settings", icon: SettingsIcon },
];

export function Shell({
  currentTab,
  onTabChange,
  projectVersion,
  openConflictsCount,
  unknownContextCount = 0,
  projects = [],
  currentProjectId,
  activeProject,
  workspaceName = "Workspace",
  currentUserName,
  currentUserInitial,
  notifications = [],
  onSelectProject,
  onCreateProject,
  onDeleteProject,
  children,
}: ShellProps) {
  const [isProjectDropdownOpen, setIsProjectDropdownOpen] = useState(false);
  const [projectSearch, setProjectSearch] = useState("");
  const [isNewProjectModalOpen, setIsNewProjectModalOpen] = useState(false);
  const [createStep, setCreateStep] = useState(1);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectUse, setNewProjectUse] = useState("");
  const [newProjectContext, setNewProjectContext] = useState("");
  const [newProjectTools, setNewProjectTools] = useState<string[]>(["google_meet", "whatsapp", "excalidraw"]);
  const [isCreatingProject, setIsCreatingProject] = useState(false);
  const [isActivityOpen, setIsActivityOpen] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [isDeleteProjectModalOpen, setIsDeleteProjectModalOpen] = useState(false);
  const [deleteProjectConfirmation, setDeleteProjectConfirmation] = useState("");
  const [isDeletingProject, setIsDeletingProject] = useState(false);

  const selectedProject = activeProject || projects.find((p) => p.id === currentProjectId) || null;

  const filteredProjects = useMemo(() => {
    const q = projectSearch.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.id.toLowerCase().includes(q) ||
        (p.description || "").toLowerCase().includes(q)
    );
  }, [projects, projectSearch]);

  const recentProjects = useMemo(() => projects.slice(0, 3), [projects]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsProjectDropdownOpen(false);
        setIsActivityOpen(false);
        setIsUserMenuOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggleTool = (tool: string) => {
    setNewProjectTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool]
    );
  };

  const resetCreateModal = () => {
    setCreateStep(1);
    setNewProjectName("");
    setNewProjectUse("");
    setNewProjectContext("");
    setNewProjectTools(["google_meet", "whatsapp", "excalidraw"]);
    setIsNewProjectModalOpen(false);
  };

  const resetDeleteModal = () => {
    setDeleteProjectConfirmation("");
    setIsDeleteProjectModalOpen(false);
  };

  const handleDeleteProjectSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProject || !onDeleteProject) return;
    if (deleteProjectConfirmation.trim().toUpperCase() !== "DELETE") return;

    try {
      setIsDeletingProject(true);
      await onDeleteProject(selectedProject.id);
      resetDeleteModal();
      setIsProjectDropdownOpen(false);
    } catch (err: any) {
      alert(`Failed to delete project: ${err.message}`);
    } finally {
      setIsDeletingProject(false);
    }
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim() || !onCreateProject) return;
    try {
      setIsCreatingProject(true);
      const description = [newProjectUse, newProjectContext].filter(Boolean).join("\n\n");
      await onCreateProject(newProjectName.trim(), description || undefined, newProjectTools);
      resetCreateModal();
      setIsProjectDropdownOpen(false);
    } catch (err: any) {
      alert(`Failed to create project: ${err.message}`);
    } finally {
      setIsCreatingProject(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-canvas text-text-main font-sans">
      {/* Sidebar Rail (240px) */}
      <aside className="w-60 bg-surface border-r border-border flex flex-col shrink-0 fixed top-0 bottom-0 left-0 z-30">
        {/* Brand */}
        <div className="h-16 px-6 flex items-center gap-3 border-b border-border">
          <div className="w-7 h-7 rounded-md bg-primary text-white flex items-center justify-center font-bold text-sm tracking-wider">
            S
          </div>
          <div>
            <span className="font-semibold text-base tracking-tight text-text-main">
              Synora
            </span>
            <span className="ml-1 text-[10px] text-text-muted font-mono uppercase tracking-widest block -mt-0.5">
              Intel OS
            </span>
          </div>
        </div>

        {/* Navigation list — exactly the 10 enterprise entries */}
        <nav className="p-3 flex-1 overflow-y-auto" aria-label="Primary">
          <div className="space-y-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = currentTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onTabChange(item.id)}
                  aria-current={isActive ? "page" : undefined}
                  className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-md text-sm font-medium transition-all relative ${
                    isActive
                      ? "bg-primary-soft text-primary font-semibold"
                      : "text-text-muted hover:text-text-main hover:bg-canvas"
                  }`}
                >
                  {isActive && (
                    <div className="absolute left-0 top-1.5 bottom-1.5 w-[3px] bg-primary rounded-r" />
                  )}
                  <div className="flex items-center gap-3">
                    <Icon className={`w-4 h-4 ${isActive ? "text-primary" : "text-text-muted"}`} />
                    <span>{item.label}</span>
                  </div>
                  {item.id === "unknown-context" && unknownContextCount > 0 && (
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full border bg-warning/10 text-warning border-warning/20">
                      {unknownContextCount}
                    </span>
                  )}
                  {item.id === "state" && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-canvas text-text-muted border border-border">
                      v{projectVersion}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </nav>

        {/* Footer info */}
        <div className="p-4 border-t border-border bg-surface-soft">
          {selectedProject && (
            <div className="mb-3 rounded-xl border border-border bg-surface p-3 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-text-muted">Active project</span>
                <span className="inline-flex items-center gap-1 text-[10px] font-medium text-success">
                  <span className="w-1.5 h-1.5 rounded-full bg-success" />
                  Live
                </span>
              </div>
              <div className="mt-2 text-xs font-semibold text-text-main truncate">{selectedProject.name}</div>
              <div className="mt-0.5 text-[10px] text-text-muted font-mono truncate">{selectedProject.id}</div>
            </div>
          )}
          <div className="text-[11px] text-text-muted">
            <span className="font-medium text-text-main">Authoritative Engine</span>
            <div className="font-mono text-[10px] mt-0.5">PostgreSQL • v{projectVersion}</div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col ml-60 min-h-screen">
        {/* Top Bar (64px, restrained glass) */}
        <header
          className="h-16 sticky top-0 z-20 px-8 flex items-center justify-between"
          style={{
            background: "rgba(255,255,255,0.78)",
            backdropFilter: "blur(14px)",
            WebkitBackdropFilter: "blur(14px)",
            borderBottom: "1px solid #E7EAE5",
          }}
        >
          {/* Left: Synesis mark + Project selector */}
          <div className="relative flex items-center gap-3">
            <div className="w-7 h-7 rounded-md bg-primary text-white hidden items-center justify-center font-bold text-xs">
              S
            </div>
            <button
              onClick={() => setIsProjectDropdownOpen(!isProjectDropdownOpen)}
              className="flex items-center gap-2 py-1.5 px-3 rounded-md hover:bg-canvas transition-colors border border-border bg-surface"
              title="Switch project or create a new project"
              aria-haspopup="listbox"
              aria-expanded={isProjectDropdownOpen}
            >
              <div className="w-2.5 h-2.5 rounded-full bg-success" aria-hidden />
              <div className="text-left">
                <span className="text-sm font-semibold text-text-main block leading-tight">
                  {selectedProject ? `Project: ${selectedProject.name}` : "Select a project"}
                </span>
                <span className="text-[11px] text-text-muted font-mono block leading-tight">
                  {selectedProject ? `${workspaceName} • ${selectedProject.id}` : "No project selected"}
                </span>
              </div>
              <ChevronDown className="w-3.5 h-3.5 text-text-muted ml-1" />
            </button>

            {/* Project selector dropdown */}
            {isProjectDropdownOpen && (
              <div className="absolute top-12 left-0 w-80 rounded-xl bg-surface border border-border shadow-lg p-2 z-50 space-y-1">
                <div className="px-1 pb-1">
                  <input
                    type="text"
                    value={projectSearch}
                    onChange={(e) => setProjectSearch(e.target.value)}
                    placeholder="Search projects"
                    aria-label="Search projects"
                    className="w-full px-3 py-1.5 text-xs rounded-md bg-canvas border border-border focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/50 text-text-main placeholder:text-text-muted"
                  />
                </div>
                <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-text-muted border-b border-border/60 flex items-center justify-between">
                  <span>Recent projects</span>
                  <span className="font-mono">{filteredProjects.length || 0} available</span>
                </div>

                <div className="max-h-56 overflow-y-auto space-y-0.5" role="listbox">
                  {(projectSearch ? filteredProjects : recentProjects.length > 0 ? recentProjects : filteredProjects).map((p) => {
                    const isSelected = p.id === currentProjectId;
                    return (
                      <button
                        key={p.id}
                        role="option"
                        aria-selected={isSelected}
                        onClick={() => {
                          if (onSelectProject) onSelectProject(p.id);
                          setIsProjectDropdownOpen(false);
                        }}
                        className={`w-full text-left px-3 py-2 rounded-md text-xs flex items-center justify-between transition-colors ${
                          isSelected
                            ? "bg-primary-soft text-primary font-semibold"
                            : "hover:bg-canvas text-text-main"
                        }`}
                      >
                        <div className="truncate">
                          <div className="font-medium truncate">{p.name}</div>
                          <span className="text-[10px] font-mono text-text-muted block">
                            {p.id}
                          </span>
                        </div>
                        {isSelected && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
                      </button>
                    );
                  })}
                  {projectSearch && filteredProjects.length > 3 && (
                    <div className="px-3 py-1 text-[10px] text-text-muted">
                      Showing all {filteredProjects.length} matches
                    </div>
                  )}
                  {!projectSearch && filteredProjects.length > 3 && (
                    <div className="px-1">
                      {filteredProjects.slice(3).map((p) => {
                        const isSelected = p.id === currentProjectId;
                        return (
                          <button
                            key={p.id}
                            role="option"
                            aria-selected={isSelected}
                            onClick={() => {
                              if (onSelectProject) onSelectProject(p.id);
                              setIsProjectDropdownOpen(false);
                            }}
                            className={`w-full text-left px-3 py-2 rounded-md text-xs flex items-center justify-between transition-colors ${
                              isSelected
                                ? "bg-primary-soft text-primary font-semibold"
                                : "hover:bg-canvas text-text-main"
                            }`}
                          >
                            <div className="truncate">
                              <div className="font-medium truncate">{p.name}</div>
                              <span className="text-[10px] font-mono text-text-muted block">
                                {p.id}
                              </span>
                            </div>
                            {isSelected && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>

                <div className="pt-2 border-t border-border/60 space-y-1">
                  <button
                    onClick={() => {
                      setIsProjectDropdownOpen(false);
                      setCreateStep(1);
                      setIsNewProjectModalOpen(true);
                    }}
                    className="w-full py-2 px-3 rounded-md text-xs font-semibold bg-primary hover:bg-primary-hover text-white flex items-center justify-center gap-1.5 transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Create project</span>
                  </button>
                  <button
                    onClick={() => {
                      if (onSelectProject && filteredProjects.length > 0) {
                        const next = filteredProjects.find((p) => p.id !== currentProjectId);
                        if (next) onSelectProject(next.id);
                      }
                      setIsProjectDropdownOpen(false);
                    }}
                    className="w-full py-1.5 px-3 rounded-md text-xs font-medium text-text-muted hover:text-text-main hover:bg-canvas transition-colors"
                  >
                    Switch project
                  </button>

                  {selectedProject && onDeleteProject && (
                    <button
                      onClick={() => {
                        setIsProjectDropdownOpen(false);
                        setDeleteProjectConfirmation("");
                        setIsDeleteProjectModalOpen(true);
                      }}
                      className="w-full py-1.5 px-3 rounded-md text-xs font-medium text-danger hover:bg-danger/10 border border-transparent hover:border-danger/20 transition-colors flex items-center justify-center gap-1.5"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      Delete current project
                    </button>
                  )}
                </div>
              </div>
            )}

            <div className="h-4 w-[1px] bg-border mx-1" />

            <div className="text-xs font-mono px-2 py-0.5 rounded bg-surface border border-border text-text-muted">
              State: <strong className="text-primary font-semibold">v{projectVersion}</strong>
            </div>
          </div>

          <div className="flex-1" />

          {/* Right: Global search, Activity, Help, User menu */}
          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                onClick={() => {
                  setIsActivityOpen(!isActivityOpen);
                  setIsUserMenuOpen(false);
                }}
                className="p-2 rounded-md text-text-muted hover:text-text-main hover:bg-canvas transition-colors relative"
                title="Activity"
                aria-label="Activity"
                aria-expanded={isActivityOpen}
              >
                <Bell className="w-4 h-4" />
                {notifications.length > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-warning text-white text-[10px] font-bold flex items-center justify-center">
                    {notifications.length}
                  </span>
                )}
              </button>
              {isActivityOpen && (
                <div className="absolute right-0 top-11 w-80 rounded-xl bg-surface border border-border shadow-lg p-2 z-50 space-y-1">
                  <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-text-muted border-b border-border/60">
                    Operational notifications
                  </div>
                  {notifications.length === 0 ? (
                    <div className="px-3 py-4 text-xs text-text-muted text-center">
                      No pending operational alerts.
                    </div>
                  ) : (
                    <div className="max-h-64 overflow-y-auto space-y-0.5">
                      {notifications.map((n, idx) => (
                        <div key={idx} className="px-3 py-2 rounded-md hover:bg-canvas text-xs">
                          <div className="font-semibold text-text-main">{n.title}</div>
                          {n.detail && <div className="text-text-muted mt-0.5">{n.detail}</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            <button
              className="p-2 rounded-md text-text-muted hover:text-text-main hover:bg-canvas transition-colors"
              title="Help"
              aria-label="Help"
            >
              <HelpCircle className="w-4 h-4" />
            </button>

            <div className="relative">
              <button
                onClick={() => {
                  setIsUserMenuOpen(!isUserMenuOpen);
                  setIsActivityOpen(false);
                }}
                className="flex items-center gap-2 pl-1 pr-2 py-1 border-l border-border rounded-md hover:bg-canvas transition-colors"
                aria-haspopup="menu"
                aria-expanded={isUserMenuOpen}
                title="User menu"
              >
                <div className="w-7 h-7 rounded-full bg-primary/10 text-primary border border-primary/20 flex items-center justify-center font-medium text-xs">
                  {currentUserInitial || "•"}
                </div>
                {currentUserName && (
                  <span className="text-xs font-medium text-text-main hidden sm:block">{currentUserName}</span>
                )}
              </button>
              {isUserMenuOpen && (
                <div className="absolute right-0 top-11 w-52 rounded-xl bg-surface border border-border shadow-lg p-2 z-50" role="menu">
                  <div className="px-3 py-2 border-b border-border/60">
                    <div className="text-xs font-semibold text-text-main flex items-center gap-1.5">
                      <UserIcon className="w-3.5 h-3.5 text-text-muted" />
                      <span>{currentUserName || "Account"}</span>
                    </div>
                    <div className="text-[11px] text-text-muted font-mono mt-0.5">Workspace member</div>
                  </div>
                  <button
                    onClick={() => {
                      setIsUserMenuOpen(false);
                      onTabChange("settings");
                    }}
                    className="w-full text-left px-3 py-2 rounded-md text-xs text-text-main hover:bg-canvas transition-colors"
                    role="menuitem"
                  >
                    Workspace settings
                  </button>
                  <button
                    onClick={() => {
                      setIsUserMenuOpen(false);
                      onTabChange("sources");
                    }}
                    className="w-full text-left px-3 py-2 rounded-md text-xs text-text-main hover:bg-canvas transition-colors"
                    role="menuitem"
                  >
                    Connected sources
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Viewport Container (1440px max width) */}
        <main className="flex-1 p-8 max-w-[1440px] w-full mx-auto">
          {children}
        </main>
      </div>

      {/* Modal: Delete Project — explicit destructive confirmation */}
      {isDeleteProjectModalOpen && selectedProject && (
        <div className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl bg-surface border border-danger/20 shadow-2xl overflow-hidden">
            <div className="p-6 space-y-5">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-danger/10 text-danger flex items-center justify-center shrink-0">
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-text-main">Delete project</h3>
                  <p className="text-xs text-text-muted mt-1">This permanently removes the project and its DB-backed project data.</p>
                </div>
                <button
                  onClick={resetDeleteModal}
                  disabled={isDeletingProject}
                  className="ml-auto text-text-muted hover:text-text-main p-1 rounded-md disabled:opacity-50"
                  aria-label="Close delete dialog"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="rounded-xl border border-danger/20 bg-danger/5 p-4 space-y-2">
                <div className="text-[10px] uppercase tracking-wider font-bold text-danger">Destructive action</div>
                <div className="text-sm font-semibold text-text-main">{selectedProject.name}</div>
                <div className="text-[11px] text-text-muted font-mono">{selectedProject.id}</div>
                <p className="text-xs text-text-muted leading-relaxed">
                  Project State, evidence, AI execution history, meetings, visual revisions, and Excalidraw data will be removed. The reserved Unknown Context area is preserved.
                </p>
              </div>

              <form onSubmit={handleDeleteProjectSubmit} className="space-y-3">
                <label htmlFor="delete-project-confirmation" className="text-xs font-semibold text-text-main block">
                  Type <span className="font-mono text-danger">DELETE</span> to continue
                </label>
                <input
                  id="delete-project-confirmation"
                  value={deleteProjectConfirmation}
                  onChange={(e) => setDeleteProjectConfirmation(e.target.value)}
                  placeholder="DELETE"
                  autoComplete="off"
                  autoFocus
                  disabled={isDeletingProject}
                  className="w-full px-3 py-2.5 text-xs rounded-lg bg-canvas border border-border focus:outline-none focus:ring-1 focus:ring-danger/40 focus:border-danger text-text-main placeholder:text-text-muted"
                />

                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={resetDeleteModal}
                    disabled={isDeletingProject}
                    className="px-3.5 py-2 text-xs font-semibold text-text-muted hover:text-text-main rounded-lg hover:bg-canvas transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isDeletingProject || deleteProjectConfirmation.trim().toUpperCase() !== "DELETE"}
                    className="px-4 py-2 text-xs font-semibold text-white bg-danger hover:bg-danger/90 rounded-lg transition-colors disabled:opacity-40 flex items-center gap-1.5"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    {isDeletingProject ? "Deleting…" : "Delete project"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Create Project — focused 5-step flow */
      {isNewProjectModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl bg-surface border border-border shadow-2xl p-6 space-y-5">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-primary-soft text-primary flex items-center justify-center font-bold">
                  <FolderPlus className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-text-main">Create project</h3>
                  <p className="text-xs text-text-muted">
                    Step {createStep} of 4 · project setup
                  </p>
                </div>
              </div>
              <button
                onClick={resetCreateModal}
                className="text-text-muted hover:text-text-main p-1 rounded-md"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Step indicator */}
            <div className="flex items-center gap-1" aria-hidden>
              {[1, 2, 3, 4].map((s) => (
                <div
                  key={s}
                  className={`h-1 flex-1 rounded-full ${s <= createStep ? "bg-primary" : "bg-border"}`}
                />
              ))}
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-4">
              {createStep === 1 && (
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-text-main" htmlFor="new-project-name">
                    1. Project name <span className="text-danger">*</span>
                  </label>
                  <input
                    id="new-project-name"
                    type="text"
                    required
                    placeholder="e.g. Claims Processing Platform"
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-md bg-canvas border border-border focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary text-text-main"
                  />
                </div>
              )}

              {createStep === 2 && (
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-text-main" htmlFor="new-project-use">
                    2. What are you building?
                  </label>
                  <textarea
                    id="new-project-use"
                    rows={3}
                    placeholder="Goals, target systems, or architecture scope..."
                    value={newProjectUse}
                    onChange={(e) => setNewProjectUse(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-md bg-canvas border border-border focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary text-text-main resize-none"
                  />
                  <div className="pt-2">
                    <label className="text-xs font-semibold text-text-main" htmlFor="new-project-context">
                      Initial context <span className="font-normal text-text-muted">(optional)</span>
                    </label>
                    <textarea
                      id="new-project-context"
                      rows={3}
                      placeholder="Background, constraints, or key decisions…"
                      value={newProjectContext}
                      onChange={(e) => setNewProjectContext(e.target.value)}
                      className="w-full mt-1.5 px-3 py-2 text-xs rounded-md bg-canvas border border-border focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary text-text-main resize-none"
                    />
                  </div>
                </div>
              )}

              {createStep === 3 && (
                <div className="space-y-2">
                  <span className="text-xs font-semibold text-text-main block">4. Connect tools</span>
                  {[
                    { id: "google_meet", label: "Google Meet — meeting transcripts" },
                    { id: "whatsapp", label: "WhatsApp — group chat via Baileys" },
                    { id: "excalidraw", label: "Excalidraw — living visual workspace" },
                  ].map((tool) => (
                    <label
                      key={tool.id}
                      className="flex items-center gap-2.5 p-2.5 rounded-md border border-border bg-canvas text-xs cursor-pointer hover:border-primary/40 transition-colors"
                    >
                      <input
                        type="checkbox"
                        checked={newProjectTools.includes(tool.id)}
                        onChange={() => toggleTool(tool.id)}
                        className="accent-[#173F35]"
                      />
                      <span className="text-text-main font-medium">{tool.label}</span>
                    </label>
                  ))}
                </div>
              )}

              {createStep === 4 && (
                <div className="space-y-2 text-xs">
                  <span className="text-xs font-semibold text-text-main block">4. Review & create</span>
                  <div className="p-3 rounded-md bg-primary-soft/40 border border-primary/20 text-xs text-text-muted">
                    Your project space will be created with the selected sources and a living visual workspace.
                  </div>
                  <div className="p-3 rounded-md bg-canvas border border-border space-y-1">
                    <div><strong className="text-text-main">{newProjectName || "Untitled project"}</strong></div>
                    {newProjectUse && <div className="text-text-muted">{newProjectUse}</div>}
                    <div className="text-text-muted">Tools: {newProjectTools.join(", ") || "none"}</div>
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between pt-2">
                <button
                  type="button"
                  onClick={() => (createStep > 1 ? setCreateStep(createStep - 1) : resetCreateModal())}
                  className="px-3.5 py-2 text-xs font-semibold text-text-muted hover:text-text-main rounded-md hover:bg-canvas transition-colors"
                >
                  {createStep > 1 ? "Back" : "Cancel"}
                </button>
                {createStep < 4 ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (createStep === 1 && !newProjectName.trim()) return;
                      setCreateStep(createStep + 1);
                    }}
                    disabled={createStep === 1 && !newProjectName.trim()}
                    className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-md transition-colors disabled:opacity-50"
                  >
                    Continue
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={isCreatingProject || !newProjectName.trim()}
                    className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-md transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  >
                    {isCreatingProject ? (
                      <span>Provisioning...</span>
                    ) : (
                      <>
                        <Plus className="w-3.5 h-3.5" />
                        <span>Create project</span>
                      </>
                    )}
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
