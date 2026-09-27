"use client";

import React from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Layers,
  HelpCircle,
  Bot,
  FileCheck,
} from "lucide-react";
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

export function OverviewView({
  state,
  conflicts,
  excalidraw = null,
  activityItems = [],
  onNavigateToTab,
  onSelectConflict,
}: OverviewViewProps) {
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  const openConflicts = conflicts.filter(
    (c) => c.status === "open" || c.status === "under_review"
  );
  const highestConflict = openConflicts[0];

  const decisionsCount = state?.decisions?.length || 0;
  const reqsCount = state?.requirements?.length || 0;
  const questionsCount = state?.open_questions?.length || 0;
  const workflow = state?.agent_workflow || ["BA", "Project", "Functional", "Tech", "Frappe"];

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Editorial Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/40">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-text-main">
            Project Overview
          </h1>
          <p className="text-xs text-text-muted mt-0.5">
            Real-time status of your project decisions, diagram alignment, and latest meeting inputs.
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <button
            onClick={() => onNavigateToTab("excalidraw")}
            className="px-3 py-1.5 text-xs font-medium text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-2xs flex items-center gap-1.5"
          >
            <span>Open Diagram</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Project Status Summary Banner */}
      <div className="p-5 rounded-xl bg-surface border border-border shadow-xs flex flex-wrap items-center justify-between gap-6 relative overflow-hidden">
        <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary" />
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-semibold uppercase tracking-wider text-primary">
              Project Status
            </span>
          </div>
          <div className="text-base font-semibold text-text-main">
            Version {state?.current_version || 1} • {openConflicts.length > 0 ? "Contradictions Detected" : "Synchronized & Aligned"}
          </div>
        </div>

        {/* Dense, real metrics (no fake vanity stats) */}
        <div className="flex items-center gap-8 text-sm">
          <div>
            <span className="text-2xl font-semibold font-mono text-text-main block">
              {decisionsCount.toString().padStart(2, "0")}
            </span>
            <span className="text-xs text-text-muted">Decisions</span>
          </div>
          <div className="w-[1px] h-8 bg-border" />
          <div>
            <span className="text-2xl font-semibold font-mono text-text-main block">
              {openConflicts.length.toString().padStart(2, "0")}
            </span>
            <span className="text-xs text-warning font-medium">Open Conflicts</span>
          </div>
          <div className="w-[1px] h-8 bg-border" />
          <div>
            <span className="text-2xl font-semibold font-mono text-text-main block">
              {reqsCount.toString().padStart(2, "0")}
            </span>
            <span className="text-xs text-text-muted">Requirements</span>
          </div>
          <div className="w-[1px] h-8 bg-border" />
          <div>
            <span className="text-2xl font-semibold font-mono text-text-main block">
              {questionsCount.toString().padStart(2, "0")}
            </span>
            <span className="text-xs text-text-muted">Questions</span>
          </div>
        </div>
      </div>

      {/* Primary Split: Current Project State vs Attention Required (design.md Section 11) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* CURRENT PROJECT STATE */}
        <div className="p-6 rounded-xl bg-surface border border-border shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-border/80">
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-primary" />
                <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
                  Current Agent Workflow
                </h3>
              </div>
              <span className="text-xs font-mono text-text-muted">
                v{state?.current_version || 1}
              </span>
            </div>

            {/* Workflow Pipeline Display */}
            <div className="py-6">
              <div className="flex items-center justify-between flex-wrap gap-2">
                {workflow.map((agentName, idx) => (
                  <React.Fragment key={agentName}>
                    <div className="px-3.5 py-2 rounded-lg border border-border bg-canvas text-xs font-medium text-text-main flex items-center gap-1.5 shadow-xs">
                      <Bot className="w-3.5 h-3.5 text-primary" />
                      <span>{agentName}</span>
                    </div>
                    {idx < workflow.length - 1 && (
                      <span className="text-text-muted font-bold text-xs">→</span>
                    )}
                  </React.Fragment>
                ))}
              </div>
            </div>

            <div className="text-xs text-text-muted leading-relaxed bg-surface-soft p-3 rounded-md border border-border/60">
              <strong>Vision:</strong> {state?.vision || "Evidence-backed project intelligence platform."}
            </div>
          </div>

          <div className="pt-4 mt-4 border-t border-border flex justify-end">
            <button
              onClick={() => onNavigateToTab("state")}
              className="text-xs font-medium text-primary hover:text-primary-hover flex items-center gap-1 transition-colors"
            >
              <span>Inspect Full Project State</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* ATTENTION REQUIRED (Most visually prominent card) */}
        <div
          className={`p-6 rounded-xl border shadow-xs flex flex-col justify-between ${
            highestConflict
              ? "bg-warning/5 border-warning/30"
              : "bg-surface border-border"
          }`}
        >
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-border/80">
              <div className="flex items-center gap-2">
                <AlertTriangle
                  className={`w-4 h-4 ${
                    highestConflict ? "text-warning" : "text-text-muted"
                  }`}
                />
                <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
                  Attention Required
                </h3>
              </div>
              <span
                className={`text-xs px-2 py-0.5 rounded font-mono ${
                  highestConflict
                    ? "bg-warning/20 text-warning border border-warning/30 font-semibold"
                    : "text-text-muted"
                }`}
              >
                {openConflicts.length} pending
              </span>
            </div>

            {highestConflict ? (
              <div className="py-4 space-y-3">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-warning/20 text-warning">
                    {highestConflict.type} conflict
                  </span>
                  <span className="text-xs text-text-muted">
                    Source: {highestConflict.source}
                  </span>
                </div>

                <div className="text-sm font-semibold text-text-main leading-snug">
                  {highestConflict.title}
                </div>

                <p className="text-xs text-text-muted leading-relaxed line-clamp-2">
                  {highestConflict.description}
                </p>

                <div className="text-xs text-text-muted pt-2 border-t border-border/40">
                  <strong>Impact:</strong> {highestConflict.impact || "Modifies architectural baseline."}
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-text-muted">
                <CheckCircle2 className="w-6 h-6 text-success mx-auto mb-2" />
                No active conflicts. Authoritative state is harmonized.
              </div>
            )}
          </div>

          <div className="pt-4 border-t border-border flex justify-end">
            {highestConflict ? (
              <button
                onClick={() => {
                  onSelectConflict(highestConflict);
                  onNavigateToTab("conflicts");
                }}
                className="px-3.5 py-1.5 rounded-md bg-warning text-surface text-xs font-semibold hover:bg-warning/90 transition-colors shadow-xs flex items-center gap-1.5"
              >
                <span>Review Conflict</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            ) : (
              <button
                onClick={() => onNavigateToTab("conflicts")}
                className="text-xs text-text-muted hover:text-text-main flex items-center gap-1"
              >
                <span>View Conflict Center</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Excalidraw Preview — first-class module */}
      <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
            Living Project Workspace
          </h3>
          <span className="text-xs text-text-muted font-mono">
            {excalidraw ? `v${excalidraw.version}` : "Not synced"}
          </span>
        </div>
        {excalidraw ? (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-xs">
              <span className="w-2 h-2 rounded-full bg-success" />
              <span className="font-semibold text-text-main">Synchronized</span>
              {excalidraw.updatedAt && (
                <span className="text-text-muted" suppressHydrationWarning>
                  Updated {new Date(excalidraw.updatedAt).toLocaleString()}
                </span>
              )}
            </div>
            <div className="flex items-center gap-5 text-xs text-text-muted">
              <span><strong className="text-text-main font-mono">{excalidraw.decisionsCount}</strong> decisions</span>
              <span><strong className="text-text-main font-mono">{excalidraw.requirementsCount}</strong> requirements</span>
              <span><strong className="text-text-main font-mono">{excalidraw.pendingCount}</strong> pending review</span>
            </div>
            <button
              onClick={() => onNavigateToTab("excalidraw")}
              className="px-3.5 py-1.5 rounded-md bg-primary hover:bg-primary-hover text-white text-xs font-semibold transition-colors flex items-center gap-1.5"
            >
              <span>Open Excalidraw</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <div className="py-6 text-center text-xs text-text-muted">
            No visual workspace synced yet. Open Excalidraw to synchronize from Project State.
          </div>
        )}
      </div>

      {/* Agent Activity */}
      <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Bot className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
              Agent Activity
            </h3>
          </div>
          <button
            onClick={() => onNavigateToTab("agent")}
            className="text-xs font-medium text-primary hover:text-primary-hover flex items-center gap-1 transition-colors"
          >
            <span>Open Agent</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
        {activityItems.length === 0 ? (
          <p className="text-xs text-text-muted py-2">No agent operations recorded yet.</p>
        ) : (
          <div className="space-y-3">
            {activityItems.map((item, idx) => (
              <div key={idx} className="flex items-start gap-4 text-xs">
                <span className="font-mono text-text-muted shrink-0 mt-0.5">{item.time}</span>
                <p className="text-text-main flex-1">{item.text}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* RECENT PROJECT CHANGES (Timeline as per design.md Section 11) */}
      <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
              Recent Project Changes & Timeline
            </h3>
          </div>
          <span className="text-xs text-text-muted">Versioned Audit Log</span>
        </div>

        <div className="space-y-3">
          <div className="flex items-start gap-4 text-xs p-2.5 rounded-lg hover:bg-canvas transition-colors">
            <span className="font-mono text-text-muted shrink-0 mt-0.5" suppressHydrationWarning>
              {mounted
                ? new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                : "Active"}
            </span>
            <div className="flex-1">
              <span className="font-semibold text-text-main">
                Project State Current Version: v{state?.current_version || 1}
              </span>
              <p className="text-text-muted mt-0.5">
                Current authoritative representation active for all 5 workforce agents.
              </p>
            </div>
            <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-primary-soft text-primary font-medium">
              v{state?.current_version || 1}
            </span>
          </div>

          {state?.decisions && state.decisions.length > 0 && (
            <div className="flex items-start gap-4 text-xs p-2.5 rounded-lg hover:bg-canvas transition-colors">
              <span className="font-mono text-text-muted shrink-0 mt-0.5">Approved</span>
              <div className="flex-1">
                <span className="font-semibold text-text-main">
                  Decision Confirmed: {state.decisions[state.decisions.length - 1].text}
                </span>
                <p className="text-text-muted mt-0.5">
                  Backed by ground-truth meeting evidence.
                </p>
              </div>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-success/10 text-success border border-success/20 font-medium">
                Decision
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
