"use client";

import React from "react";
import { CheckCircle2, FileText, History, Layers3 } from "lucide-react";
import { ProjectState, ProjectStateVersion } from "@/lib/types";

interface ProjectStateViewProps {
  state: ProjectState | null;
  history: ProjectStateVersion[];
  onRollback: (version: number) => void;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
}

export function ProjectStateView({ state, history, onOpenEvidence }: ProjectStateViewProps) {
  const version = state?.current_version ?? 1;
  const requirements = state?.requirements || [];
  const decisions = state?.decisions || [];

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-2">
        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-border bg-surface px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          <Layers3 className="h-3.5 w-3.5 text-primary" />
          Authoritative state
        </div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-text-main">Project State</h1>
          <span className="rounded-md bg-primary-soft px-2 py-1 font-mono text-[11px] font-semibold text-primary">v{version}</span>
        </div>
        <p className="max-w-2xl text-sm text-text-muted">
          The current source of truth produced from connected evidence and maintained automatically by Synora.
        </p>
      </header>

      <section className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
        <div className="grid lg:grid-cols-[1.25fr_0.75fr]">
          <div className="p-5 lg:border-r lg:border-border">
            <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Vision</div>
            <p className="mt-3 text-base leading-7 text-text-main">
              {state?.vision || "No project vision recorded yet."}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 p-5">
            <div className="rounded-xl border border-border bg-canvas p-4">
              <div className="text-xl font-semibold text-text-main">{requirements.length}</div>
              <div className="mt-1 text-[11px] text-text-muted">Requirements</div>
            </div>
            <div className="rounded-xl border border-border bg-canvas p-4">
              <div className="text-xl font-semibold text-text-main">{decisions.length}</div>
              <div className="mt-1 text-[11px] text-text-muted">Decisions</div>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            <CheckCircle2 className="h-4 w-4 text-success" />
            <div>
              <h2 className="text-sm font-semibold text-text-main">Requirements</h2>
              <p className="text-[11px] text-text-muted">{requirements.length} confirmed</p>
            </div>
          </div>
          <div className="divide-y divide-border">
            {requirements.length === 0 ? (
              <div className="px-5 py-8 text-xs text-text-muted">No confirmed requirements yet.</div>
            ) : (
              requirements.slice(0, 5).map((item, index) => (
                <div key={item.id || index} className="px-5 py-3.5">
                  <div className="text-xs font-semibold text-text-main">{item.title}</div>
                  <div className="mt-1 text-xs leading-5 text-text-muted line-clamp-2">{item.content}</div>
                  {(item.evidence_ids || []).length > 0 && (
                    <button
                      onClick={() => onOpenEvidence(item.title, "Requirement", item.evidence_ids || [])}
                      className="mt-2 text-[11px] font-semibold text-primary hover:underline"
                    >
                      View evidence
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            <FileText className="h-4 w-4 text-primary" />
            <div>
              <h2 className="text-sm font-semibold text-text-main">Decisions</h2>
              <p className="text-[11px] text-text-muted">{decisions.length} recorded</p>
            </div>
          </div>
          <div className="divide-y divide-border">
            {decisions.length === 0 ? (
              <div className="px-5 py-8 text-xs text-text-muted">No decisions yet.</div>
            ) : (
              decisions.slice(0, 5).map((item, index) => (
                <div key={item.id || index} className="px-5 py-3.5">
                  <div className="text-xs font-semibold leading-5 text-text-main">{item.text}</div>
                  <div className="mt-1 text-[11px] text-text-muted">
                    {item.approved_by || "Recorded"}{item.date ? " • " + item.date : ""}
                  </div>
                  {(item.evidence_ids || []).length > 0 && (
                    <button
                      onClick={() => onOpenEvidence(item.text, "Decision", item.evidence_ids || [])}
                      className="mt-2 text-[11px] font-semibold text-primary hover:underline"
                    >
                      View evidence
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
        <div className="flex items-center gap-2 border-b border-border px-5 py-4">
          <History className="h-4 w-4 text-primary" />
          <div>
            <h2 className="text-sm font-semibold text-text-main">Version history</h2>
            <p className="text-[11px] text-text-muted">Immutable snapshots • {history.length || 1} recorded</p>
          </div>
        </div>
        <div className="divide-y divide-border">
          {history.length === 0 ? (
            <div className="px-5 py-8 text-xs text-text-muted">Initial version only.</div>
          ) : (
            history.slice(0, 6).map((entry) => (
              <div key={entry.id} className="flex items-center justify-between gap-4 px-5 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="rounded-md bg-canvas px-2 py-0.5 font-mono text-[10px] font-semibold text-primary">
                      v{entry.version_number}
                    </span>
                    {entry.version_number === version && (
                      <span className="text-[10px] font-semibold text-success">Current</span>
                    )}
                  </div>
                  <div className="mt-1 truncate text-xs text-text-main">{entry.reason}</div>
                </div>
                <span className="shrink-0 text-[10px] font-mono text-text-muted">
                  {new Date(entry.created_at).toLocaleDateString()}
                </span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}