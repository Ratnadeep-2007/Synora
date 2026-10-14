"use client";

import React, { useState } from "react";
import {
  ArrowLeft,
  Clock,
  Trash2,
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

const SPEAKER_STYLES = [
  { avatar: "bg-primary-soft text-primary border-primary/20", bubble: "bg-primary-soft/45 border-primary/15" },
  { avatar: "bg-amber-100 text-amber-800 border-amber-200", bubble: "bg-amber-50 border-amber-100" },
  { avatar: "bg-emerald-100 text-emerald-800 border-emerald-200", bubble: "bg-emerald-50 border-emerald-100" },
  { avatar: "bg-violet-100 text-violet-800 border-violet-200", bubble: "bg-violet-50 border-violet-100" },
  { avatar: "bg-sky-100 text-sky-800 border-sky-200", bubble: "bg-sky-50 border-sky-100" },
];

function speakerStyle(name: string) {
  let hash = 0;
  for (let index = 0; index < name.length; index += 1) {
    hash = (hash * 31 + name.charCodeAt(index)) >>> 0;
  }
  return SPEAKER_STYLES[hash % SPEAKER_STYLES.length];
}

function speakerInitials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

interface MeetingDetailViewProps {
  meetingId: string;
  meetingData: any;
  meetingCanvas?: any;
  candidates: CandidateKnowledgeItem[];
  onBack: () => void;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
  onDeleteMeeting?: (meetingId: string) => Promise<void>;
  onSaveCanvas?: (projectId: string, scene: { name?: string; elements: any[]; app_state?: any }) => Promise<void>;
}

export function MeetingDetailView({
  meetingId,
  meetingData,
  meetingCanvas,
  candidates,
  onBack,
  onOpenEvidence,
  onDeleteMeeting,
  onSaveCanvas,
}: MeetingDetailViewProps) {
  const [intelligenceFilter, setIntelligenceFilter] = useState<string>("all");
  const [meetingSurface, setMeetingSurface] = useState<"canvas" | "intelligence">("canvas");
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (
      !window.confirm(
        "Delete this meeting and its transcript? Evidence rows are kept but unlinked so project knowledge keeps provenance."
      )
    ) {
      return;
    }
    setDeleting(true);
    try {
      await onDeleteMeeting?.(meetingId);
    } finally {
      setDeleting(false);
    }
  };

  const meeting = meetingData?.meeting || meetingData || {};
  // Entries arrive nested under transcripts[].entries; flatten them in
  // time order. The previous binding read a flat transcript_entries key
  // the API never returns, so the transcript always rendered empty.
  const entries = ((meetingData?.transcripts || meeting?.transcripts || []) as any[]).flatMap(
    (t: any) => t?.entries || []
  ).sort((a: any, b: any) => String(a?.start_time || "").localeCompare(String(b?.start_time || "")));
  const conversationEntries = entries.filter((entry: any) => {
    const speaker = String(entry?.participant_display_name || entry?.participant_name || entry?.speaker || "")
      .trim()
      .toLowerCase();
    return !["meeting title", "date", "participants", "meeting id"].includes(speaker);
  });

  const filteredCandidates = candidates.filter((c) => {
    if (intelligenceFilter === "all") return true;
    return normalizeCategory(c.category) === intelligenceFilter;
  });

  return (
    <div className="space-y-6 view-enter">
      {/* Top back navigation */}
      <div>
        <div className="flex items-center justify-between gap-3 mb-3">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-xs font-medium text-text-muted hover:text-text-main transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Back to Meetings</span>
          </button>
          {onDeleteMeeting && (
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-danger hover:bg-danger/10 border border-transparent hover:border-danger/25 transition-all disabled:opacity-50"
            >
              <Trash2 className="w-3.5 h-3.5" />
              {deleting ? "Deleting…" : "Delete meeting"}
            </button>
          )}
        </div>

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

      {/* Explicit meeting surface switch: the Meeting Canvas is a first-class UI surface,
          separate from the intelligence/transcript projection. */}
      <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface p-1.5 shadow-xs">
        <div className="flex items-center gap-1">
          {[
            { key: "canvas" as const, label: "Meeting Canvas" },
            { key: "intelligence" as const, label: "Meeting Intelligence" },
          ].map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setMeetingSurface(item.key)}
              className={
                "rounded-lg px-3.5 py-2 text-xs font-semibold transition-all " +
                (meetingSurface === item.key
                  ? "bg-primary-soft text-primary border border-primary/20"
                  : "text-text-muted border border-transparent hover:bg-canvas hover:text-text-main")
              }
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="hidden sm:block px-2.5 text-[10px] font-mono uppercase tracking-wider text-text-muted">
          {meetingSurface === "canvas" ? "Free-form visual workspace" : "Transcript + extracted intelligence"}
        </span>
      </div>

      {meetingSurface === "canvas" && (
        <>
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
              onSaveCanvas={
                onSaveCanvas && meetingCanvas.artifact.project_id
                  ? (scene) => onSaveCanvas(meetingCanvas.artifact.project_id, scene)
                  : undefined
              }
            />
          ) : (
            <div className="min-h-[620px] flex items-center justify-center rounded-xl border border-border bg-surface text-xs text-text-muted">
              Building the meeting canvas from the persisted discussion…
            </div>
          )}
        </div>
          </section>
        </>
      )}

      {meetingSurface === "intelligence" && (
      <>
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
        {/* LEFT: Complete speaker-attributed discussion, preserved verbatim. */}
        <section className="rounded-xl bg-surface border border-border shadow-xs overflow-hidden lg:sticky lg:top-20 lg:max-h-[70vh] flex flex-col">
          <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-border bg-surface">
            <div>
              <h3 className="text-sm font-semibold text-text-main flex items-center gap-2">
                <MessageSquareText className="w-4 h-4 text-primary" />
                Meeting discussion
              </h3>
              <p className="text-[11px] text-text-muted mt-1">Every spoken turn, attributed to its speaker and kept verbatim.</p>
            </div>
            <span className="shrink-0 text-[10px] font-mono px-2 py-1 rounded-full bg-primary-soft text-primary border border-primary/20">
              {conversationEntries.length} messages
            </span>
          </div>

          <div className="min-h-[320px] overflow-y-auto p-4 sm:p-5 bg-canvas/50 space-y-4">
            {conversationEntries.length === 0 ? (
              <div className="py-10 text-center text-xs text-text-muted">
                No discussion messages found for this meeting.
              </div>
            ) : (
              conversationEntries.map((entry: any, idx: number) => {
                const name = entry.participant_display_name || entry.participant_name || entry.speaker || "Participant";
                const style = speakerStyle(name);
                const time = entry.start_time
                  ? new Date(entry.start_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                  : null;
                return (
                  <article key={entry.id || idx} className="flex items-start gap-2.5">
                    <div className={`w-8 h-8 shrink-0 rounded-full border flex items-center justify-center text-[10px] font-bold ${style.avatar}`} aria-hidden="true">
                      {speakerInitials(name) || <User className="w-3.5 h-3.5" />}
                    </div>
                    <div className="min-w-0 max-w-[92%] sm:max-w-[86%] space-y-1">
                      <div className="flex items-center gap-2 px-1">
                        <span className="text-[11px] font-semibold text-text-main">{name}</span>
                        {time && <span className="text-[10px] text-text-muted font-mono">{time}</span>}
                      </div>
                      <div className={`rounded-2xl rounded-tl-md border px-3.5 py-2.5 ${style.bubble}`}>
                        <p className="text-xs text-text-main leading-relaxed whitespace-pre-wrap break-words">{entry.text}</p>
                      </div>
                    </div>
                  </article>
                );
              })
            )}
          </div>
        </section>

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
      </>
      )}
    </div>
  );
}
