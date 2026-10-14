"use client";

import React from "react";
import {
  ArrowDownRight,
  ArrowRight,
  BookOpen,
  FileText,
  Layers3,
  Plus,
  ShieldAlert,
  Sparkles,
  Video,
} from "lucide-react";
import { CandidateKnowledgeItem, Conflict, EvidenceItem, Project, ProjectState } from "@/lib/types";
import type { NavTab } from "@/components/layout/Shell";

interface ProjectPulseViewProps {
  project?: Project | null;
  state: ProjectState | null;
  conflicts: Conflict[];
  evidence: EvidenceItem[];
  candidates?: CandidateKnowledgeItem[];
  history?: Array<{ version_number: number; reason?: string; created_at?: string }>;
  connections?: unknown[];
  activeProjectName?: string;
  projectVersion?: number;
  projects?: Project[];
  currentProjectId?: string;
  onSelectProject?: (projectId: string) => void;
  onNavigateToTab: (tab: NavTab) => void;
  onSyncAtlas?: () => Promise<void> | void;
  onOpenAgentSheet?: () => void;
  onOpenStoryModal?: () => void;
  onReviewConflict?: (conflict: Conflict) => void;
}

const isOpenConflict = (conflict: Conflict) =>
  ["open", "under_review"].includes(conflict.status);

function timeAgo(value?: string | null) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date unavailable";
  const hours = Math.max(0, Math.floor((Date.now() - date.getTime()) / 3_600_000));
  if (hours < 1) return "Just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function ProjectPulseView({
  state,
  conflicts,
  evidence,
  candidates = [],
  activeProjectName,
  projectVersion,
  projects = [],
  currentProjectId,
  onSelectProject,
  onNavigateToTab,
}: ProjectPulseViewProps) {
  const openConflicts = conflicts.filter(isOpenConflict);
  const version = projectVersion || state?.current_version || 1;
  const decisionCount = state?.decisions?.length || 0;
  const title = state?.title || activeProjectName || "Your project workspace";
  const vision = state?.vision?.trim();

  return (
    <main className="mx-auto w-full max-w-7xl px-4 pb-12 pt-6 sm:px-7 sm:pt-9 lg:px-10">
      <header className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-text-dim">
            <span className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-border bg-surface text-text-muted">
              <Layers3 className="h-3.5 w-3.5" />
            </span>
            Workspace overview
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-main sm:text-[30px]">Good to have you back.</h1>
          <p className="mt-1.5 max-w-2xl text-sm text-text-muted">A clear view of what Synora remembers and what needs your attention.</p>
        </div>
        {projects.length > 0 && (
          <label className="flex h-10 items-center gap-2 rounded-lg border border-border bg-surface px-3 text-xs shadow-xs focus-within:border-border-active">
            <span className="text-text-dim">Project</span>
            <select
              value={currentProjectId || ""}
              onChange={(event) => onSelectProject?.(event.target.value)}
              className="max-w-[190px] cursor-pointer appearance-none bg-transparent pr-1 font-medium text-text-main outline-none"
              aria-label="Select project"
            >
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
            <ArrowDownRight className="h-3.5 w-3.5 text-text-dim" />
          </label>
        )}
      </header>

      <section className="relative overflow-hidden rounded-xl border border-[#222] bg-[#080808] p-5 text-white shadow-sm sm:p-7 lg:p-8">
        <div aria-hidden className="pointer-events-none absolute -right-16 -top-24 h-72 w-72 rounded-full bg-white/[0.07] blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-white/20 to-transparent" />
        <div className="relative grid gap-7 lg:grid-cols-[minmax(0,1fr)_290px] lg:items-center">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.06] px-2.5 py-1 text-[11px] font-medium text-white/75">
              <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white/60" /><span className="relative inline-flex h-2 w-2 rounded-full bg-white" /></span>
              Synora is keeping project memory up to date
            </div>
            <h2 className="mt-4 max-w-3xl text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">{title}</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-white/65">
              {vision || "Bring conversations, decisions, and project evidence together in one source of truth."}
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <button onClick={() => onNavigateToTab("meetings")} className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3.5 text-xs font-semibold text-black transition hover:bg-white/90">
                <Plus className="h-3.5 w-3.5" /> Open meetings
              </button>
              <button onClick={() => onNavigateToTab("excalidraw")} className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/20 bg-white/[0.05] px-3.5 text-xs font-medium text-white transition hover:bg-white/10">
                View living atlas <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2.5 lg:border-l lg:border-white/10 lg:pl-6">
            <div className="rounded-lg border border-white/10 bg-white/[0.045] p-3.5">
              <div className="text-[10px] uppercase tracking-[0.12em] text-white/45">Memory version</div>
              <div className="mt-2 text-2xl font-semibold tabular-nums">v{version}</div>
              <div className="mt-1 text-[10px] text-white/45">Current project state</div>
            </div>
            <div className="rounded-lg border border-white/10 bg-white/[0.045] p-3.5">
              <div className="text-[10px] uppercase tracking-[0.12em] text-white/45">Last update</div>
              <div className="mt-2 text-sm font-semibold">{timeAgo(state?.updated_at)}</div>
              <div className="mt-1 text-[10px] text-white/45">Approved project memory</div>
            </div>
            <div className="col-span-2 flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.045] px-3.5 py-3">
              <div className="flex items-center gap-2.5">
                <span className="grid h-8 w-8 place-items-center rounded-md bg-white/10"><Sparkles className="h-4 w-4 text-white/75" /></span>
                <div><div className="text-xs font-medium">Evidence-backed memory</div><div className="mt-0.5 text-[10px] text-white/45">Every decision stays traceable</div></div>
              </div>
              <span className="rounded-full border border-white/15 px-2 py-1 text-[9px] font-medium uppercase tracking-wider text-white/60">Active</span>
            </div>
          </div>
        </div>
      </section>

      <section aria-label="Project metrics" className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "Approved decisions", value: decisionCount, note: "In project memory", icon: BookOpen, tab: "state" as NavTab },
          { label: "Evidence collected", value: evidence.length, note: "Across connected sources", icon: FileText, tab: "sources" as NavTab },
          { label: "Needs review", value: openConflicts.length, note: openConflicts.length ? "Review conflicting context" : "You’re all caught up", icon: ShieldAlert, tab: "context" as NavTab },
          { label: "New insights", value: candidates.length, note: "See extracted context", icon: Sparkles, tab: "context" as NavTab },
        ].map(({ label, value, note, icon: Icon, tab }) => (
          <button key={label} onClick={() => onNavigateToTab(tab)} className="group rounded-xl border border-border bg-surface p-4 text-left shadow-xs transition hover:-translate-y-0.5 hover:border-border-active hover:shadow-sm sm:p-5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-text-muted">{label}</span>
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-surface-muted text-text-muted transition group-hover:bg-black group-hover:text-white"><Icon className="h-4 w-4" /></span>
            </div>
            <div className="mt-4 flex items-end justify-between gap-2">
              <span className="text-3xl font-semibold tracking-tight tabular-nums text-text-main">{value}</span>
              <ArrowRight className="mb-1 h-4 w-4 text-text-dim transition group-hover:translate-x-0.5 group-hover:text-text-main" />
            </div>
            <div className="mt-1 text-[11px] text-text-dim">{note}</div>
          </button>
        ))}
      </section>

    </main>
  );
}
