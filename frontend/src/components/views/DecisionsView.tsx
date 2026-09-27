import React, { useState } from "react";
import { CheckCircle2, Clock, User, FileText, ShieldCheck, AlertTriangle } from "lucide-react";
import { ProjectState, Conflict } from "@/lib/types";

interface DecisionsViewProps {
  state: ProjectState | null;
  conflicts?: Conflict[];
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
  onReviewConflict?: (conflictId: string, action: "approve" | "reject" | "mark_unresolved", reason?: string, note?: string) => Promise<void>;
}

export function DecisionsView({ state, conflicts = [], onOpenEvidence, onReviewConflict }: DecisionsViewProps) {
  const [subTab, setSubTab] = useState<"decisions" | "conflicts">("decisions");
  const decisions = state?.decisions || [];
  const openConflicts = conflicts.filter((c) => c.status === "open" || c.status === "under_review");

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Clean Human Header & Sub-tabs */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/40">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-text-main flex items-center gap-2">
            <CheckCircle2 className="w-5 h-5 text-primary" />
            <span>Decisions & Alignment</span>
          </h1>
          <p className="text-xs text-text-muted mt-0.5">
            Confirmed team decisions and detected contradictions needing human review.
          </p>
        </div>

        {/* Sub-tab Pill Switcher */}
        <div className="flex items-center p-1 bg-surface border border-border rounded-lg shadow-2xs self-start sm:self-auto">
          <button
            onClick={() => setSubTab("decisions")}
            className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              subTab === "decisions"
                ? "bg-primary text-white shadow-xs"
                : "text-text-muted hover:text-text-main"
            }`}
          >
            Decisions ({decisions.length})
          </button>
          <button
            onClick={() => setSubTab("conflicts")}
            className={`px-3 py-1 text-xs font-medium rounded-md transition-colors flex items-center gap-1.5 ${
              subTab === "conflicts"
                ? "bg-amber-600 text-white shadow-xs"
                : "text-text-muted hover:text-text-main"
            }`}
          >
            <span>Contradictions</span>
            {openConflicts.length > 0 && (
              <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono ${
                subTab === "conflicts" ? "bg-white/20 text-white" : "bg-amber-500/20 text-amber-700"
              }`}>
                {openConflicts.length}
              </span>
            )}
          </button>
        </div>
      </div>

      {subTab === "decisions" ? (
        <div className="space-y-3">
          {decisions.length === 0 ? (
            <div className="p-12 text-center text-sm text-text-muted bg-surface rounded-xl border border-border">
              <CheckCircle2 className="w-8 h-8 text-text-muted mx-auto mb-2 opacity-40" />
              No confirmed decisions recorded yet. Decisions approved from meetings appear here.
            </div>
          ) : (
            decisions.map((d, idx) => (
              <div
                key={d.id || idx}
                className="p-5 rounded-xl bg-surface border border-border shadow-2xs hover:border-primary/30 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4"
              >
                <div className="space-y-1.5 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-success/10 text-success border border-success/20 font-mono">
                      Decision
                    </span>
                    <span className="text-xs text-text-muted font-mono">{d.id || `DEC-${idx + 1}`}</span>
                  </div>

                  <h3 className="text-sm font-semibold text-text-main leading-snug">{d.text}</h3>

                  <div className="flex items-center gap-4 text-xs text-text-muted pt-1">
                    <div className="flex items-center gap-1">
                      <User className="w-3.5 h-3.5" />
                      <span>Approved by: <strong className="text-text-main">{d.approved_by || "PM"}</strong></span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5" />
                      <span>{d.date || "Active"}</span>
                    </div>
                  </div>
                </div>

                <div className="shrink-0">
                  <button
                    onClick={() =>
                      onOpenEvidence(d.text, "Decision", d.evidence_ids || [])
                    }
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-text-main bg-surface hover:bg-surface/80 border border-border flex items-center gap-1.5 transition-colors shadow-2xs"
                  >
                    <FileText className="w-3.5 h-3.5 text-text-muted" />
                    <span>View Evidence</span>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {conflicts.length === 0 ? (
            <div className="p-12 text-center text-sm text-text-muted bg-surface rounded-xl border border-border">
              <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2" />
              <p className="font-semibold text-text-main">All Clear • No Contradictions</p>
              <p className="text-xs text-text-muted mt-1">All meeting statements and project requirements are aligned.</p>
            </div>
          ) : (
            conflicts.map((c) => (
              <div
                key={c.id}
                className="p-5 rounded-xl bg-surface border border-border shadow-2xs hover:border-amber-500/40 transition-all space-y-3"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full border ${
                        c.status === "open"
                          ? "bg-amber-500/10 text-amber-700 border-amber-500/20"
                          : "bg-surface text-text-muted border-border"
                      }`}>
                        {c.status.replace("_", " ")}
                      </span>
                      <span className="text-xs text-text-muted font-mono">{c.id}</span>
                    </div>
                    <h3 className="text-sm font-semibold text-text-main">{c.title}</h3>
                    <p className="text-xs text-text-muted">{c.description}</p>
                  </div>

                  {c.status === "open" && onReviewConflict && (
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => onReviewConflict(c.id, "reject")}
                        className="px-2.5 py-1 text-xs font-medium text-danger bg-danger/10 hover:bg-danger/20 rounded-lg transition-colors"
                      >
                        Dismiss
                      </button>
                      <button
                        onClick={() => onReviewConflict(c.id, "approve")}
                        className="px-3 py-1 text-xs font-medium text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-2xs"
                      >
                        Resolve
                      </button>
                    </div>
                  )}
                </div>

                <div className="pt-2 border-t border-border/60 flex items-center justify-between text-xs text-text-muted">
                    <span>Topic: <strong className="text-text-main">{c.type || "Architecture"}</strong></span>
                  <button
                    onClick={() => onOpenEvidence(c.title, "Contradiction", c.evidence_ids || [])}
                    className="text-primary hover:underline flex items-center gap-1 font-medium"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    <span>Compare Evidence</span>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
