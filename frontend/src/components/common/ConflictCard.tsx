"use client";

import React from "react";
import { FileText } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

interface ConflictCardProps {
  id: string;
  type: string;
  severity: "low" | "medium" | "high";
  title: string;
  description?: string;
  currentState: string;
  proposedChange: string;
  source?: string;
  impact?: string;
  status: string;
  evidenceCount?: number;
  reviewing?: boolean;
  onOpenEvidence?: () => void;
  onApprove?: () => void;
  onReject?: () => void;
  onMarkUnresolved?: () => void;
}

export function ConflictCard({
  id,
  type,
  severity,
  title,
  description,
  currentState,
  proposedChange,
  source,
  impact,
  status,
  evidenceCount = 0,
  reviewing = false,
  onOpenEvidence,
  onApprove,
  onReject,
  onMarkUnresolved,
}: ConflictCardProps) {
  const isPending = status === "open" || status === "under_review";

  return (
    <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-border/70">
        <div className="flex items-center gap-2.5">
          <StatusBadge kind={severity === "high" ? "failed" : "review"} label={`${severity} severity`} />
          <span className="text-xs font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-primary-soft text-primary font-mono">
            {type}
          </span>
          <span className="text-xs text-text-muted font-mono">{id}</span>
        </div>
        <StatusBadge
          kind={status === "approved" ? "success" : status === "rejected" ? "failed" : status === "unresolved" ? "neutral" : "review"}
          label={status.replace("_", " ")}
        />
      </div>

      <div>
        <h3 className="text-base font-semibold text-text-main">{title}</h3>
        {description && <p className="text-xs text-text-muted mt-1 leading-relaxed">{description}</p>}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
        <div className="p-3.5 rounded-lg border border-border bg-canvas/60 space-y-1">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted block">
            Current Authoritative State
          </span>
          <div className="text-xs text-text-main font-semibold break-all leading-normal">{currentState}</div>
        </div>
        <div className="p-3.5 rounded-lg border border-primary/30 bg-primary-soft/40 space-y-1">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-primary block">
            Proposed Candidate Modification
          </span>
          <div className="text-xs text-primary font-semibold break-all leading-normal">{proposedChange}</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between text-xs text-text-muted pt-2 border-t border-border/40 gap-2">
        <div><strong>Impact:</strong> {impact || "Modifies project baseline."}</div>
        {source && <div><strong>Source:</strong> {source}</div>}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-border">
        {onOpenEvidence && (
          <button
            onClick={onOpenEvidence}
            className="text-xs font-semibold text-primary hover:text-primary-hover flex items-center gap-1 transition-colors"
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Why? Inspect Evidence ({evidenceCount})</span>
          </button>
        )}
        {isPending ? (
          <div className="flex items-center gap-2">
            {onReject && (
              <button
                onClick={onReject}
                disabled={reviewing}
                className="px-3.5 py-1.5 rounded-md border border-border bg-surface text-danger text-xs font-semibold hover:bg-danger/10 transition-colors disabled:opacity-50"
              >
                Keep current
              </button>
            )}
            {onMarkUnresolved && (
              <button
                onClick={onMarkUnresolved}
                disabled={reviewing}
                className="px-3.5 py-1.5 rounded-md border border-border bg-canvas text-text-muted text-xs font-semibold hover:text-text-main transition-colors disabled:opacity-50"
              >
                Mark unresolved
              </button>
            )}
            {onApprove && (
              <button
                onClick={onApprove}
                disabled={reviewing}
                className="px-4 py-1.5 rounded-md bg-primary hover:bg-primary-hover text-white text-xs font-semibold shadow-xs transition-colors disabled:opacity-50"
              >
                {reviewing ? "Applying..." : "Approve"}
              </button>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
