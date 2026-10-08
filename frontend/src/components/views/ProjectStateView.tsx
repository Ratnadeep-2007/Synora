"use client";

import React, { useState, useMemo } from "react";
import {
  Layers,
  History,
  CheckCircle2,
  HelpCircle,
  Shield,
  Compass,
  ArrowRight,
  RotateCcw,
  Sparkles,
  GitCommit,
  Cpu,
  ChevronRight,
} from "lucide-react";
import { ProjectState, ProjectStateVersion } from "@/lib/types";

interface ProjectStateViewProps {
  state: ProjectState | null;
  history: ProjectStateVersion[];
  onRollback?: (version: number) => void;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
}

export function ProjectStateView({
  state,
  history = [],
  onRollback,
  onOpenEvidence,
}: ProjectStateViewProps) {
  const currentVersion = state?.current_version ?? 1;
  const [selectedVersionNum, setSelectedVersionNum] = useState<number>(currentVersion);

  // Sync selected version if current version increments in live mode
  React.useEffect(() => {
    setSelectedVersionNum(currentVersion);
  }, [currentVersion]);

  // Find snapshot for selected version
  const selectedHistoryEntry = useMemo(() => {
    return history.find((h) => h.version_number === selectedVersionNum) || null;
  }, [history, selectedVersionNum]);

  // Use historical snapshot data if viewing a previous version, otherwise use live state
  const isViewingHistorical = selectedVersionNum !== currentVersion;
  const effectiveState: ProjectState | null = useMemo(() => {
    if (isViewingHistorical && selectedHistoryEntry?.snapshot) {
      const snap = selectedHistoryEntry.snapshot as Partial<ProjectState>;
      return { ...(state as ProjectState), ...snap, current_version: selectedVersionNum };
    }
    return state;
  }, [isViewingHistorical, selectedHistoryEntry, selectedVersionNum, state]);

  const vision = effectiveState?.vision || "No authoritative project vision recorded yet.";
  const decisions = effectiveState?.decisions || [];
  const requirements = effectiveState?.requirements || [];
  const constraints = effectiveState?.constraints || [];
  const assumptions = (effectiveState as any)?.assumptions || [];
  const openQuestions = (effectiveState as any)?.open_questions || [];
  const architecture = effectiveState?.architecture || null;

  // Build sorted version numbers for timeline scrubber
  const versionList = useMemo(() => {
    const numbers = Array.from(
      new Set([1, ...history.map((h) => h.version_number), currentVersion])
    ).sort((a, b) => a - b);
    return numbers;
  }, [history, currentVersion]);

  return (
    <div className="space-y-8 max-w-6xl mx-auto pb-16 view-enter">
      {/* Editorial Header */}
      <header className="border-b border-border pb-6 flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">
            <Layers className="h-3.5 w-3.5" />
            Project Brain & Authoritative Memory
          </div>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-text-main flex items-center gap-3">
            <span>Project State</span>
            <span className="font-mono text-sm px-2.5 py-0.5 rounded-lg bg-surface border border-border text-primary font-bold">
              v{currentVersion}
            </span>
          </h1>
          <p className="mt-1 text-sm text-text-muted max-w-2xl leading-relaxed">
            The canonical source of truth synthesized by Synora across meeting audio, WhatsApp discussions, and verified decisions.
          </p>
        </div>

        {/* Live sync pill */}
        <div className="flex items-center gap-2 bg-surface px-3 py-1.5 rounded-xl border border-border text-xs text-text-muted">
          <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
          <span>Continuous Intelligence Active</span>
        </div>
      </header>

      {/* Change Replay Scrubber */}
      <section className="rounded-2xl border border-border bg-surface p-5 shadow-sm relative overflow-hidden">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-border/80">
          <div>
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-primary" />
              <h2 className="text-sm font-bold text-text-main">Change Replay Timeline</h2>
              <span className="text-[10px] font-mono text-text-muted">
                ({versionList.length} Milestones)
              </span>
            </div>
            <p className="text-xs text-text-muted mt-0.5">
              Scrub across state versions to understand how project architecture and decisions evolved.
            </p>
          </div>

          {isViewingHistorical ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-warning font-semibold">
                Replaying v{selectedVersionNum}
              </span>
              <button
                onClick={() => setSelectedVersionNum(currentVersion)}
                className="px-3 py-1.5 rounded-lg bg-primary hover:bg-primary-hover text-white text-xs font-semibold transition-all flex items-center gap-1.5 shadow-[0_0_12px_rgba(16,185,129,0.2)]"
              >
                <span>Return to Live (v{currentVersion})</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <span className="text-xs font-mono text-primary flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-primary" />
              Viewing Authoritative Live State
            </span>
          )}
        </div>

        {/* Version Scrubber Track */}
        <div className="pt-6 pb-2 px-2 overflow-x-auto">
          <div className="flex items-center gap-3 min-w-[500px] relative">
            {/* Connecting baseline */}
            <div className="absolute left-6 right-6 top-4 h-0.5 bg-border -z-0" />

            {versionList.map((ver) => {
              const isCurrent = ver === currentVersion;
              const isSelected = ver === selectedVersionNum;
              const entry = history.find((h) => h.version_number === ver);

              return (
                <button
                  key={ver}
                  onClick={() => setSelectedVersionNum(ver)}
                  className={`relative z-10 flex flex-col items-center group focus:outline-none transition-all flex-1`}
                >
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center font-mono text-xs font-bold transition-all ${
                      isSelected
                        ? "bg-primary text-white ring-4 ring-primary/20 scale-110 shadow-[0_0_12px_rgba(16,185,129,0.4)]"
                        : isCurrent
                        ? "bg-surface border-2 border-primary text-primary hover:scale-105"
                        : "bg-canvas border border-border text-text-muted hover:text-text-main hover:border-border"
                    }`}
                  >
                    v{ver}
                  </div>
                  <span
                    className={`text-[10px] mt-1.5 truncate max-w-[90px] font-mono transition-colors ${
                      isSelected ? "text-primary font-bold" : "text-text-muted"
                    }`}
                  >
                    {isCurrent ? "Live" : entry?.created_at ? new Date(entry.created_at).toLocaleDateString([], { month: "short", day: "numeric" }) : `v${ver}`}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Historical Context Notice Banner */}
        {isViewingHistorical && selectedHistoryEntry && (
          <div className="mt-4 p-3.5 rounded-xl bg-canvas border border-warning/30 flex items-center justify-between gap-4 text-xs">
            <div className="flex items-center gap-2.5">
              <GitCommit className="w-4 h-4 text-warning shrink-0" />
              <div>
                <span className="font-semibold text-text-main">
                  State Snapshot v{selectedVersionNum}:
                </span>{" "}
                <span className="text-text-muted">
                  {selectedHistoryEntry.reason || "Automatic knowledge consolidation"}
                </span>
                <span className="text-[10px] text-text-muted font-mono ml-2">
                  • Recorded {new Date(selectedHistoryEntry.created_at).toLocaleString()}
                </span>
              </div>
            </div>

            {onRollback && (
              <button
                onClick={() => onRollback(selectedVersionNum)}
                className="px-2.5 py-1 rounded bg-warning/10 hover:bg-warning/20 text-warning border border-warning/20 font-medium transition-colors flex items-center gap-1 shrink-0"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Rollback to v{selectedVersionNum}</span>
              </button>
            )}
          </div>
        )}
      </section>

      {/* Section 1: Vision (Editorial Display) */}
      <section className="rounded-2xl border border-border bg-surface p-6 sm:p-8 shadow-xs relative">
        <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-primary">
          <Compass className="w-4 h-4" />
          <span>Core Vision & Mandate</span>
        </div>
        <p className="mt-3 text-lg sm:text-xl font-medium leading-relaxed text-text-main">
          {vision}
        </p>
      </section>

      {/* Section 2: Architecture & System Topology */}
      {architecture && (
        <section className="rounded-2xl border border-border bg-surface p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between border-b border-border/80 pb-3">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-primary" />
              <h2 className="text-sm font-bold text-text-main">System Architecture & Topology</h2>
            </div>
            <span className="text-[11px] font-mono text-text-muted">
              Synchronized with Project Atlas
            </span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {architecture.length === 0 ? (
              <div className="col-span-full p-4 rounded-xl bg-canvas border border-dashed border-border text-xs text-text-muted">
                Continuous architecture models are being synchronized directly to the living Project Atlas canvas.
              </div>
            ) : (
              architecture.map((comp, idx) => (
                <div
                  key={`${comp.component}-${idx}`}
                  className="p-4 rounded-xl bg-canvas border border-border hover:border-primary/30 transition-all space-y-1.5"
                >
                  <div className="text-xs font-bold text-text-main flex items-center justify-between">
                    <span>{comp.component || `Component ${idx + 1}`}</span>
                    {comp.role && (
                      <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 rounded bg-surface border border-border text-primary">
                        {comp.role}
                      </span>
                    )}
                  </div>
                  {comp.details && (
                    <p className="text-[11px] text-text-muted leading-relaxed">
                      {comp.details}
                    </p>
                  )}
                </div>
              ))
            )}
          </div>
        </section>
      )}

      {/* Section 3: Authoritative Decisions */}
      <section className="rounded-2xl border border-border bg-surface p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-border/80 pb-3">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-primary" />
            <h2 className="text-base font-bold text-text-main">Authoritative Decisions</h2>
            <span className="text-xs font-mono text-text-muted px-2 py-0.5 rounded-full bg-canvas border border-border">
              {decisions.length}
            </span>
          </div>
          <span className="text-xs text-text-muted">
            Backed by verbatim meeting & message evidence
          </span>
        </div>

        <div className="divide-y divide-border/60">
          {decisions.length === 0 ? (
            <div className="py-8 text-center text-xs text-text-muted">
              No authoritative decisions recorded for this version milestone.
            </div>
          ) : (
            decisions.map((decision, index) => {
              const evidenceCount = (decision.evidence_ids || []).length;
              return (
                <div key={decision.id || index} className="py-4 first:pt-2 last:pb-2 group">
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                    <div className="space-y-1.5 max-w-3xl">
                      <div className="text-sm font-semibold text-text-main leading-snug group-hover:text-primary transition-colors">
                        {decision.text}
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
                        {decision.approved_by && (
                          <span>
                            Decided by: <strong className="text-text-main font-medium">{decision.approved_by}</strong>
                          </span>
                        )}
                        {decision.date && <span>• {decision.date}</span>}
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-canvas border border-border text-primary capitalize">
                          ratified
                        </span>
                      </div>
                    </div>

                    {/* "Why does Synora think this?" Button */}
                    <button
                      onClick={() =>
                        onOpenEvidence(
                          decision.text,
                          "Decision",
                          decision.evidence_ids || []
                        )
                      }
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-canvas hover:bg-surface-soft border border-border hover:border-primary/40 text-xs font-medium text-primary transition-all shrink-0 self-start group/btn"
                    >
                      <Sparkles className="w-3 h-3 text-primary group-hover/btn:rotate-12 transition-transform" />
                      <span>{evidenceCount > 0 ? `${evidenceCount} Evidence Citation${evidenceCount > 1 ? "s" : ""}` : "Inspect Evidence"}</span>
                      <ChevronRight className="w-3 h-3 group-hover/btn:translate-x-0.5 transition-transform" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* Section 4: Confirmed Requirements */}
      <section className="rounded-2xl border border-border bg-surface p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-border/80 pb-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-primary" />
            <h2 className="text-base font-bold text-text-main">Confirmed Requirements</h2>
            <span className="text-xs font-mono text-text-muted px-2 py-0.5 rounded-full bg-canvas border border-border">
              {requirements.length}
            </span>
          </div>
          <span className="text-xs text-text-muted">Derived and verified specification</span>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {requirements.length === 0 ? (
            <div className="col-span-full py-8 text-center text-xs text-text-muted">
              No requirements recorded yet.
            </div>
          ) : (
            requirements.map((req, idx) => {
              const evidenceCount = (req.evidence_ids || []).length;
              return (
                <div
                  key={req.id || idx}
                  className="p-4 rounded-xl bg-canvas border border-border hover:border-primary/30 transition-all flex flex-col justify-between space-y-3"
                >
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-xs font-bold text-text-main">{req.title}</h3>
                    </div>
                    <p className="text-xs text-text-muted leading-relaxed line-clamp-3">
                      {req.content}
                    </p>
                  </div>

                  <div className="pt-2 border-t border-border/50 flex items-center justify-between">
                    <span className="text-[10px] font-mono text-text-muted">
                      {evidenceCount} verified source{evidenceCount === 1 ? "" : "s"}
                    </span>
                    <button
                      onClick={() =>
                        onOpenEvidence(req.title, "Requirement", req.evidence_ids || [])
                      }
                      className="text-[11px] font-medium text-primary hover:underline flex items-center gap-1"
                    >
                      <span>Why?</span>
                      <ChevronRight className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* Section 5: Constraints & Open Questions (2-column grid) */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Constraints */}
        <section className="rounded-2xl border border-border bg-surface p-5 shadow-xs space-y-3">
          <div className="flex items-center gap-2 border-b border-border/80 pb-2.5">
            <Shield className="w-4 h-4 text-warning" />
            <h2 className="text-sm font-bold text-text-main">Constraints & Guardrails</h2>
            <span className="text-xs font-mono text-text-muted ml-auto">
              {constraints.length}
            </span>
          </div>

          <div className="space-y-2">
            {constraints.length === 0 ? (
              <div className="py-4 text-xs text-text-muted text-center">
                No active project constraints recorded.
              </div>
            ) : (
              constraints.map((c, idx) => (
                <div
                  key={c.id || idx}
                  className="p-3 rounded-lg bg-canvas border border-border text-xs space-y-1"
                >
                  <div className="font-semibold text-text-main">{c.title || c.text}</div>
                  {c.description && <p className="text-text-muted text-[11px]">{c.description}</p>}
                </div>
              ))
            )}
          </div>
        </section>

        {/* Open Questions / Inquiries */}
        <section className="rounded-2xl border border-border bg-surface p-5 shadow-xs space-y-3">
          <div className="flex items-center gap-2 border-b border-border/80 pb-2.5">
            <HelpCircle className="w-4 h-4 text-primary" />
            <h2 className="text-sm font-bold text-text-main">Cognitive Inquiries & Questions</h2>
            <span className="text-xs font-mono text-text-muted ml-auto">
              {openQuestions.length}
            </span>
          </div>

          <div className="space-y-2">
            {openQuestions.length === 0 ? (
              <div className="py-4 text-xs text-text-muted text-center">
                All architectural inquiries are resolved.
              </div>
            ) : (
              openQuestions.map((q: any, idx: number) => (
                <div
                  key={q.id || idx}
                  className="p-3 rounded-lg bg-canvas border border-border text-xs space-y-1"
                >
                  <div className="font-medium text-text-main">{q.question || q.title}</div>
                  <div className="flex items-center gap-2 text-[10px] text-text-muted font-mono">
                    {q.urgency && <span>Urgency: {q.urgency}</span>}
                    {q.owner && <span>Owner: {q.owner}</span>}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}