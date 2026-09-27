"use client";

import React, { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Clock,
  ArrowRight,
  ShieldAlert,
  ShieldCheck,
  FileText,
} from "lucide-react";
import { Conflict } from "@/lib/types";

interface ConflictCenterViewProps {
  conflicts: Conflict[];
  onReviewConflict: (
    conflictId: string,
    action: "approve" | "reject" | "mark_unresolved",
    reason?: string,
    note?: string
  ) => Promise<void>;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
}

export function ConflictCenterView({
  conflicts,
  onReviewConflict,
  onOpenEvidence,
}: ConflictCenterViewProps) {
  const [filter, setFilter] = useState<string>("all");
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  const filteredConflicts = conflicts.filter((c) => {
    if (filter === "all") return true;
    return c.status === filter;
  });

  const handleAction = async (
    conflictId: string,
    action: "approve" | "reject" | "mark_unresolved"
  ) => {
    try {
      setReviewingId(conflictId);
      await onReviewConflict(conflictId, action);
    } finally {
      setReviewingId(null);
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text-main">
          Conflict Center & Human Review
        </h1>
        <p className="text-sm text-text-muted mt-1">
          Resolve detected architectural, workflow, and requirement contradictions before state advancement.
        </p>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 border-b border-border pb-3 text-xs">
        {["all", "open", "approved", "rejected", "unresolved"].map((st) => (
          <button
            key={st}
            onClick={() => setFilter(st)}
            className={`px-3 py-1.5 rounded-md capitalize transition-colors font-medium ${
              filter === st
                ? "bg-primary text-surface font-semibold shadow-neu"
                : "text-text-muted hover:text-text-main hover:bg-canvas"
            }`}
          >
            {st} ({st === "all" ? conflicts.length : conflicts.filter((c) => c.status === st).length})
          </button>
        ))}
      </div>

      {/* Conflicts List */}
      <div className="space-y-6">
        {filteredConflicts.length === 0 ? (
          <div className="p-12 text-center text-xs text-text-muted bg-surface rounded-xl border border-border">
            <CheckCircle2 className="w-8 h-8 text-success mx-auto mb-2" />
            No conflicts found for filter '{filter}'.
          </div>
        ) : (
          filteredConflicts.map((c) => {
            const isPending = c.status === "open" || c.status === "under_review";
            let currentStateStr = c.current_state_reference;
            let proposedStateStr = c.proposed_change_reference;
            try {
              const curObj = JSON.parse(c.current_state_reference);
              currentStateStr = curObj.agent_workflow
                ? curObj.agent_workflow.join(" → ")
                : JSON.stringify(curObj);
            } catch {}
            try {
              const propObj = JSON.parse(c.proposed_change_reference);
              proposedStateStr = propObj.agent_workflow
                ? propObj.agent_workflow.join(" → ")
                : JSON.stringify(propObj);
            } catch {}

            return (
              <div
                key={c.id}
                className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-5"
              >
                {/* Header */}
                <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-border/70">
                  <div className="flex items-center gap-2.5">
                    <span
                      className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded font-mono border ${
                        c.severity === "high"
                          ? "bg-danger/10 text-danger border-danger/20"
                          : "bg-warning/10 text-warning border-warning/20"
                      }`}
                    >
                      {c.severity} Severity
                    </span>
                    <span className="text-xs font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-primary-soft text-primary font-mono">
                      {c.type}
                    </span>
                    <span className="text-xs text-text-muted font-mono">{c.id}</span>
                  </div>

                  <div className="flex items-center gap-3 text-xs text-text-muted">
                    <div className="flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5" />
                      <span suppressHydrationWarning>{new Date(c.created_at).toLocaleString()}</span>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[11px] font-semibold capitalize font-mono border ${
                        c.status === "approved"
                          ? "bg-success/10 text-success border-success/20"
                          : c.status === "rejected"
                          ? "bg-danger/10 text-danger border-danger/20"
                          : c.status === "unresolved"
                          ? "bg-canvas text-text-muted border-border"
                          : "bg-warning/20 text-warning border-warning/30"
                      }`}
                    >
                      {c.status.replace("_", " ")}
                    </span>
                  </div>
                </div>

                {/* Title & Description */}
                <div>
                  <h3 className="text-base font-semibold text-text-main">{c.title}</h3>
                  <p className="text-xs text-text-muted mt-1 leading-relaxed">{c.description}</p>
                </div>

                {/* Visual State Comparison: Current State vs Proposed Change */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
                  {/* Current State */}
                  <div className="p-3.5 rounded-lg border border-border bg-canvas/60 space-y-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted block">
                      Current Authoritative State
                    </span>
                    <div className="text-xs text-text-main font-semibold break-all leading-normal">
                      {currentStateStr}
                    </div>
                  </div>

                  {/* Proposed State */}
                  <div className="p-3.5 rounded-lg border border-primary/30 bg-primary-soft/40 space-y-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-primary block">
                      Proposed Candidate Modification
                    </span>
                    <div className="text-xs text-primary font-semibold break-all leading-normal">
                      {proposedStateStr}
                    </div>
                  </div>
                </div>

                {/* Impact & Source Details */}
                <div className="flex flex-wrap items-center justify-between text-xs text-text-muted pt-2 border-t border-border/40 gap-2">
                  <div>
                    <strong>Impact:</strong> {c.impact || "Modifies project sequence and baseline."}
                  </div>
                  <div>
                    <strong>Source:</strong> {c.source}
                  </div>
                </div>

                {/* Action Controls */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-border">
                  <button
                    onClick={() =>
                      onOpenEvidence(c.title, `${c.type} Conflict`, c.evidence_ids || [])
                    }
                    className="text-xs font-semibold text-primary hover:text-primary-hover flex items-center gap-1 transition-colors"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    <span>Why? Inspect Evidence ({c.evidence_ids?.length || 0})</span>
                  </button>

                  {isPending ? (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleAction(c.id, "reject")}
                        disabled={reviewingId === c.id}
                        className="px-3.5 py-1.5 rounded-md border border-border bg-surface text-danger text-xs font-semibold hover:bg-danger/10 transition-colors disabled:opacity-50"
                      >
                        Reject
                      </button>
                      <button
                        onClick={() => handleAction(c.id, "mark_unresolved")}
                        disabled={reviewingId === c.id}
                        className="px-3.5 py-1.5 rounded-md border border-border bg-canvas text-text-muted text-xs font-semibold hover:text-text-main transition-colors disabled:opacity-50"
                      >
                        Mark Unresolved
                      </button>
                      <button
                        onClick={() => handleAction(c.id, "approve")}
                        disabled={reviewingId === c.id}
                        className="px-4 py-1.5 rounded-md bg-primary hover:bg-primary-hover text-surface text-xs font-semibold shadow-xs transition-colors disabled:opacity-50"
                      >
                        {reviewingId === c.id ? "Applying..." : "Approve & Advance State"}
                      </button>
                    </div>
                  ) : (
                    <div className="text-xs text-text-muted italic" suppressHydrationWarning>
                      Resolved by <strong>{c.resolved_by || "—"}</strong> on{" "}
                      {c.resolved_at ? new Date(c.resolved_at).toLocaleDateString() : "—"}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
