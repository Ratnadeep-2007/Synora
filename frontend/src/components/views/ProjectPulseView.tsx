"use client";

import React from "react";
import {
  BrainCircuit,
  Layers3,
  MessageSquareText,
  Settings2,
  Video,
  ArrowRight,
  Radio,
  ChevronDown,
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
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
  onSyncAtlas?: () => Promise<void> | void;
  onOpenAgentSheet?: () => void;
  onOpenStoryModal?: () => void;
  onReviewConflict?: (conflict: Conflict) => void;
}

const DESTINATIONS: Array<{
  tab: NavTab;
  title: string;
  detail: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { tab: "state", title: "State", detail: "Authoritative memory — approve decisions and requirements.", icon: BrainCircuit },
  { tab: "excalidraw", title: "Atlas", detail: "Living visual brain drawn from memory.", icon: Layers3 },
  { tab: "meetings", title: "Meetings", detail: "Conversation memory, transcripts, and canvases.", icon: Video },
  { tab: "sources", title: "Sources", detail: "Connected streams feeding evidence.", icon: MessageSquareText },
  { tab: "settings", title: "Settings", detail: "Workspace, identity, and integrations.", icon: Settings2 },
];

const FLOW_STAGES = ["Sources", "Evidence", "State", "Atlas"];

export function ProjectPulseView({
  state,
  conflicts,
  evidence,
  activeProjectName,
  projectVersion,
  projects = [],
  currentProjectId,
  onSelectProject,
  onNavigateToTab,
}: ProjectPulseViewProps) {
  const openConflicts = conflicts.filter(
    (c) => c.status === "open" || c.status === "unresolved" || c.status === "under_review"
  ).length;
  const version = projectVersion || state?.current_version || 1;

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-10">
      <style>{`
        @keyframes synora-rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes synora-drift { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(24px,-14px) scale(1.06); } }
        @keyframes synora-ping { 0% { transform: scale(1); opacity: .7; } 80%,100% { transform: scale(2.1); opacity: 0; } }
        @keyframes synora-flow { to { stroke-dashoffset: -28; } }
        @keyframes synora-node { 0%,100% { opacity: 1; } 50% { opacity: .45; } }
        @keyframes synora-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-7px); } }
        .synora-rise { animation: synora-rise .55s cubic-bezier(.22,.8,.3,1) both; }
        .synora-d1 { animation-delay: .06s; } .synora-d2 { animation-delay: .14s; }
        .synora-d3 { animation-delay: .22s; } .synora-d4 { animation-delay: .3s; }
        .synora-d5 { animation-delay: .38s; }
        .synora-orb { animation: synora-drift 9s ease-in-out infinite; }
        .synora-ping { animation: synora-ping 2s cubic-bezier(0,0,.2,1) infinite; }
        .synora-flow { stroke-dasharray: 7 7; animation: synora-flow 1.4s linear infinite; }
        .synora-node { animation: synora-node 2.6s ease-in-out infinite; }
        .synora-float { animation: synora-float 5s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .synora-rise, .synora-orb, .synora-ping, .synora-flow, .synora-node, .synora-float { animation: none; }
        }
      `}</style>

      {/* Brand row (chrome is hidden on Home, so the page carries its own mark) */}
      <div className="synora-rise mb-6 flex items-center gap-2">
        <span className="grid h-9 w-9 place-items-center rounded-xl border border-primary/20 bg-primary-soft text-sm font-black text-primary">S</span>
        <div>
          <div className="text-sm font-semibold tracking-tight">Synora</div>
          <div className="text-[10px] text-text-dim">Project memory that keeps moving</div>
        </div>
      </div>

      {/* Hero */}
      <section className="relative overflow-hidden rounded-3xl border border-border bg-canvas px-8 py-12 sm:px-12">
        <div aria-hidden className="pointer-events-none absolute -top-20 -right-16 h-64 w-64 rounded-full bg-primary/10 blur-3xl synora-orb" />
        <div aria-hidden className="pointer-events-none absolute -bottom-24 -left-10 h-56 w-56 rounded-full bg-primary/5 blur-3xl synora-orb" />

        <div className="relative grid items-center gap-10 lg:grid-cols-[1.1fr_.9fr]">
          <div>
            <div className="synora-rise flex flex-wrap items-center gap-2 text-[11px] font-medium">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background px-2.5 py-1 text-text-muted">
                <span className="relative flex h-2 w-2">
                  <span className="synora-ping absolute inline-flex h-full w-full rounded-full bg-primary" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                </span>
                <Radio className="h-3 w-3" />
                Synora is watching
              </span>
              <span className="rounded-full border border-border bg-background px-2.5 py-1 text-text-muted">
                State v{version}
              </span>
            </div>

            <h1 className="synora-rise synora-d1 mt-4 text-3xl sm:text-5xl font-semibold tracking-tight text-text-main">
              {activeProjectName || "Synora Core"}
            </h1>
            <p className="synora-rise synora-d2 mt-3 max-w-xl text-sm leading-relaxed text-text-muted">
              Conversations become evidence, evidence becomes memory, memory draws
              itself. Pick a project, then pick where to go.
            </p>

            {projects.length > 0 && (
              <label className="synora-rise synora-d2 mt-5 inline-flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 text-xs shadow-xs">
                <span className="text-text-dim">Project</span>
                <span className="relative inline-flex items-center">
                  <select
                    value={currentProjectId || ""}
                    onChange={(e) => onSelectProject?.(e.target.value)}
                    className="appearance-none bg-transparent pr-5 font-medium text-text-main outline-none"
                    aria-label="Select project"
                  >
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-0 h-3.5 w-3.5 text-text-dim" />
                </span>
              </label>
            )}

            <div className="synora-rise synora-d3 mt-5 flex flex-wrap items-center gap-3 text-xs text-text-muted">
              <span className="rounded-lg border border-border bg-background px-3 py-1.5">
                {evidence.length} evidence
              </span>
              <span className="rounded-lg border border-border bg-background px-3 py-1.5">
                {openConflicts} open conflicts
              </span>
              <span className="rounded-lg border border-border bg-background px-3 py-1.5">
                v{version} memory
              </span>
            </div>
          </div>

          {/* Animated pipeline visual */}
          <div className="synora-rise synora-d2 synora-float" aria-hidden>
            <svg viewBox="0 0 400 210" className="h-auto w-full" role="presentation">
              <defs>
                <linearGradient id="synoraPipe" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0" stopColor="currentColor" stopOpacity=".15" />
                  <stop offset=".5" stopColor="currentColor" stopOpacity=".55" />
                  <stop offset="1" stopColor="currentColor" stopOpacity=".15" />
                </linearGradient>
              </defs>
              <g className="text-primary">
                <line x1="70" y1="105" x2="140" y2="105" stroke="url(#synoraPipe)" strokeWidth="2.5" className="synora-flow" />
                <line x1="170" y1="105" x2="240" y2="105" stroke="url(#synoraPipe)" strokeWidth="2.5" className="synora-flow" />
                <line x1="270" y1="105" x2="340" y2="105" stroke="url(#synoraPipe)" strokeWidth="2.5" className="synora-flow" />
                {[
                  { cx: 55, label: "Sources" },
                  { cx: 155, label: "Evidence" },
                  { cx: 255, label: "State" },
                  { cx: 355, label: "Atlas" },
                ].map((n, i) => (
                  <g key={n.label} className="synora-node" style={{ animationDelay: `${i * 0.4}s` }}>
                    <circle cx={n.cx} cy="105" r="15" fill="currentColor" fillOpacity=".12" stroke="currentColor" strokeWidth="2" />
                    <circle cx={n.cx} cy="105" r="5" fill="currentColor" />
                    <text x={n.cx} y="140" textAnchor="middle" fontSize="11" fill="currentColor" opacity=".75">{n.label}</text>
                  </g>
                ))}
              </g>
            </svg>
            <div className="mt-1 flex justify-between text-[10px] uppercase tracking-[0.16em] text-text-dim">
              {FLOW_STAGES.map((s) => (<span key={s}>{s}</span>))}
            </div>
          </div>
        </div>
      </section>

      {/* Destinations */}
      <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {DESTINATIONS.map((dest, i) => (
          <button
            key={dest.tab}
            onClick={() => onNavigateToTab(dest.tab)}
            className={`synora-rise group rounded-2xl border border-border bg-canvas p-5 text-left transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-sm synora-d${Math.min(i, 5)}`}
          >
            <dest.icon className="h-5 w-5 text-primary" />
            <div className="mt-3 flex items-center gap-1.5 font-medium text-text-main">
              {dest.title}
              <ArrowRight className="h-3.5 w-3.5 text-text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
            </div>
            <p className="mt-1 text-xs leading-relaxed text-text-muted">{dest.detail}</p>
          </button>
        ))}
        <div className="synora-rise synora-d5 rounded-2xl border border-dashed border-border p-5 text-xs leading-relaxed text-text-muted sm:col-span-2 lg:col-span-1">
          New here? Start a meeting capture or connect a source — evidence lands
          on its own, proposals appear in State for approval, and the Atlas draws
          itself.
        </div>
      </section>
    </div>
  );
}
