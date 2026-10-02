"use client";

import React, { useState } from "react";
import {
  ArrowLeft,
  Clock,
  User,
  ListChecks,
  MessageSquareText,
  Users,
} from "lucide-react";
import { CandidateKnowledgeItem } from "@/lib/types";

interface MeetingDetailViewProps {
  meetingId: string;
  meetingData: any;
  candidates: CandidateKnowledgeItem[];
  onBack: () => void;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
}

export function MeetingDetailView({
  meetingId,
  meetingData,
  candidates,
  onBack,
  onOpenEvidence,
}: MeetingDetailViewProps) {
  const [intelligenceFilter, setIntelligenceFilter] = useState<string>("all");

  const meeting = meetingData?.meeting || meetingData || {};
  const entries = meetingData?.transcript_entries || [];

  const filteredCandidates = candidates.filter((c) => {
    if (intelligenceFilter === "all") return true;
    return c.category === intelligenceFilter;
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Top back navigation */}
      <div>
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs font-medium text-text-muted hover:text-text-main transition-colors mb-3"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Meetings</span>
        </button>

        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-primary px-2 py-0.5 rounded bg-primary-soft border border-primary/20">
              Conference Detail
            </span>
            <span className="text-xs font-mono text-text-muted">ID: {meetingId}</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-main">
            {meeting.title || "Project Architecture Sync"}
          </h1>
        </div>
      </div>

      {/* Meet-only session intelligence: a projection over the same shared evidence/memory. */}
      {meetingData?.session_intelligence && (
        <section className="p-5 rounded-xl bg-surface border border-border shadow-xs space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-wider text-text-main">
                Meeting Session Intelligence
              </h3>
              <p className="text-xs text-text-muted mt-1">
                Conversation structure from Meet; project knowledge still lives in shared Synora memory.
              </p>
            </div>
            <span className="text-[10px] font-mono px-2 py-1 rounded bg-primary-soft text-primary border border-primary/20">
              {meetingData.session_intelligence.segment_count || 0} segments
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Participants", value: meetingData.session_intelligence.participant_count || 0, icon: Users },
              { label: "Decisions", value: (meetingData.session_intelligence.decisions || []).length, icon: MessageSquareText },
              { label: "Action items", value: (meetingData.session_intelligence.action_items || []).length, icon: ListChecks },
              { label: "Open questions", value: (meetingData.session_intelligence.open_questions || []).length, icon: MessageSquareText },
            ].map(({ label, value, icon: Icon }) => (
              <div key={label} className="rounded-lg border border-border bg-canvas p-3">
                <div className="flex items-center gap-2 text-text-muted">
                  <Icon className="w-3.5 h-3.5" />
                  <span className="text-[10px] uppercase tracking-wider font-semibold">{label}</span>
                </div>
                <div className="text-xl font-semibold text-text-main mt-1">{value}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="rounded-lg border border-border bg-canvas p-4 space-y-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Action items</div>
              {(meetingData.session_intelligence.action_items || []).length === 0 ? (
                <p className="text-xs text-text-muted">No action items extracted from this meeting.</p>
              ) : (
                meetingData.session_intelligence.action_items.slice(0, 6).map((item: any) => (
                  <div key={item.id} className="rounded-md border border-border bg-surface p-3 space-y-1">
                    <div className="text-xs font-semibold text-text-main">{item.title}</div>
                    <div className="text-[11px] text-text-muted">{item.content}</div>
                    <div className="flex flex-wrap gap-2 text-[10px] font-mono text-text-muted">
                      {item.owner_hints?.[0] && <span>Owner: {item.owner_hints[0]}</span>}
                      {item.due_hint && <span>Due: {item.due_hint}</span>}
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="rounded-lg border border-border bg-canvas p-4 space-y-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Memory delta</div>
              {(meetingData.session_intelligence.memory_delta || []).length === 0 ? (
                <p className="text-xs text-text-muted">No project memory update recorded for this meeting yet.</p>
              ) : (
                meetingData.session_intelligence.memory_delta.map((delta: any) => (
                  <div key={delta.project_id} className="flex items-center justify-between rounded-md border border-border bg-surface px-3 py-2">
                    <span className="text-xs font-mono text-text-main">{delta.project_id}</span>
                    <span className="text-[10px] font-mono text-text-muted">
                      v{delta.version_before ?? "—"} → v{delta.version_after ?? "—"} · {delta.applied || 0} applied
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
      )}

      {/* Desktop two primary columns: Transcript + Intelligence (independently scrollable) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        {/* LEFT: Transcript — original text, never paraphrased */}
        <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4 lg:sticky lg:top-20 lg:max-h-[70vh] lg:overflow-y-auto">
          <div className="flex items-center justify-between pb-3 border-b border-border">
            <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
              Transcript ({entries.length})
            </h3>
            <span className="text-xs text-text-muted">Direct source record</span>
          </div>

          <div className="divide-y divide-border/60">
            {entries.length === 0 ? (
              <div className="py-6 text-center text-xs text-text-muted">
                No transcript entries found for this meeting.
              </div>
            ) : (
              entries.map((entry: any, idx: number) => (
                <div key={entry.id || idx} className="py-3.5 space-y-1.5">
                  <div className="flex items-center justify-between text-xs text-text-muted">
                    <div className="flex items-center gap-1.5 font-medium text-text-main">
                      <User className="w-3.5 h-3.5 text-primary" />
                      <span>{entry.participant_name || entry.speaker || "Participant"}</span>
                    </div>
                    <div className="flex items-center gap-1 font-mono text-[11px]">
                      <Clock className="w-3 h-3" />
                      <span>{entry.start_time || "00:00:00"}</span>
                    </div>
                  </div>
                  <p className="text-xs text-text-main leading-relaxed pl-5 font-sans">
                    {entry.text}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>

        {/* RIGHT: Intelligence — type, statement, status, evidence, action */}
        <div className="space-y-4 lg:max-h-[70vh] lg:overflow-y-auto lg:pr-1">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
              Intelligence ({candidates.length})
            </h3>
          </div>
          {/* Category Filter Pills */}
          <div className="flex items-center gap-2 text-xs">
            {["all", "proposal", "requirement_candidate", "decision_candidate", "question"].map((cat) => (
              <button
                key={cat}
                onClick={() => setIntelligenceFilter(cat)}
                className={`px-2.5 py-1 rounded-md capitalize transition-colors ${
                  intelligenceFilter === cat
                    ? "bg-primary-soft text-primary font-semibold border border-primary/20"
                    : "text-text-muted hover:bg-canvas border border-transparent"
                }`}
              >
                {cat.replace("_", " ")}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-3">
            {filteredCandidates.length === 0 ? (
              <div className="p-8 text-center text-xs text-text-muted bg-surface rounded-xl border border-border">
                No extracted items match this filter. Run "Process Pipeline" on the meeting if not yet analyzed.
              </div>
            ) : (
              filteredCandidates.map((cand) => (
                <div
                  key={cand.id}
                  className="p-5 rounded-xl bg-surface border border-border shadow-xs space-y-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-semibold font-mono uppercase tracking-wider px-2 py-0.5 rounded bg-canvas text-primary border border-border">
                      {cand.category}
                    </span>
                    <span className="text-[11px] font-medium capitalize px-1.5 py-0.5 rounded bg-canvas border border-border text-text-muted">
                      {cand.status || "Needs review"}
                    </span>
                  </div>

                  <p className="text-xs text-text-main leading-relaxed">
                    {cand.content}
                  </p>
                  <div className="text-[11px] text-text-muted font-mono">
                    Meet · {(cand.evidence_ids || []).length} evidence ref{(cand.evidence_ids || []).length === 1 ? "" : "s"}
                  </div>

                  <button
                    onClick={() =>
                      onOpenEvidence(cand.title, cand.category, cand.evidence_ids || [])
                    }
                    className="px-3 py-1.5 rounded-md text-xs font-semibold text-primary bg-primary-soft hover:bg-primary/20 border border-primary/20 transition-colors"
                  >
                    Why?
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
