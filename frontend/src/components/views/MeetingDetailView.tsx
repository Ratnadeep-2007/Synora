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
import { ExcalidrawCanvas } from "@/components/canvas/ExcalidrawCanvas";

/**
 * Canonical intelligence categories.
 *
 * The extraction model was previously free to invent spellings, which is why the
 * filter used to compare `c.category` literally against a hardcoded list. Rows
 * persisted before the vocabulary was standardised still carry the old
 * `decision_candidate` / `requirement_candidate` values, so every category is
 * normalised before comparing. This mirrors the alias map in
 * `meeting_session_intelligence.py`; keep the two in step.
 */
const CATEGORY_ALIASES: Record<string, string> = {
  proposal: "proposal",
  decision: "decision",
  decisions: "decision",
  decision_candidate: "decision",
  decisioncandidate: "decision",
  requirement: "requirement",
  requirements: "requirement",
  requirement_candidate: "requirement",
  requirementcandidate: "requirement",
  question: "question",
  questions: "question",
  open_question: "question",
  openquestion: "question",
  action_item: "action_item",
  action_items: "action_item",
  actionitem: "action_item",
  actionitems: "action_item",
  task: "action_item",
  todo: "action_item",
  constraint: "constraint",
  constraints: "constraint",
  assumption: "assumption",
  assumptions: "assumption",
};

function normalizeCategory(raw?: string | null): string {
  const token = (raw || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (!token) return "knowledge";
  if (CATEGORY_ALIASES[token]) return CATEGORY_ALIASES[token];
  for (const [alias, canonical] of Object.entries(CATEGORY_ALIASES)) {
    if (token.endsWith(`_${alias}`)) return canonical;
  }
  return "knowledge";
}

const INTELLIGENCE_FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "all" },
  { key: "decision", label: "decision" },
  { key: "requirement", label: "requirement" },
  { key: "action_item", label: "action item" },
  { key: "constraint", label: "constraint" },
  { key: "proposal", label: "proposal" },
  { key: "question", label: "question" },
  { key: "assumption", label: "assumption" },
  { key: "knowledge", label: "other" },
];

interface MeetingDetailViewProps {
  meetingId: string;
  meetingData: any;
  meetingCanvas?: any;
  candidates: CandidateKnowledgeItem[];
  onBack: () => void;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
}

export function MeetingDetailView({
  meetingId,
  meetingData,
  meetingCanvas,
  candidates,
  onBack,
  onOpenEvidence,
}: MeetingDetailViewProps) {
  const [intelligenceFilter, setIntelligenceFilter] = useState<string>("all");

  const meeting = meetingData?.meeting || meetingData || {};
  const entries = meetingData?.transcript_entries || [];

  const filteredCandidates = candidates.filter((c) => {
    if (intelligenceFilter === "all") return true;
    return normalizeCategory(c.category) === intelligenceFilter;
  });

  return (
    <div className="space-y-6 view-enter">
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

      {/* Independent free-form Meeting Canvas. This is the meeting's working surface,
          not a projection of Project State and not constrained to fixed note types. */}
      <section className="rounded-2xl border border-border bg-surface shadow-sm overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3 bg-surface-soft">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-text-main">Meeting Canvas</h3>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-primary-soft text-primary border border-primary/20">FREE FORM</span>
            </div>
            <p className="text-[11px] text-text-muted mt-1">
              Synora records this meeting in whatever visual or written form best fits the discussion. No fixed sections or diagram types.
            </p>
          </div>
          <span className="text-[10px] font-mono text-text-muted">
            {meetingCanvas?.artifact?.version ? `Canvas v${meetingCanvas.artifact.version}` : "Preparing…"}
          </span>
        </div>
        <div className="p-2 bg-canvas">
          {meetingCanvas?.artifact ? (
            <ExcalidrawCanvas
              key={meetingCanvas.artifact.id}
              projectId={meetingCanvas.artifact.project_id}
              projectName={meeting.title || "Meeting Notes"}
              version={meetingCanvas.artifact.version || 1}
              initialElements={meetingCanvas.artifact.elements || []}
              initialAppState={{
                ...(meetingCanvas.artifact.app_state || {}),
                theme: "light",
                viewBackgroundColor: "#ffffff",
              }}
              readOnly
            />
          ) : (
            <div className="min-h-[620px] flex items-center justify-center rounded-xl border border-border bg-surface text-xs text-text-muted">
              Building the meeting canvas from the persisted discussion…
            </div>
          )}
        </div>
      </section>

      {/* Meet-only session intelligence: a projection over the same shared evidence/memory. */}
      {meetingData?.session_intelligence && (
        <section className="p-5 rounded-xl bg-surface border border-border shadow-xs space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-wider text-text-main">
                Meeting Session Intelligence
              </h3>
              <p className="text-xs text-text-muted mt-1">
                Built from the complete persisted transcript. Routing windows are only for project routing and timeline navigation; intelligence uses the full project-specific transcript context.
              </p>
            </div>
            <span className="shrink-0 text-[10px] font-mono px-2 py-1 rounded bg-primary-soft text-primary border border-primary/20">
              Completed sync
            </span>
          </div>

          {(() => {
            const sync = meetingData.session_intelligence.source_sync || {};
            return (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <div className="rounded-lg border border-border bg-canvas px-3 py-2">
                  <div className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">Transcript source</div>
                  <div className="text-xs font-medium text-text-main mt-1">Complete persisted transcript</div>
                </div>
                <div className="rounded-lg border border-border bg-canvas px-3 py-2">
                  <div className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">Google API after sync</div>
                  <div className="text-xs font-medium text-text-main mt-1">{sync.google_api_calls_after_persistence ?? 0} calls</div>
                </div>
                <div className="rounded-lg border border-border bg-canvas px-3 py-2">
                  <div className="text-[10px] uppercase tracking-wider font-semibold text-text-muted">Sync mode</div>
                  <div className="text-xs font-medium text-text-main mt-1">One completed-meeting sync</div>
                </div>
              </div>
            );
          })()}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Transcript turns", value: meetingData.session_intelligence.transcript_entry_count || 0, icon: MessageSquareText },
              { label: "Routing windows", value: meetingData.session_intelligence.routing_window_count ?? meetingData.session_intelligence.segment_count ?? 0, icon: Clock },
              { label: "Participants", value: meetingData.session_intelligence.participant_count || 0, icon: Users },
              { label: "Action items", value: (meetingData.session_intelligence.action_items || []).length, icon: ListChecks },
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

          <div className="rounded-lg border border-border bg-canvas p-4 space-y-3">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Conversation timeline</div>
              <div className="text-[10px] text-text-muted mt-1">Routing/timeline windows only — no separate AI pass per window.</div>
            </div>
            {(meetingData.session_intelligence.segments || []).length === 0 ? (
              <p className="text-xs text-text-muted">No routing windows available for this completed transcript.</p>
            ) : (
              <div className="flex gap-3 overflow-x-auto pb-1">
                {meetingData.session_intelligence.segments.slice(0, 10).map((segment: any) => (
                  <div key={segment.segment_id} className="min-w-[250px] max-w-[290px] rounded-md border border-border bg-surface p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] font-semibold font-mono text-primary">{segment.segment_id.split(":").pop()}</span>
                      <span className="text-[10px] font-mono text-text-muted">{segment.entry_count || 0} turns</span>
                    </div>
                    <div className="text-[10px] font-mono text-text-muted">
                      {segment.start_time ? new Date(segment.start_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                      {segment.end_time ? " → " + new Date(segment.end_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {(segment.speakers || []).slice(0, 4).map((speaker: string) => (
                        <span key={speaker} className="text-[10px] px-1.5 py-0.5 rounded bg-canvas border border-border text-text-muted">{speaker}</span>
                      ))}
                    </div>
                    {(segment.topics || []).length > 0 && (
                      <div className="text-[11px] font-medium text-text-main">
                        {(segment.topics || []).slice(0, 2).join(" · ")}
                      </div>
                    )}
                    <p className="text-[10px] text-text-muted leading-relaxed line-clamp-4">{segment.preview || "No preview available."}</p>
                  </div>
                ))}
              </div>
            )}
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
                    <div className="text-[10px] font-mono text-text-muted">
                      Evidence: {(item.evidence_ids || []).length} persisted reference{(item.evidence_ids || []).length === 1 ? "" : "s"}
                    </div>
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
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {INTELLIGENCE_FILTERS.map(({ key, label }) => {
              const count =
                key === "all"
                  ? candidates.length
                  : candidates.filter((c) => normalizeCategory(c.category) === key).length;
              return (
                <button
                  key={key}
                  onClick={() => setIntelligenceFilter(key)}
                  disabled={count === 0}
                  className={`px-2.5 py-1 rounded-md capitalize transition-colors ${
                    intelligenceFilter === key
                      ? "bg-primary-soft text-primary font-semibold border border-primary/20"
                      : count === 0
                        ? "text-text-muted/40 border border-transparent cursor-not-allowed"
                        : "text-text-muted hover:bg-canvas border border-transparent"
                  }`}
                >
                  {label}
                  <span className="ml-1.5 text-[10px] opacity-70">{count}</span>
                </button>
              );
            })}
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
                      {normalizeCategory(cand.category)}
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
                      onOpenEvidence(
                        cand.title,
                        normalizeCategory(cand.category),
                        cand.evidence_ids || []
                      )
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
