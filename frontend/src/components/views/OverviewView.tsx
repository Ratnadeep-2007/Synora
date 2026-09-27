"use client";

import React from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, FileText, PenTool } from "lucide-react";
import { Conflict, ProjectState } from "@/lib/types";

interface OverviewViewProps {
  state: ProjectState | null;
  conflicts: Conflict[];
  excalidraw?: {
    name: string;
    version: number;
    updatedAt?: string | null;
    decisionsCount: number;
    requirementsCount: number;
    pendingCount: number;
  } | null;
  activityItems?: Array<{ time: string; text: string }>;
  onNavigateToTab: (tab: any) => void;
  onSelectConflict: (conflict: Conflict) => void;
}

export function OverviewView({ state, conflicts, excalidraw = null, activityItems = [], onNavigateToTab, onSelectConflict }: OverviewViewProps) {
  const openConflicts = conflicts.filter((c) => c.status === "open" || c.status === "under_review");
  const requirementsCount = state?.requirements?.length ?? 0;
  const decisionsCount = state?.decisions?.length ?? 0;
  const questionsCount = state?.open_questions?.length ?? 0;
  const currentVersion = state?.current_version ?? 1;
  const topConflict = openConflicts[0];

  return (
    <div className="space-y-6">
      <header>
        <p className="text-[11px] uppercase tracking-wider font-semibold text-primary">Project overview</p>
        <h1 className="text-xl font-semibold tracking-tight text-text-main mt-1">What is true right now?</h1>
        <p className="text-xs text-text-muted mt-1 max-w-2xl">A single source of truth for current state, open questions, conflicts, and the living workspace.</p>
      </header>

      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          ["Requirements", requirementsCount],
          ["Decisions", decisionsCount],
          ["Open questions", questionsCount],
          ["Conflicts", openConflicts.length],
        ].map(([label, value]) => (
          <div key={String(label)} className="p-4 rounded-lg bg-surface border border-border">
            <div className="text-2xl font-semibold font-mono text-text-main">{String(value).padStart(2, "0")}</div>
            <div className="text-xs text-text-muted mt-1">{label}</div>
          </div>
        ))}
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-[1.25fr_0.75fr] gap-4">
        <section className="p-5 rounded-xl bg-surface border border-border">
          <div className="flex items-center justify-between pb-3 border-b border-border">
            <div>
              <h2 className="text-sm font-semibold text-text-main">Current project state</h2>
              <p className="text-[11px] text-text-muted mt-0.5">Authoritative state v{currentVersion}</p>
            </div>
            <button onClick={() => onNavigateToTab("state")} className="text-xs text-primary inline-flex items-center gap-1">View state <ArrowRight className="w-3 h-3" /></button>
          </div>
          <div className="space-y-3 pt-4">
            <div>
              <span className="text-[11px] font-semibold text-text-muted uppercase tracking-wide">Vision</span>
              <p className="text-sm text-text-main mt-1 leading-relaxed">{state?.vision || "No project vision recorded yet."}</p>
            </div>
            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="p-3 rounded-lg bg-canvas border border-border">
                <span className="text-[11px] text-text-muted">Latest requirement</span>
                <p className="text-xs font-medium text-text-main mt-1 line-clamp-2">{(state?.requirements?.[0]?.title || state?.requirements?.[0]?.content) || "None yet"}</p>
              </div>
              <div className="p-3 rounded-lg bg-canvas border border-border">
                <span className="text-[11px] text-text-muted">Latest decision</span>
                <p className="text-xs font-medium text-text-main mt-1 line-clamp-2">{state?.decisions?.[0]?.text || "None yet"}</p>
              </div>
            </div>
          </div>
        </section>

        <section className={`p-5 rounded-xl border ${topConflict ? "bg-warning/5 border-warning/30" : "bg-surface border-border"}`}>
          <div className="flex items-center justify-between pb-3 border-b border-border/70">
            <div className="flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-warning" /><h2 className="text-sm font-semibold text-text-main">Needs attention</h2></div>
            <span className="text-[11px] text-text-muted">{openConflicts.length} open</span>
          </div>
          {topConflict ? (
            <div className="pt-4 space-y-3">
              <h3 className="text-sm font-semibold text-text-main">{topConflict.title}</h3>
              <p className="text-xs text-text-muted leading-relaxed line-clamp-4">{topConflict.description}</p>
              <button onClick={() => { onSelectConflict(topConflict); onNavigateToTab("conflicts"); }} className="px-3 py-1.5 rounded-md bg-warning text-white text-xs font-semibold inline-flex items-center gap-1.5">Review conflict <ArrowRight className="w-3 h-3" /></button>
            </div>
          ) : (
            <div className="pt-8 text-center">
              <CheckCircle2 className="w-5 h-5 text-success mx-auto" />
              <p className="text-xs text-text-muted mt-2">Nothing needs review right now.</p>
            </div>
          )}
        </section>
      </div>

      <section className="p-5 rounded-xl bg-surface border border-border">
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div className="flex items-center gap-2"><PenTool className="w-4 h-4 text-primary" /><div><h2 className="text-sm font-semibold text-text-main">Living visual workspace</h2><p className="text-[11px] text-text-muted mt-0.5">Excalidraw reflects the authoritative project state visually.</p></div></div>
          <button onClick={() => onNavigateToTab("excalidraw")} className="text-xs text-primary">Open workspace</button>
        </div>
        <div className="pt-4 flex flex-wrap items-center gap-4 text-xs">
          <span className="inline-flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${excalidraw ? "bg-success" : "bg-text-muted"}`} />{excalidraw ? "Synchronized" : "Not synced"}</span>
          {excalidraw && <><span className="text-text-muted">v{excalidraw.version}</span><span className="text-text-muted">{excalidraw.decisionsCount} decisions</span><span className="text-text-muted">{excalidraw.requirementsCount} requirements</span>{excalidraw.pendingCount > 0 && <span className="text-warning font-medium">{excalidraw.pendingCount} awaiting review</span>}</>}
        </div>
      </section>

      <section className="p-5 rounded-xl bg-surface border border-border">
        <div className="flex items-center gap-2 pb-3 border-b border-border"><Clock3 className="w-4 h-4 text-primary" /><div><h2 className="text-sm font-semibold text-text-main">Recent activity</h2><p className="text-[11px] text-text-muted mt-0.5">Recent project and workspace activity.</p></div></div>
        {activityItems.length ? <div className="divide-y divide-border">{activityItems.slice(0,6).map((item,idx)=><div key={idx} className="py-3 flex items-start gap-3 text-xs"><span className="font-mono text-text-muted shrink-0">{item.time}</span><span className="text-text-main">{item.text}</span></div>)}</div> : <p className="pt-4 text-xs text-text-muted">No recent activity.</p>}
      </section>

      <div className="text-[11px] text-text-muted inline-flex items-center gap-1.5"><FileText className="w-3.5 h-3.5" />Evidence remains available from state, decision, and conflict details.</div>
    </div>
  );
}
