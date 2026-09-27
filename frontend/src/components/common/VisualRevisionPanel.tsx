"use client";

import React from "react";
import { History, RotateCcw } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

export interface VisualRevisionSummary {
  id: string;
  revision_number: number;
  parent_revision_id?: string | null;
  derived_from_project_state_version?: number | null;
  proposal_id?: string | null;
  actor_id: string;
  reason: string;
  is_current: boolean;
  evidence_ids: string[];
  created_at?: string | null;
}

export interface VisualRevisionDiff {
  from_revision: number;
  to_revision: number;
  added: string[];
  removed: string[];
  changed: Array<{ before: string; after: string }>;
  relationships_before: string[];
  relationships_after: string[];
  state_version_from?: number | null;
  state_version_to?: number | null;
}

interface VisualRevisionPanelProps {
  revisions: VisualRevisionSummary[];
  currentRevisionNumber?: number | null;
  compareFrom?: number | null;
  compareTo?: number | null;
  diff?: VisualRevisionDiff | null;
  onSelectCompare?: (revisionNumber: number) => void;
  onRestore?: (revisionNumber: number) => void;
  busy?: boolean;
}

export function VisualRevisionPanel({
  revisions,
  currentRevisionNumber = null,
  compareFrom = null,
  compareTo = null,
  diff = null,
  onSelectCompare,
  onRestore,
  busy = false,
}: VisualRevisionPanelProps) {
  return (
    <section className="p-5 rounded-xl bg-surface border border-border space-y-4">
      <div className="flex items-center justify-between pb-3 border-b border-border">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold text-text-main">Revision history</h2>
        </div>
        <span className="text-[11px] text-text-muted font-mono">
          {currentRevisionNumber ? `current: r${currentRevisionNumber}` : "no revisions"}
        </span>
      </div>

      {revisions.length === 0 ? (
        <p className="text-xs text-text-muted">No revisions recorded yet.</p>
      ) : (
        <ol className="space-y-2">
          {revisions.map((rev) => {
            const isCurrent = rev.is_current || rev.revision_number === currentRevisionNumber;
            const isCompareAnchor = rev.revision_number === compareFrom;
            return (
              <li
                key={rev.id}
                className={`p-3 rounded-lg border text-xs ${
                  isCompareAnchor
                    ? "border-primary/40 bg-primary-soft/40"
                    : "border-border bg-canvas/50"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-mono font-semibold text-text-main">r{rev.revision_number}</span>
                    {isCurrent ? (
                      <StatusBadge kind="success" label="Current" />
                    ) : (
                      <span className="text-[11px] text-text-muted font-mono">historical</span>
                    )}
                    {typeof rev.derived_from_project_state_version === "number" && (
                      <span className="text-[11px] text-text-muted font-mono">
                        state v{rev.derived_from_project_state_version}
                      </span>
                    )}
                    {rev.proposal_id && (
                      <span className="text-[11px] text-text-muted font-mono truncate">
                        proposal {rev.proposal_id}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {onSelectCompare && !isCurrent && (
                      <button
                        onClick={() => onSelectCompare(rev.revision_number)}
                        className="text-[11px] font-medium text-primary hover:underline"
                      >
                        Compare
                      </button>
                    )}
                    {onRestore && !isCurrent && (
                      <button
                        disabled={busy}
                        onClick={() => onRestore(rev.revision_number)}
                        className="text-[11px] font-medium text-text-muted hover:text-text-main inline-flex items-center gap-1 disabled:opacity-50"
                        title="Create a new revision from this snapshot"
                      >
                        <RotateCcw className="w-3 h-3" /> Restore
                      </button>
                    )}
                  </div>
                </div>
                <p className="text-text-muted mt-1 truncate">{rev.reason}</p>
                {rev.evidence_ids.length > 0 && (
                  <p className="text-[10px] text-text-muted font-mono mt-0.5">
                    evidence: {rev.evidence_ids.join(", ")}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {diff && (
        <div className="p-4 rounded-lg bg-canvas border border-border space-y-3">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            r{diff.from_revision} → r{diff.to_revision}
          </span>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            <div>
              <span className="text-text-muted">Added</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {diff.added.length === 0 ? (
                  <span className="text-text-muted italic">none</span>
                ) : (
                  diff.added.map((n, i) => (
                    <span key={i} className="px-1.5 py-0.5 rounded bg-success/10 text-success border border-success/20 font-mono text-[11px]">
                      + {n}
                    </span>
                  ))
                )}
              </div>
            </div>
            <div>
              <span className="text-text-muted">Removed</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {diff.removed.length === 0 ? (
                  <span className="text-text-muted italic">none</span>
                ) : (
                  diff.removed.map((n, i) => (
                    <span key={i} className="px-1.5 py-0.5 rounded bg-canvas text-text-muted border border-dashed border-border font-mono text-[11px]">
                      − {n}
                    </span>
                  ))
                )}
              </div>
            </div>
          </div>
          {diff.changed.length > 0 && (
            <div className="text-xs">
              <span className="text-text-muted">Changed</span>
              <ul className="mt-1 space-y-0.5">
                {diff.changed.map((c, i) => (
                  <li key={i} className="text-text-main">
                    <span className="text-text-muted line-through">{c.before}</span>
                    <span className="mx-1">→</span>
                    <span>{c.after}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {diff.relationships_before.length !== diff.relationships_after.length && (
            <p className="text-[11px] text-text-muted">
              Relationships: {diff.relationships_before.length} → {diff.relationships_after.length}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
