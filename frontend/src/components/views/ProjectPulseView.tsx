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

export function ProjectPulseView({
  state,
  conflicts,
  evidence,
  activeProjectName,
  projectVersion,
  onNavigateToTab,
}: ProjectPulseViewProps) {
  const openConflicts = conflicts.filter((c) => c.status === "open" || c.status === "unresolved" || c.status === "under_review").length;
  const version = projectVersion || state?.current_version || 1;

  return (
    <div className="max-w-5xl mx-auto px-6 py-10">
      <style>{`
        @keyframes synora-rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes synora-drift { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(24px,-14px) scale(1.06); } }
        @keyframes synora-ping { 0% { transform: scale(1); opacity: .7; } 80%,100% { transform: scale(2.1); opacity: 0; } }
        .synora-rise { animation: synora-rise .55s cubic-bezier(.22,.8,.3,1) both; }
        .synora-d1 { animation-delay: .06s; } .synora-d2 { animation-delay: .14s; }
        .synora-d3 { animation-delay: .22s; } .synora-d4 { animation-delay: .3s; }
        .synora-orb { animation: synora-drift 9s ease-in-out infinite; }
        .synora-ping { animation: synora-ping 2s cubic-bezier(0,0,.2,1) infinite; }
        @media (prefers-reduced-motion: reduce) {
          .synora-rise, .synora-orb, .synora-ping { animation: none; }
        }
      `}</style>

      {/* Hero */}
      <section className="relative overflow-hidden rounded-2xl border border-border bg-canvas px-8 py-12 sm:px-12">
        <div aria-hidden className="pointer-events-none absolute -top-20 -right-16 h-64 w-64 rounded-full bg-primary/10 blur-3xl synora-orb" />
        <div aria-hidden className="pointer-events-none absolute -bottom-24 -left-10 h-56 w-56 rounded-full bg-primary/5 blur-3xl synora-orb" />

        <div className="relative">
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

          <h1 className="synora-rise synora-d1 mt-4 text-3xl sm:text-4xl font-semibold tracking-tight text-text-main">
            {activeProjectName || "Synora Core"}
          </h1>
          <p className="synora-rise synora-d2 mt-2 max-w-xl text-sm leading-relaxed text-text-muted">
            Conversations become evidence, evidence becomes memory, memory draws
            itself. Pick where to go — everything below reads from the same
            project brain.
          </p>

          <div className="synora-rise synora-d3 mt-6 flex flex-wrap items-center gap-3 text-xs text-text-muted">
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
      </section>

      {/* Destinations */}
      <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {DESTINATIONS.map((dest, i) => (
          <button
            key={dest.tab}
            onClick={() => onNavigateToTab(dest.tab)}
            className={`synora-rise group rounded-2xl border border-border bg-canvas p-5 text-left transition-all hover:border-primary/40 hover:shadow-sm synora-d${Math.min(i, 4)}`}
          >
            <dest.icon className="h-5 w-5 text-primary" />
            <div className="mt-3 flex items-center gap-1.5 font-medium text-text-main">
              {dest.title}
              <ArrowRight className="h-3.5 w-3.5 text-text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
            </div>
            <p className="mt-1 text-xs leading-relaxed text-text-muted">{dest.detail}</p>
          </button>
        ))}
        <div className="synora-rise synora-d4 rounded-2xl border border-dashed border-border p-5 text-xs leading-relaxed text-text-muted sm:col-span-2 lg:col-span-1">
          New here? Start a meeting capture or connect a source — evidence lands
          here, proposals appear in State for approval, and the Atlas draws
          itself.
        </div>
      </section>
    </div>
  );
}
