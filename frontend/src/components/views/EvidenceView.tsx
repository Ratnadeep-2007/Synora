"use client";

import React, { useState } from "react";
import { ArrowRight, FileText, Search } from "lucide-react";
import { EvidenceItem } from "@/lib/types";
import { EmptyState } from "@/components/common/EmptyState";

interface EvidenceViewProps {
  evidence: EvidenceItem[];
  onOpenEvidenceDetail?: (item: EvidenceItem) => void;
  onOpenMeeting?: (meetingId: string) => void;
  onNavigateToState?: () => void;
  contextReviewItems?: Array<{
    evidence_id: string;
    source: string;
    content: string;
    context_status: string;
    context_candidates?: Array<{
      project_id: string;
      project_name: string;
      confidence: number;
      reasons?: string[];
      basis?: string[];
    }>;
    reasoning?: string;
  }>;
  onAssignContext?: (evidenceId: string, targetProjectId: string) => Promise<void>;
}

export function EvidenceView({
  evidence,
  onOpenEvidenceDetail,
  onOpenMeeting,
  onNavigateToState,
  contextReviewItems = [],
  onAssignContext,
}: EvidenceViewProps) {
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const sources = Array.from(new Set(evidence.map((e) => e.source || "unknown")));

  const filtered = evidence.filter((e) => {
    if (sourceFilter !== "all" && (e.source || "unknown") !== sourceFilter) return false;
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      e.content.toLowerCase().includes(q) ||
      (e.actor_id || "").toLowerCase().includes(q) ||
      e.id.toLowerCase().includes(q)
    );
  });

  const selected = selectedId ? evidence.find((e) => e.id === selectedId) || null : null;

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-main">Evidence</h1>
          <p className="text-sm text-text-muted mt-1">
            First-class trust surface. Every claim links back to its source.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-text-muted absolute left-2.5 top-2.5" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search evidence…"
              aria-label="Search evidence"
              className="pl-8 pr-3 py-1.5 text-xs rounded-md bg-surface border border-border focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/50 w-56 text-text-main placeholder:text-text-muted"
            />
          </div>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            aria-label="Filter by source"
            className="px-2.5 py-1.5 text-xs rounded-md bg-surface border border-border text-text-main focus:outline-none focus:ring-1 focus:ring-primary/40"
          >
            <option value="all">All sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {contextReviewItems.length > 0 && (
        <section className="rounded-xl bg-warning/5 border border-warning/20 p-5 space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-text-main">Context needs review</h2>
            <p className="text-xs text-text-muted mt-0.5">
              Synora could not safely place this evidence. Suggested projects are shown with the reasons behind the match.
            </p>
          </div>
          <div className="space-y-3">
            {contextReviewItems.slice(0, 8).map((item) => (
              <div key={item.evidence_id} className="rounded-lg bg-surface border border-border p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/20">
                        {item.source}
                      </span>
                      <span className="text-[10px] font-mono text-text-muted">{item.evidence_id}</span>
                    </div>
                    <p className="text-xs text-text-main leading-relaxed">{item.content}</p>
                    {item.reasoning && (
                      <p className="text-[11px] text-text-muted mt-2">{item.reasoning}</p>
                    )}
                  </div>
                </div>
                <div className="mt-3 space-y-2">
                  {(item.context_candidates || []).slice(0, 3).map((candidate) => (
                    <div key={candidate.project_id} className="flex items-center justify-between gap-3 p-2.5 rounded-md bg-canvas border border-border">
                      <div>
                        <div className="text-xs font-semibold text-text-main">{candidate.project_name}</div>
                        <div className="text-[11px] text-text-muted">
                          {candidate.reasons?.slice(0, 2).join(" • ") || "Context overlap found"}
                        </div>
                      </div>
                      <button
                        disabled={!onAssignContext}
                        onClick={() => onAssignContext?.(item.evidence_id, candidate.project_id)}
                        className="px-2.5 py-1.5 text-xs font-medium text-primary bg-primary-soft border border-primary/20 rounded-md hover:bg-primary/20 disabled:opacity-50"
                      >
                        Assign
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {filtered.length === 0 ? (
        <EmptyState
          title="No evidence records"
          description="Evidence appears here once meetings or sources are ingested and normalized. Connect a source to begin building project knowledge."
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Evidence list */}
          <div className="rounded-xl bg-surface border border-border shadow-xs overflow-hidden">
            <div className="px-5 py-3 border-b border-border flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                Evidence records ({filtered.length})
              </span>
            </div>
            <div className="divide-y divide-border/60 max-h-[640px] overflow-y-auto">
              {filtered.map((item) => {
                const isSelected = item.id === selectedId;
                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      setSelectedId(item.id);
                      onOpenEvidenceDetail?.(item);
                    }}
                    className={`w-full text-left px-5 py-4 hover:bg-canvas transition-colors ${
                      isSelected ? "bg-primary-soft/50" : ""
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[10px] font-mono font-semibold uppercase px-1.5 py-0.5 rounded bg-canvas text-primary border border-border">
                        {item.source || "unknown"}
                      </span>
                      <span className="text-[11px] font-mono text-text-muted">{item.id}</span>
                    </div>
                    <p className="text-xs text-text-main leading-relaxed line-clamp-2">“{item.content}”</p>
                    <div className="flex items-center gap-3 text-[11px] text-text-muted mt-1.5">
                      <span>{item.actor_id || "Unknown speaker"}</span>
                      {item.occurred_at && (
                        <span suppressHydrationWarning>
                          {new Date(item.occurred_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Evidence detail */}
          <div className="rounded-xl bg-surface border border-border shadow-xs p-6 space-y-4 h-fit lg:sticky lg:top-20">
            {!selected ? (
              <div className="py-10 text-center text-xs text-text-muted">
                <FileText className="w-6 h-6 mx-auto mb-2 opacity-40" />
                Select an evidence record to inspect its provenance trail.
              </div>
            ) : (
              <>
                <div>
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-primary px-2 py-0.5 rounded bg-primary-soft border border-primary/20">
                    Evidence detail
                  </span>
                  <h3 className="text-sm font-semibold text-text-main mt-2 font-mono">{selected.id}</h3>
                </div>
                <dl className="space-y-2.5 text-xs">
                  <div className="flex justify-between gap-4 py-2 border-b border-border/60">
                    <dt className="text-text-muted">Source</dt>
                    <dd className="font-semibold text-text-main">{selected.source}</dd>
                  </div>
                  <div className="flex justify-between gap-4 py-2 border-b border-border/60">
                    <dt className="text-text-muted">Actor / speaker</dt>
                    <dd className="font-semibold text-text-main">{selected.actor_id || "Unknown"}</dd>
                  </div>
                  <div className="flex justify-between gap-4 py-2 border-b border-border/60">
                    <dt className="text-text-muted">Timestamp</dt>
                    <dd className="font-mono text-text-main" suppressHydrationWarning>
                      {selected.occurred_at ? new Date(selected.occurred_at).toLocaleString() : "—"}
                    </dd>
                  </div>
                  {selected.meeting_id && (
                    <div className="flex justify-between gap-4 py-2 border-b border-border/60">
                      <dt className="text-text-muted">Meeting</dt>
                      <dd className="font-mono text-text-main">{selected.meeting_id}</dd>
                    </div>
                  )}
                  {selected.transcript_entry_id && (
                    <div className="flex justify-between gap-4 py-2 border-b border-border/60">
                      <dt className="text-text-muted">Transcript entry</dt>
                      <dd className="font-mono text-text-main text-[11px] break-all text-right">{selected.transcript_entry_id}</dd>
                    </div>
                  )}
                </dl>
                <div className="p-3 rounded-md bg-canvas/60 border border-border/60 text-xs text-text-main leading-relaxed italic">
                  “{selected.content}”
                </div>
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  {selected.meeting_id && onOpenMeeting && (
                    <button
                      onClick={() => onOpenMeeting(selected.meeting_id!)}
                      className="px-3 py-1.5 rounded-md text-xs font-semibold text-primary bg-primary-soft hover:bg-primary/20 border border-primary/20 transition-colors flex items-center gap-1"
                    >
                      <span>Open source meeting</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {onNavigateToState && (
                    <button
                      onClick={onNavigateToState}
                      className="px-3 py-1.5 rounded-md text-xs font-medium text-text-muted hover:text-text-main border border-border hover:bg-canvas transition-colors"
                    >
                      View in Project State
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
