"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Layers,
  PenTool,
  Video,
  Plug,
  Settings as SettingsIcon,
  Bell,
  ChevronDown,
  Plus,
  Check,
  X,
  Sparkles,
  FolderPlus,
  Trash2,
  AlertTriangle,
  User as UserIcon,
  Search,
  Command,
  Zap,
} from "lucide-react";
import { Project } from "@/lib/types";

export type NavTab =
  | "overview"
  | "state"
  | "excalidraw"
  | "meetings"
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
  onOpenAgentSheet?: () => void;
  onOpenCommandPalette?: () => void;
  onOpenStoryModal?: () => void;
  children: React.ReactNode;
}

const PRIMARY_NAV_ITEMS: Array<{
  id: NavTab;
  label: string;
  shortLabel: string;
  shortcut: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { id: "overview", label: "Project Pulse", shortLabel: "Pulse", shortcut: "1", icon: Activity },
  { id: "state", label: "Project State", shortLabel: "State", shortcut: "2", icon: Layers },
  { id: "excalidraw", label: "Project Atlas", shortLabel: "Atlas", shortcut: "3", icon: PenTool },
  { id: "meetings", label: "Meetings", shortLabel: "Meetings", shortcut: "4", icon: Video },
  { id: "sources", label: "Sources", shortLabel: "Sources", shortcut: "5", icon: Plug },
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
  onOpenAgentSheet,
  onOpenCommandPalette,
  onOpenStoryModal,
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

  const recentProjects = useMemo(() => projects.slice(0, 4), [projects]);

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
    <div className="flex min-h-screen bg-canvas text-text-main font-sans selection:bg-primary/20 selection:text-text-main">
      {/* Intelligent Navigation Rail (Minimal 64px on mobile/desktop, clean and calm) */}
      <aside className="w-16 md:w-56 bg-surface border-r border-border flex flex-col shrink-0 fixed top-0 bottom-0 left-0 z-30 transition-all duration-300">
        {/* Brand / Intelligence Logo */}
        <div className="h-16 px-4 md:px-5 flex items-center justify-between border-b border-border/80">
          <div className="flex items-center gap-3">
            <div className="relative w-8 h-8 rounded-lg bg-surface-soft border border-primary/30 flex items-center justify-center font-bold text-sm tracking-wider text-primary shadow-[0_0_12px_rgba(16,185,129,0.15)]">
              <span>S</span>
              <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-primary animate-pulse" />
            </div>
            <div className="hidden md:block">
              <span className="font-semibold text-sm tracking-tight text-text-main flex items-center gap-1.5">
                Synora
                <span className="text-[9px] font-mono uppercase tracking-widest px-1.5 py-0.2 rounded bg-primary/10 text-primary border border-primary/20">
                  OS
                </span>
              </span>
              <span className="text-[10px] text-text-muted font-mono tracking-tight block">
                Project Intelligence
              </span>
            </div>
          </div>
        </div>

        {/* Primary Navigation Rail */}
        <nav className="p-2 md:p-3 flex-1 overflow-y-auto space-y-1" aria-label="Primary">
          <div className="hidden md:block px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.16em] text-text-muted/70">
            Intelligence Views
          </div>

          {PRIMARY_NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = currentTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onTabChange(item.id)}
                aria-current={isActive ? "page" : undefined}
                title={`${item.label} (${item.shortcut})`}
                className={`w-full flex items-center justify-between px-2.5 md:px-3 py-2.5 rounded-lg text-xs font-medium transition-all group relative ${
                  isActive
                    ? "bg-primary/10 text-text-main font-semibold border border-primary/25 shadow-[0_0_15px_rgba(16,185,129,0.08)]"
                    : "text-text-muted hover:text-text-main hover:bg-surface-soft border border-transparent"
                }`}
              >
                {isActive && (
                  <div className="absolute left-0 top-2 bottom-2 w-0.5 bg-primary rounded-r" />
                )}
                <div className="flex items-center gap-2.5 min-w-0">
                  <Icon
                    className={`w-4 h-4 shrink-0 transition-colors ${
                      isActive ? "text-primary" : "text-text-muted group-hover:text-text-main"
                    }`}
                  />
                  <span className="hidden md:inline truncate">{item.label}</span>
                </div>

                <div className="hidden md:flex items-center gap-1.5">
                  {item.id === "state" && (
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-canvas text-primary border border-border">
                      v{projectVersion}
                    </span>
                  )}
                  {item.id === "overview" && openConflictsCount > 0 && (
                    <span className="w-1.5 h-1.5 rounded-full bg-danger animate-pulse" />
                  )}
                  {item.id === "excalidraw" && unknownContextCount > 0 && (
                    <span className="text-[9px] font-mono px-1 rounded bg-warning/20 text-warning border border-warning/30">
                      {unknownContextCount}
                    </span>
                  )}
                  <kbd className="opacity-0 group-hover:opacity-100 transition-opacity text-[9px] font-mono text-text-muted bg-canvas px-1 rounded border border-border">
                    {item.shortcut}
                  </kbd>
                </div>
              </button>
            );
          })}
        </nav>

        {/* Bottom Rail: Storytelling, Settings & Agent status */}
        <div className="p-2 md:p-3 border-t border-border/80 space-y-1">
          {/* Intelligence Pipeline Story Walkthrough */}
          {onOpenStoryModal && (
            <button
              onClick={onOpenStoryModal}
              title="How Synora Understands Projects"
              className="w-full flex items-center justify-between px-2.5 md:px-3 py-2 rounded-lg text-xs text-text-muted hover:text-primary hover:bg-primary/5 transition-all border border-transparent hover:border-primary/20 group"
            >
              <div className="flex items-center gap-2.5">
                <Sparkles className="w-4 h-4 text-primary shrink-0 group-hover:rotate-12 transition-transform" />
                <span className="hidden md:inline text-[11px] font-medium">How Synora Works</span>
              </div>
              <span className="hidden md:inline text-[9px] font-mono text-text-muted">Story</span>
            </button>
          )}

          {/* Settings */}
          <button
            onClick={() => onTabChange("settings")}
            title="Settings"
            className={`w-full flex items-center justify-between px-2.5 md:px-3 py-2 rounded-lg text-xs transition-colors ${
              currentTab === "settings"
                ? "bg-surface-soft text-text-main font-medium border border-border"
                : "text-text-muted hover:text-text-main hover:bg-surface-soft border border-transparent"
            }`}
          >
            <div className="flex items-center gap-2.5">
              <SettingsIcon className="w-4 h-4 shrink-0 text-text-muted" />
              <span className="hidden md:inline text-[11px]">Settings</span>
            </div>
          </button>

          {/* Agent Persistent Status Pill in Sidebar */}
          {onOpenAgentSheet && (
            <button
              onClick={onOpenAgentSheet}
              className="w-full mt-2 p-2 rounded-lg bg-canvas border border-border hover:border-primary/30 transition-all text-left group"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                  <span className="hidden md:inline text-[10px] font-semibold tracking-wider uppercase text-text-muted group-hover:text-primary transition-colors">
                    Synora Agent
                  </span>
                </div>
                <Zap className="hidden md:block w-3 h-3 text-primary opacity-60 group-hover:opacity-100" />
              </div>
              <div className="hidden md:block text-[10px] text-text-muted/80 font-mono mt-0.5 truncate">
                Continuous Cognition
              </div>
            </button>
          )}
        </div>
      </aside>

      {/* Main Content Viewport */}
      <div className="flex-1 flex flex-col ml-16 md:ml-56 min-h-screen">
        {/* Editorial Top Bar (Obsidian Glass) */}
        <header className="h-16 sticky top-0 z-20 px-4 md:px-8 flex items-center justify-between bg-surface/85 backdrop-blur-md border-b border-border">
          {/* Left: Project Selector Pill */}
          <div className="relative flex items-center gap-2 md:gap-3">
            <button
              onClick={() => setIsProjectDropdownOpen(!isProjectDropdownOpen)}
              className="flex items-center gap-2 py-1.5 px-3 rounded-lg hover:bg-surface-soft transition-all border border-border bg-canvas/80 group"
              title="Switch or create projects"
              aria-haspopup="listbox"
              aria-expanded={isProjectDropdownOpen}
            >
              <span className="w-2 h-2 rounded-full bg-primary animate-pulse shrink-0" />
              <div className="text-left">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs md:text-sm font-semibold text-text-main group-hover:text-primary transition-colors truncate max-w-[140px] md:max-w-[200px]">
                    {selectedProject ? selectedProject.name : "Select Project"}
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-surface border border-border text-primary font-bold">
                    v{projectVersion}
                  </span>
                </div>
              </div>
              <ChevronDown className="w-3.5 h-3.5 text-text-muted group-hover:text-text-main transition-colors ml-0.5" />
            </button>

            {/* Quick Command Palette Button */}
            {onOpenCommandPalette && (
              <button
                onClick={onOpenCommandPalette}
                className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface border border-border text-text-muted hover:text-text-main hover:border-primary/40 transition-all text-xs"
                title="Open Command Palette (⌘K)"
              >
                <Search className="w-3.5 h-3.5 text-primary" />
                <span className="text-text-muted text-[11px]">Command Palette</span>
                <kbd className="text-[9px] font-mono px-1 py-0.5 rounded bg-canvas border border-border text-text-muted">
                  ⌘K
                </kbd>
              </button>
            )}

            {/* Project dropdown modal */}
            {isProjectDropdownOpen && (
              <div className="absolute top-12 left-0 w-84 rounded-xl bg-surface border border-border shadow-2xl p-2.5 z-50 space-y-2 animate-in fade-in zoom-in-95 duration-150">
                <div className="px-1">
                  <input
                    type="text"
                    value={projectSearch}
                    onChange={(e) => setProjectSearch(e.target.value)}
                    placeholder="Search projects..."
                    aria-label="Search projects"
                    autoFocus
                    className="w-full px-3 py-1.5 text-xs rounded-lg bg-canvas border border-border focus:outline-none focus:border-primary text-text-main placeholder:text-text-muted"
                  />
                </div>

                <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-[0.16em] text-text-muted border-b border-border/60 flex items-center justify-between">
                  <span>Available Projects</span>
                  <span className="font-mono">{filteredProjects.length}</span>
                </div>

                <div className="max-h-56 overflow-y-auto space-y-1" role="listbox">
                  {(projectSearch ? filteredProjects : recentProjects).map((p) => {
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
                        className={`w-full text-left px-3 py-2 rounded-lg text-xs flex items-center justify-between transition-colors ${
                          isSelected
                            ? "bg-primary/10 text-text-main font-semibold border border-primary/20"
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

                <div className="pt-2 border-t border-border/60 space-y-1">
                  <button
                    onClick={() => {
                      setIsProjectDropdownOpen(false);
                      setCreateStep(1);
                      setIsNewProjectModalOpen(true);
                    }}
                    className="w-full py-2 px-3 rounded-lg text-xs font-semibold bg-primary hover:bg-primary-hover text-white flex items-center justify-center gap-1.5 transition-all shadow-[0_0_12px_rgba(16,185,129,0.2)]"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Create new project</span>
                  </button>

                  {selectedProject && onDeleteProject && (
                    <button
                      onClick={() => {
                        setIsProjectDropdownOpen(false);
                        setDeleteProjectConfirmation("");
                        setIsDeleteProjectModalOpen(true);
                      }}
                      className="w-full py-1.5 px-3 rounded-lg text-xs font-medium text-danger hover:bg-danger/10 border border-transparent hover:border-danger/20 transition-colors flex items-center justify-center gap-1.5"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Delete project</span>
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Right: Persistent Synora Intelligence Pill & Controls */}
          <div className="flex items-center gap-2 md:gap-3">
            {/* Synora Persistent Agent HUD Pill */}
            {onOpenAgentSheet && (
              <button
                onClick={onOpenAgentSheet}
                className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-primary/25 bg-primary/10 hover:bg-primary/20 text-text-main transition-all text-xs shadow-[0_0_14px_rgba(16,185,129,0.15)] group"
                title="Inspect Synora Agent Cognition"
              >
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
                </span>
                <span className="font-semibold text-[11px] text-text-main">
                  Synora is watching
                </span>
                <span className="hidden sm:inline text-[9px] font-mono px-1.5 py-0.2 rounded bg-canvas/80 text-primary border border-primary/30">
                  Inspect
                </span>
              </button>
            )}

            {/* Unresolved Conflict Badge */}
            {openConflictsCount > 0 && (
              <button
                onClick={() => onTabChange("overview")}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-danger/30 bg-danger/10 text-danger text-[11px] font-semibold animate-pulse"
                title={`${openConflictsCount} unresolved conflicts detected`}
              >
                <AlertTriangle className="w-3 h-3" />
                <span>{openConflictsCount} Conflict{openConflictsCount > 1 ? "s" : ""}</span>
              </button>
            )}

            {/* Operational notifications */}
            <div className="relative">
              <button
                onClick={() => {
                  setIsActivityOpen(!isActivityOpen);
                  setIsUserMenuOpen(false);
                }}
                className="p-2 rounded-lg text-text-muted hover:text-text-main hover:bg-surface-soft transition-colors relative"
                title="Notifications"
                aria-label="Notifications"
                aria-expanded={isActivityOpen}
              >
                <Bell className="w-4 h-4" />
                {notifications.length > 0 && (
                  <span className="absolute 1 top-1 right-1 w-2 h-2 rounded-full bg-warning" />
                )}
              </button>

              {isActivityOpen && (
                <div className="absolute right-0 top-11 w-80 rounded-xl bg-surface border border-border shadow-2xl p-2.5 z-50 space-y-1">
                  <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-text-muted border-b border-border/60">
                    System Telemetry
                  </div>
                  {notifications.length === 0 ? (
                    <div className="px-3 py-5 text-xs text-text-muted text-center">
                      All intelligence pipelines operating normally.
                    </div>
                  ) : (
                    <div className="max-h-64 overflow-y-auto space-y-1">
                      {notifications.map((n, idx) => (
                        <div key={idx} className="px-3 py-2 rounded-lg bg-canvas border border-border text-xs">
                          <div className="font-semibold text-text-main">{n.title}</div>
                          {n.detail && <div className="text-text-muted mt-0.5 text-[11px]">{n.detail}</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* User Avatar Menu */}
            <div className="relative">
              <button
                onClick={() => {
                  setIsUserMenuOpen(!isUserMenuOpen);
                  setIsActivityOpen(false);
                }}
                className="flex items-center gap-2 p-1 rounded-lg hover:bg-surface-soft transition-colors"
                aria-haspopup="menu"
                aria-expanded={isUserMenuOpen}
                title="User Menu"
              >
                <div className="w-7 h-7 rounded-full bg-primary/20 text-primary border border-primary/30 flex items-center justify-center font-semibold text-xs">
                  {currentUserInitial || "U"}
                </div>
              </button>

              {isUserMenuOpen && (
                <div className="absolute right-0 top-11 w-52 rounded-xl bg-surface border border-border shadow-2xl p-2 z-50" role="menu">
                  <div className="px-3 py-2 border-b border-border/60">
                    <div className="text-xs font-semibold text-text-main flex items-center gap-1.5">
                      <UserIcon className="w-3.5 h-3.5 text-primary" />
                      <span>{currentUserName || "Lead Architect"}</span>
                    </div>
                    <div className="text-[10px] text-text-muted font-mono mt-0.5">{workspaceName}</div>
                  </div>
                  <button
                    onClick={() => {
                      setIsUserMenuOpen(false);
                      onTabChange("settings");
                    }}
                    className="w-full text-left px-3 py-2 rounded-md text-xs text-text-main hover:bg-canvas transition-colors"
                    role="menuitem"
                  >
                    Workspace Settings
                  </button>
                  <button
                    onClick={() => {
                      setIsUserMenuOpen(false);
                      onTabChange("sources");
                    }}
                    className="w-full text-left px-3 py-2 rounded-md text-xs text-text-main hover:bg-canvas transition-colors"
                    role="menuitem"
                  >
                    Stream Sources
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Viewport Container (1440px max width, calm whitespace) */}
        <main className="flex-1 p-4 md:p-8 max-w-[1440px] w-full mx-auto">
          {children}
        </main>
      </div>

      {/* Modal: Delete Project */}
      {isDeleteProjectModalOpen && selectedProject && (
        <div className="fixed inset-0 z-50 bg-[var(--scrim)] backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl bg-surface border border-danger/30 shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="p-6 space-y-4">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-danger/10 text-danger flex items-center justify-center shrink-0">
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-text-main">Permanently Delete Project</h3>
                  <p className="text-xs text-text-muted mt-1">This operation cannot be undone.</p>
                </div>
                <button
                  onClick={resetDeleteModal}
                  disabled={isDeletingProject}
                  className="ml-auto text-text-muted hover:text-text-main p-1 rounded-md"
                  aria-label="Close"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="rounded-xl border border-danger/25 bg-danger/5 p-4 space-y-1.5 text-xs text-text-muted">
                <div className="text-sm font-semibold text-text-main">{selectedProject.name}</div>
                <div className="font-mono text-[11px] text-text-muted">{selectedProject.id}</div>
                <p className="pt-1 text-[11px] leading-relaxed">
                  Project State, evidence citations, AI memory shards, and Excalidraw visual artifacts will be permanently removed.
                </p>
              </div>

              <form onSubmit={handleDeleteProjectSubmit} className="space-y-3">
                <label htmlFor="delete-confirmation" className="text-xs font-semibold text-text-main block">
                  Type <span className="font-mono text-danger font-bold">DELETE</span> to confirm:
                </label>
                <input
                  id="delete-confirmation"
                  value={deleteProjectConfirmation}
                  onChange={(e) => setDeleteProjectConfirmation(e.target.value)}
                  placeholder="DELETE"
                  autoComplete="off"
                  autoFocus
                  disabled={isDeletingProject}
                  className="w-full px-3 py-2 text-xs rounded-lg bg-canvas border border-border focus:border-danger text-text-main"
                />

                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={resetDeleteModal}
                    disabled={isDeletingProject}
                    className="px-3.5 py-2 text-xs font-semibold text-text-muted hover:text-text-main rounded-lg hover:bg-canvas transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isDeletingProject || deleteProjectConfirmation.trim().toUpperCase() !== "DELETE"}
                    className="px-4 py-2 text-xs font-semibold text-white bg-danger hover:bg-danger/90 rounded-lg transition-colors disabled:opacity-40 flex items-center gap-1.5"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    {isDeletingProject ? "Deleting…" : "Delete Project"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Create Project (4-step Flow) */}
      {isNewProjectModalOpen && (
        <div className="fixed inset-0 z-50 bg-[var(--scrim)] backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl bg-surface border border-border shadow-2xl p-6 space-y-5 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 text-primary flex items-center justify-center font-bold">
                  <FolderPlus className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-text-main">Initialize New Project</h3>
                  <p className="text-xs text-text-muted">
                    Step {createStep} of 4 · Continuous intelligence setup
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
                  className={`h-1 flex-1 rounded-full transition-colors ${
                    s <= createStep ? "bg-primary" : "bg-border"
                  }`}
                />
              ))}
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-4">
              {createStep === 1 && (
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-text-main" htmlFor="new-project-name">
                    1. Project Name <span className="text-danger">*</span>
                  </label>
                  <input
                    id="new-project-name"
                    type="text"
                    required
                    placeholder="e.g. Distributed Core Engine"
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    autoFocus
                    className="w-full px-3 py-2 text-xs rounded-lg bg-canvas border border-border focus:border-primary text-text-main"
                  />
                </div>
              )}

              {createStep === 2 && (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-text-main" htmlFor="new-project-use">
                      2. Scope & Target Vision
                    </label>
                    <textarea
                      id="new-project-use"
                      rows={3}
                      placeholder="High-level mission, core systems, or key deliverable..."
                      value={newProjectUse}
                      onChange={(e) => setNewProjectUse(e.target.value)}
                      className="w-full px-3 py-2 text-xs rounded-lg bg-canvas border border-border focus:border-primary text-text-main resize-none"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-text-main" htmlFor="new-project-context">
                      Initial Context & Constraints <span className="text-text-muted font-normal">(optional)</span>
                    </label>
                    <textarea
                      id="new-project-context"
                      rows={2}
                      placeholder="Tech constraints, assumptions, or existing dependencies..."
                      value={newProjectContext}
                      onChange={(e) => setNewProjectContext(e.target.value)}
                      className="w-full px-3 py-2 text-xs rounded-lg bg-canvas border border-border focus:border-primary text-text-main resize-none"
                    />
                  </div>
                </div>
              )}

              {createStep === 3 && (
                <div className="space-y-2">
                  <span className="text-xs font-semibold text-text-main block">3. Connect Sources</span>
                  {[
                    { id: "google_meet", label: "Google Meet — audio meeting transcripts" },
                    { id: "whatsapp", label: "WhatsApp — real-time discussion bridge" },
                    { id: "excalidraw", label: "Project Atlas — living Excalidraw canvas" },
                  ].map((tool) => (
                    <label
                      key={tool.id}
                      className="flex items-center gap-2.5 p-2.5 rounded-lg border border-border bg-canvas text-xs cursor-pointer hover:border-primary/40 transition-colors"
                    >
                      <input
                        type="checkbox"
                        checked={newProjectTools.includes(tool.id)}
                        onChange={() => toggleTool(tool.id)}
                        className="accent-primary"
                      />
                      <span className="text-text-main font-medium">{tool.label}</span>
                    </label>
                  ))}
                </div>
              )}

              {createStep === 4 && (
                <div className="space-y-2 text-xs">
                  <span className="text-xs font-semibold text-text-main block">4. Confirmation</span>
                  <div className="p-3 rounded-lg bg-canvas border border-border space-y-1">
                    <div className="font-bold text-text-main">{newProjectName || "Untitled Project"}</div>
                    {newProjectUse && <div className="text-text-muted text-[11px]">{newProjectUse}</div>}
                    <div className="text-primary font-mono text-[10px] pt-1">
                      Pipelines: {newProjectTools.join(", ")}
                    </div>
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between pt-2">
                <button
                  type="button"
                  onClick={() => (createStep > 1 ? setCreateStep(createStep - 1) : resetCreateModal())}
                  className="px-3.5 py-2 text-xs font-semibold text-text-muted hover:text-text-main rounded-lg hover:bg-canvas transition-colors"
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
                    className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors disabled:opacity-50"
                  >
                    Continue
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={isCreatingProject || !newProjectName.trim()}
                    className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  >
                    {isCreatingProject ? "Provisioning..." : "Initialize Project"}
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
