"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronDown,
  Command,
  FolderKanban,
  FolderPlus,
  Home,
  Layers3,
  Menu,
  PenTool,
  Plug,
  Plus,
  Search,
  Settings2,
  Sparkles,
  Trash2,
  UserRound,
  Video,
  X,
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

const NAV_ITEMS: Array<{
  id: NavTab;
  label: string;
  hint: string;
  shortcut: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { id: "overview", label: "Home", hint: "Start here", shortcut: "1", icon: Home },
  { id: "state", label: "State", hint: "Authoritative brain", shortcut: "2", icon: Layers3 },
  { id: "excalidraw", label: "Atlas", hint: "Living visual brain", shortcut: "3", icon: PenTool },
  { id: "meetings", label: "Meetings", hint: "Conversation memory", shortcut: "4", icon: Video },
  { id: "sources", label: "Sources", hint: "Connected streams", shortcut: "5", icon: Plug },
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
  const [railOpen, setRailOpen] = useState(true);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [projectSearch, setProjectSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createStep, setCreateStep] = useState(1);
  const [newName, setNewName] = useState("");
  const [newBrief, setNewBrief] = useState("");
  const [newSources, setNewSources] = useState<string[]>(["google_meet", "whatsapp", "excalidraw"]);
  const [creating, setCreating] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteText, setDeleteText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);

  const selectedProject =
    activeProject || projects.find((project) => project.id === currentProjectId) || null;

  const filteredProjects = useMemo(() => {
    const q = projectSearch.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (project) =>
        project.name.toLowerCase().includes(q) ||
        project.id.toLowerCase().includes(q) ||
        (project.description || "").toLowerCase().includes(q)
    );
  }, [projects, projectSearch]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setProjectMenuOpen(false);
        setActivityOpen(false);
        setUserOpen(false);
        setCreateOpen(false);
        setDeleteOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggleSource = (source: string) => {
    setNewSources((current) =>
      current.includes(source) ? current.filter((item) => item !== source) : [...current, source]
    );
  };

  const resetCreate = () => {
    setCreateOpen(false);
    setCreateStep(1);
    setNewName("");
    setNewBrief("");
    setNewSources(["google_meet", "whatsapp", "excalidraw"]);
  };

  const submitCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newName.trim() || !onCreateProject) return;
    try {
      setCreating(true);
      await onCreateProject(newName.trim(), newBrief.trim() || undefined, newSources);
      resetCreate();
      setProjectMenuOpen(false);
    } catch (error: any) {
      alert(error?.message || "Project creation failed.");
    } finally {
      setCreating(false);
    }
  };

  const submitDelete = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedProject || deleteText.trim().toUpperCase() !== "DELETE" || !onDeleteProject) return;
    try {
      setDeleting(true);
      await onDeleteProject(selectedProject.id);
      setDeleteOpen(false);
      setDeleteText("");
    } catch (error: any) {
      alert(error?.message || "Project deletion failed.");
    } finally {
      setDeleting(false);
    }
  };

  const navTo = (tab: NavTab) => {
    setActivityOpen(false);
    setUserOpen(false);
    onTabChange(tab);
  };

  // Home is a full-bleed landing page: no rail, no topbar, only content.
  const isHome = currentTab === "overview";

  return (
    <div className="synora-shell min-h-screen bg-canvas text-text-main">
      {!isHome && (
      <aside
        className={
          "synora-rail fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-white/90 backdrop-blur-xl transition-all duration-300 " +
          (railOpen ? "w-[232px]" : "w-[76px]")
        }
      >
        <div className="flex h-16 items-center gap-3 border-b border-border px-4">
          <button
            type="button"
            onClick={() => setRailOpen((value) => !value)}
            aria-label={railOpen ? "Collapse navigation" : "Expand navigation"}
            className="group relative grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-primary/20 bg-primary-soft text-primary transition-all hover:-translate-y-0.5 hover:border-primary/40"
          >
            <span className="text-sm font-black tracking-tight">S</span>
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-primary animate-pulse-live" />
          </button>

          {railOpen && (
            <div className="min-w-0 animate-in fade-in">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold tracking-tight">Synora</span>
                <span className="rounded-full border border-border bg-canvas px-1.5 py-0.5 font-mono text-[8px] font-bold tracking-[0.14em] text-text-muted">
                  INTELLIGENCE
                </span>
              </div>
              <div className="mt-0.5 truncate text-[10px] text-text-dim">
                Project memory that keeps moving
              </div>
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-2.5 py-4">
          <div className={railOpen ? "px-2 pb-2 text-[9px] font-semibold uppercase tracking-[0.18em] text-text-dim" : "sr-only"}>
            Navigate
          </div>

          <nav className="space-y-1" aria-label="Primary navigation">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active = currentTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navTo(item.id)}
                  title={!railOpen ? item.label : undefined}
                  className={
                    "group relative flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-all duration-200 " +
                    (active
                      ? "border border-primary/15 bg-primary-soft text-text-main shadow-xs"
                      : "border border-transparent text-text-muted hover:-translate-y-px hover:bg-surface-soft hover:text-text-main")
                  }
                >
                  {active && (
                    <span className="absolute inset-y-2 left-0 w-0.5 rounded-r-full bg-primary" />
                  )}
                  <span
                    className={
                      "grid h-8 w-8 shrink-0 place-items-center rounded-lg transition-colors " +
                      (active
                        ? "bg-white text-primary shadow-xs ring-1 ring-primary/10"
                        : "bg-transparent text-text-muted group-hover:bg-white group-hover:text-primary")
                    }
                  >
                    <Icon className="h-4 w-4" />
                  </span>

                  {railOpen && (
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-semibold">{item.label}</span>
                      <span className="mt-0.5 block truncate text-[10px] text-text-dim">{item.hint}</span>
                    </span>
                  )}

                  {railOpen && (
                    <kbd className="rounded-md border border-border bg-white px-1.5 py-0.5 font-mono text-[8px] text-text-dim opacity-0 transition-opacity group-hover:opacity-100">
                      {item.shortcut}
                    </kbd>
                  )}

                  {item.id === "overview" && openConflictsCount > 0 && (
                    <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-danger shadow-[0_0_0_3px_rgba(220,38,38,0.10)]" />
                  )}

                  {item.id === "excalidraw" && unknownContextCount > 0 && railOpen && (
                    <span className="rounded-full border border-warning/20 bg-warning/10 px-1.5 py-0.5 font-mono text-[8px] font-semibold text-warning">
                      {unknownContextCount}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          <div className="my-5 h-px bg-border-subtle" />

          {railOpen && (
            <div className="px-2 text-[9px] font-semibold uppercase tracking-[0.18em] text-text-dim">
              Workspace
            </div>
          )}

          <div className="mt-2 space-y-1">
            <button
              type="button"
              onClick={() => navTo("settings")}
              className={
                "group flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-xs transition-all " +
                (currentTab === "settings"
                  ? "border-border bg-surface-soft text-text-main"
                  : "border-transparent text-text-muted hover:border-border hover:bg-surface-soft hover:text-text-main")
              }
              title={!railOpen ? "Settings" : undefined}
            >
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-canvas text-text-muted group-hover:text-primary">
                <Settings2 className="h-4 w-4" />
              </span>
              {railOpen && <span className="font-medium">Settings</span>}
            </button>

            {onOpenStoryModal && (
              <button
                type="button"
                onClick={onOpenStoryModal}
                className="group flex w-full items-center gap-3 rounded-xl border border-transparent px-3 py-2.5 text-xs text-text-muted transition-all hover:border-primary/10 hover:bg-primary-soft hover:text-primary"
                title={!railOpen ? "How Synora works" : undefined}
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-canvas text-primary group-hover:bg-white">
                  <Sparkles className="h-4 w-4" />
                </span>
                {railOpen && (
                  <span>
                    <span className="block font-medium">How Synora works</span>
                    <span className="block text-[10px] text-text-dim">See the intelligence pipeline</span>
                  </span>
                )}
              </button>
            )}
          </div>
        </div>

        <div className="border-t border-border bg-surface-soft/60 p-3">
          {onOpenAgentSheet && (
            <button
              type="button"
              onClick={onOpenAgentSheet}
              className="agent-beacon group w-full rounded-xl border border-primary/15 bg-white px-3 py-2.5 text-left shadow-xs transition-all hover:-translate-y-0.5 hover:border-primary/30"
            >
              <div className="flex items-center gap-2">
                <span className="relative grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary-soft text-primary">
                  <Zap className="h-3.5 w-3.5" />
                  <span className="absolute inset-0 rounded-full ring-1 ring-primary/10 pulse-ring" />
                </span>
                {railOpen && (
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5 text-[10px] font-semibold text-text-main">
                      Synora is watching
                      <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                    </span>
                    <span className="mt-0.5 block truncate font-mono text-[9px] text-text-dim">
                      state v{projectVersion} · continuous cognition
                    </span>
                  </span>
                )}
              </div>
            </button>
          )}
        </div>
      </aside>
      )}

      <div className={isHome ? "" : railOpen ? "ml-[232px] transition-all duration-300" : "ml-[76px] transition-all duration-300"}>
        {!isHome && (
        <header className="synora-topbar sticky top-0 z-30 border-b border-border/80 bg-white/80 backdrop-blur-xl">
          <div className="flex h-[68px] items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-2.5">
              <button
                type="button"
                onClick={() => setRailOpen((value) => !value)}
                className="grid h-9 w-9 place-items-center rounded-xl border border-border bg-white text-text-muted shadow-xs hover:text-text-main lg:hidden"
                aria-label="Toggle navigation"
              >
                <Menu className="h-4 w-4" />
              </button>

              <div className="relative">
                <button
                  type="button"
                  onClick={() => setProjectMenuOpen((value) => !value)}
                  className="group flex max-w-[58vw] items-center gap-3 rounded-2xl border border-border bg-white px-3 py-2 shadow-xs transition-all hover:-translate-y-px hover:border-border-active hover:shadow-sm"
                >
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-canvas text-primary ring-1 ring-border">
                    <FolderKanban className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 text-left">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-xs font-semibold text-text-main">
                        {selectedProject?.name || "Select a project"}
                      </span>
                      <span className="shrink-0 rounded-full border border-primary/15 bg-primary-soft px-1.5 py-0.5 font-mono text-[8px] font-semibold text-primary">
                        v{projectVersion}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-[10px] text-text-dim">
                      {workspaceName} · project intelligence
                    </span>
                  </span>
                  <ChevronDown className="h-3.5 w-3.5 shrink-0 text-text-dim transition-transform group-hover:text-text-main" />
                </button>

                {projectMenuOpen && (
                  <div className="absolute left-0 top-14 z-50 w-[340px] max-w-[calc(100vw-24px)] rounded-2xl border border-border bg-white p-2.5 shadow-xl animate-in fade-in zoom-in-95">
                    <div className="flex items-center gap-2 border-b border-border-subtle px-1 pb-2">
                      <Search className="h-3.5 w-3.5 text-text-dim" />
                      <input
                        value={projectSearch}
                        onChange={(event) => setProjectSearch(event.target.value)}
                        placeholder="Search projects"
                        className="w-full bg-transparent py-1 text-xs text-text-main placeholder:text-text-dim focus:outline-none"
                        autoFocus
                      />
                      <kbd className="rounded-md border border-border bg-canvas px-1.5 py-0.5 font-mono text-[8px] text-text-dim">⌘P</kbd>
                    </div>

                    <div className="px-2 pb-1 pt-3 text-[9px] font-semibold uppercase tracking-[0.18em] text-text-dim">
                      {filteredProjects.length ? "Projects" : "No matching projects"}
                    </div>

                    <div className="max-h-60 space-y-1 overflow-y-auto">
                      {filteredProjects.map((project) => {
                        const selected = project.id === currentProjectId;
                        return (
                          <button
                            key={project.id}
                            type="button"
                            onClick={() => {
                              onSelectProject?.(project.id);
                              setProjectMenuOpen(false);
                              setProjectSearch("");
                            }}
                            className={
                              "flex w-full items-center justify-between rounded-xl border px-3 py-2.5 text-left transition-all " +
                              (selected
                                ? "border-primary/15 bg-primary-soft"
                                : "border-transparent hover:border-border hover:bg-surface-soft")
                            }
                          >
                            <span className="min-w-0">
                              <span className="block truncate text-xs font-semibold text-text-main">{project.name}</span>
                              <span className="mt-0.5 block truncate font-mono text-[9px] text-text-dim">{project.id}</span>
                            </span>
                            {selected && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                          </button>
                        );
                      })}
                    </div>

                    <div className="mt-2 border-t border-border-subtle pt-2">
                      <button
                        type="button"
                        onClick={() => {
                          setProjectMenuOpen(false);
                          setCreateOpen(true);
                          setCreateStep(1);
                        }}
                        className="flex w-full items-center justify-between rounded-xl bg-primary px-3 py-2.5 text-xs font-semibold text-white shadow-sm transition-all hover:-translate-y-px hover:bg-primary-hover"
                      >
                        <span className="flex items-center gap-2">
                          <Plus className="h-3.5 w-3.5" />
                          Create a new project
                        </span>
                        <span className="rounded-md bg-white/15 px-1.5 py-0.5 text-[8px] uppercase tracking-[0.12em]">Start</span>
                      </button>

                      {selectedProject && onDeleteProject && (
                        <button
                          type="button"
                          onClick={() => {
                            setProjectMenuOpen(false);
                            setDeleteOpen(true);
                          }}
                          className="mt-1.5 flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2 text-xs font-medium text-danger transition-colors hover:bg-danger/5"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Delete current project
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>

              <div className="hidden items-center gap-1.5 text-[10px] text-text-dim xl:flex">
                <span className="h-1 w-1 rounded-full bg-border-active" />
                <span>State v{projectVersion}</span>
                <span className="h-1 w-1 rounded-full bg-primary" />
                <span>Live</span>
              </div>
            </div>

            <div className="flex items-center gap-1.5 sm:gap-2">
              {onOpenCommandPalette && (
                <button
                  type="button"
                  onClick={onOpenCommandPalette}
                  className="hidden h-9 items-center gap-2 rounded-xl border border-border bg-white px-3 text-[10px] font-medium text-text-muted shadow-xs transition-all hover:border-border-active hover:text-text-main sm:flex"
                >
                  <Command className="h-3.5 w-3.5 text-primary" />
                  <span>Search Synora</span>
                  <kbd className="rounded-md border border-border bg-canvas px-1.5 py-0.5 font-mono text-[8px]">⌘K</kbd>
                </button>
              )}

              {onOpenAgentSheet && (
                <button
                  type="button"
                  onClick={onOpenAgentSheet}
                  className="agent-status-button hidden h-9 items-center gap-2 rounded-full border border-primary/15 bg-primary-soft px-3 text-[10px] font-semibold text-text-main transition-all hover:border-primary/30 hover:bg-primary/10 md:flex"
                >
                  <span className="relative h-2 w-2">
                    <span className="absolute inset-0 rounded-full bg-primary pulse-ring" />
                    <span className="relative block h-2 w-2 rounded-full bg-primary" />
                  </span>
                  Synora is watching
                </button>
              )}

              {openConflictsCount > 0 && (
                <button
                  type="button"
                  onClick={() => navTo("overview")}
                  className="hidden items-center gap-1.5 rounded-full border border-danger/15 bg-danger/5 px-2.5 py-2 text-[10px] font-semibold text-danger sm:flex"
                >
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {openConflictsCount}
                </button>
              )}

              <div className="relative">
                <button
                  type="button"
                  onClick={() => {
                    setActivityOpen((value) => !value);
                    setUserOpen(false);
                  }}
                  className="grid h-9 w-9 place-items-center rounded-xl border border-transparent text-text-muted transition-colors hover:border-border hover:bg-white hover:text-text-main"
                  aria-label="Notifications"
                >
                  <span className="relative">
                    <Activity className="h-4 w-4" />
                    {notifications.length > 0 && (
                      <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-warning ring-2 ring-white" />
                    )}
                  </span>
                </button>

                {activityOpen && (
                  <div className="absolute right-0 top-12 z-50 w-80 max-w-[calc(100vw-20px)] rounded-2xl border border-border bg-white p-2.5 shadow-xl animate-in fade-in zoom-in-95">
                    <div className="flex items-center justify-between px-2 pb-2">
                      <div>
                        <div className="text-xs font-semibold">System signals</div>
                        <div className="text-[9px] uppercase tracking-[0.16em] text-text-dim">Only what needs attention</div>
                      </div>
                      <span className="h-2 w-2 rounded-full bg-primary" />
                    </div>

                    <div className="space-y-1">
                      {notifications.length === 0 ? (
                        <div className="rounded-xl border border-dashed border-border bg-canvas p-5 text-center text-[11px] text-text-muted">
                          Everything looks healthy.
                        </div>
                      ) : (
                        notifications.map((item, index) => (
                          <div key={index} className="rounded-xl border border-border-subtle bg-surface-soft/50 p-3">
                            <div className="text-xs font-semibold">{item.title}</div>
                            {item.detail && <div className="mt-1 text-[10px] leading-relaxed text-text-muted">{item.detail}</div>}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>

              <div className="relative">
                <button
                  type="button"
                  onClick={() => {
                    setUserOpen((value) => !value);
                    setActivityOpen(false);
                  }}
                  className="grid h-9 w-9 place-items-center rounded-xl border border-border bg-white text-text-muted shadow-xs transition-all hover:border-border-active hover:text-text-main"
                  aria-label="User menu"
                >
                  <span className="text-[10px] font-bold">{currentUserInitial || "U"}</span>
                </button>

                {userOpen && (
                  <div className="absolute right-0 top-12 z-50 w-60 rounded-2xl border border-border bg-white p-2 shadow-xl animate-in fade-in zoom-in-95">
                    <div className="rounded-xl bg-surface-soft px-3 py-2.5">
                      <div className="flex items-center gap-2 text-xs font-semibold">
                        <UserRound className="h-3.5 w-3.5 text-primary" />
                        {currentUserName || "Lead Architect"}
                      </div>
                      <div className="mt-0.5 text-[10px] text-text-dim">{workspaceName}</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setUserOpen(false);
                        navTo("settings");
                      }}
                      className="mt-1 w-full rounded-xl px-3 py-2 text-left text-xs font-medium text-text-muted hover:bg-surface-soft hover:text-text-main"
                    >
                      Workspace settings
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setUserOpen(false);
                        navTo("sources");
                      }}
                      className="w-full rounded-xl px-3 py-2 text-left text-xs font-medium text-text-muted hover:bg-surface-soft hover:text-text-main"
                    >
                      Connected sources
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </header>
        )}

        <main className="mx-auto w-full max-w-[1500px] px-4 pb-12 pt-5 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>

      {createOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-[var(--scrim)] p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg overflow-hidden rounded-3xl border border-border bg-white shadow-xl animate-in slide-in-from-bottom">
            <div className="flex items-start justify-between border-b border-border-subtle px-6 py-5">
              <div>
                <div className="flex items-center gap-2">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary-soft text-primary">
                    <FolderPlus className="h-4 w-4" />
                  </span>
                  <div>
                    <h2 className="text-sm font-semibold">Create a project intelligence space</h2>
                    <p className="mt-0.5 text-[10px] text-text-dim">A lightweight setup. Synora can learn from the rest.</p>
                  </div>
                </div>
              </div>
              <button type="button" onClick={resetCreate} className="rounded-lg p-1.5 text-text-dim hover:bg-canvas hover:text-text-main">
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={submitCreate}>
              <div className="px-6 py-6">
                <div className="mb-5 flex items-center gap-1.5">
                  {[1, 2].map((step) => (
                    <span
                      key={step}
                      className={
                        "h-1.5 flex-1 rounded-full transition-colors " +
                        (step <= createStep ? "bg-primary" : "bg-border")
                      }
                    />
                  ))}
                </div>

                {createStep === 1 ? (
                  <div className="space-y-4">
                    <label className="block">
                      <span className="text-xs font-semibold">Project name</span>
                      <input
                        autoFocus
                        value={newName}
                        onChange={(event) => setNewName(event.target.value)}
                        placeholder="e.g. Synora Mobile Platform"
                        className="mt-2 w-full rounded-xl border border-border bg-canvas px-3.5 py-3 text-sm text-text-main placeholder:text-text-dim focus:border-primary focus:outline-none"
                        required
                      />
                    </label>

                    <label className="block">
                      <span className="text-xs font-semibold">One-line brief</span>
                      <textarea
                        rows={4}
                        value={newBrief}
                        onChange={(event) => setNewBrief(event.target.value)}
                        placeholder="What are you building, changing, or trying to solve?"
                        className="mt-2 w-full resize-none rounded-xl border border-border bg-canvas px-3.5 py-3 text-sm text-text-main placeholder:text-text-dim focus:border-primary focus:outline-none"
                      />
                    </label>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div>
                      <div className="text-xs font-semibold">Connect the streams that matter</div>
                      <p className="mt-1 text-[10px] leading-relaxed text-text-muted">
                        You can change these later. Synora will continuously turn them into project evidence.
                      </p>
                    </div>

                    {[
                      ["google_meet", "Google Meet", "Meeting transcripts"],
                      ["whatsapp", "WhatsApp", "Discussion streams"],
                      ["excalidraw", "Project Atlas", "Living visual workspace"],
                    ].map(([id, label, detail]) => {
                      const active = newSources.includes(id);
                      return (
                        <button
                          key={id}
                          type="button"
                          onClick={() => toggleSource(id)}
                          className={
                            "flex w-full items-center justify-between rounded-2xl border px-4 py-3 text-left transition-all " +
                            (active
                              ? "border-primary/20 bg-primary-soft"
                              : "border-border bg-surface hover:bg-surface-soft")
                          }
                        >
                          <span>
                            <span className="block text-xs font-semibold">{label}</span>
                            <span className="mt-0.5 block text-[10px] text-text-muted">{detail}</span>
                          </span>
                          <span
                            className={
                              "grid h-7 w-7 place-items-center rounded-full border transition-all " +
                              (active ? "border-primary bg-primary text-white" : "border-border bg-white text-text-dim")
                            }
                          >
                            <Check className="h-3.5 w-3.5" />
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between border-t border-border-subtle bg-surface-soft/60 px-6 py-4">
                <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-text-dim">
                  Step {createStep} of 2
                </span>
                <div className="flex items-center gap-2">
                  <button type="button" onClick={resetCreate} className="rounded-xl px-3 py-2 text-xs font-semibold text-text-muted hover:bg-white hover:text-text-main">
                    Cancel
                  </button>
                  {createStep === 2 && (
                    <button
                      type="button"
                      onClick={() => setCreateStep(1)}
                      className="rounded-xl border border-border bg-white px-3 py-2 text-xs font-semibold text-text-main hover:bg-canvas"
                    >
                      Back
                    </button>
                  )}
                  {createStep === 1 ? (
                    <button
                      type="button"
                      disabled={!newName.trim()}
                      onClick={() => setCreateStep(2)}
                      className="rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-white shadow-sm transition-all hover:-translate-y-px hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Continue
                    </button>
                  ) : (
                    <button
                      type="submit"
                      disabled={creating}
                      className="rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-white shadow-sm transition-all hover:-translate-y-px hover:bg-primary-hover disabled:opacity-50"
                    >
                      {creating ? "Creating…" : "Create project"}
                    </button>
                  )}
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {deleteOpen && selectedProject && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-[var(--scrim)] p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-3xl border border-danger/20 bg-white p-6 shadow-xl animate-in slide-in-from-bottom">
            <div className="flex items-start gap-3">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-danger/5 text-danger">
                <Trash2 className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <h2 className="text-sm font-semibold">Delete {selectedProject.name}?</h2>
                <p className="mt-1 text-[10px] leading-relaxed text-text-muted">
                  This permanently removes the project state, evidence references and visual artifact. This cannot be undone.
                </p>
              </div>
              <button type="button" onClick={() => setDeleteOpen(false)} className="ml-auto rounded-lg p-1.5 text-text-dim hover:bg-canvas hover:text-text-main">
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={submitDelete} className="mt-5 space-y-3">
              <label className="block">
                <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
                  Type DELETE to confirm
                </span>
                <input
                  autoFocus
                  value={deleteText}
                  onChange={(event) => setDeleteText(event.target.value)}
                  className="mt-2 w-full rounded-xl border border-border bg-canvas px-3 py-2.5 text-sm focus:border-danger focus:outline-none"
                  placeholder="DELETE"
                />
              </label>

              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setDeleteOpen(false)}
                  className="rounded-xl px-3 py-2 text-xs font-semibold text-text-muted hover:bg-canvas hover:text-text-main"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={deleteText.trim().toUpperCase() !== "DELETE" || deleting}
                  className="rounded-xl bg-danger px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {deleting ? "Deleting…" : "Delete project"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
