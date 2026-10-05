"use client";

import React, { useMemo, useState } from "react";
import {
  ArrowRight,
  CircleCheck,
  Clock3,
  Loader2,
  Mic,
  MicOff,
  Radio,
  Search,
  Square,
  Video,
} from "lucide-react";
import { MeetingItem } from "@/lib/types";

export interface CaptureStatus {
  running: boolean;
  stage: string;
  job?: { project_id?: string; candidate_project_ids?: string[] } | null;
  last_state?: { status?: string; detail?: string; meeting_id?: string } | null;
  logs?: string[];
  problems?: string[];
}

interface MeetingsViewProps {
  meetings: MeetingItem[];
  autoSyncStatus?: {
    connected: boolean;
    active: boolean;
    lastEventAt?: string | null;
    pendingCount?: number;
    subscriptionsCount?: number;
  };
  onSelectMeeting: (meetingId: string) => void;
  onProcessPipeline: (meetingId: string) => Promise<void>;
  onSyncGoogleMeet?: () => Promise<void>;
  onIngestTranscript?: (payload: {
    title: string;
    raw_transcript: string;
    provider?: string;
  }) => Promise<void>;
  captureStatus?: CaptureStatus | null;
  onArmCapture?: (opts: {
    project_id: string;
    candidate_project_ids: string[];
    max_minutes: number;
    speakers: number;
  }) => Promise<void>;
  onStopCapture?: () => Promise<void>;
  projects?: { id: string; name: string }[];
  activeProjectId?: string | null;
}

const STAGE_LABEL: Record<string, string> = {
  idle: "Idle",
  starting: "Starting",
  armed: "Listening for someone to speak",
  recording: "Recording",
  processing: "Processing",
  transcribing: "Transcribing",
  routing: "Routing across projects",
  ingested: "Ingested",
  idle_timeout: "No audio detected - stopped",
};

export function MeetingsView({
  meetings,
  autoSyncStatus,
  onSelectMeeting,
  captureStatus,
  onArmCapture,
  onStopCapture,
  projects = [],
  activeProjectId,
}: MeetingsViewProps) {
  const [search, setSearch] = useState("");
  const [landing, setLanding] = useState(activeProjectId || "");
  const [multi, setMulti] = useState<string[]>([]);
  const [maxMinutes, setMaxMinutes] = useState(20);
  const [speakers, setSpeakers] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const stage = captureStatus?.stage || "idle";
  const running = Boolean(captureStatus?.running);
  const armedOrRecording = running && (stage === "armed" || stage === "recording");

  const toggleMulti = (id: string) =>
    setMulti((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));

  const arm = async () => {
    const project = landing || activeProjectId || "";
    if (!project) {
      setErr("Choose the project this meeting belongs to.");
      return;
    }
    const candidates = Array.from(new Set([project, ...multi]));
    setBusy(true);
    setErr(null);
    try {
      await onArmCapture?.({
        project_id: project,
        candidate_project_ids: candidates,
        max_minutes: maxMinutes,
        speakers,
      });
    } catch (e: any) {
      setErr(e?.message || "Could not start capture.");
    } finally {
      setBusy(false);
    }
  };

  const visibleMeetings = useMemo(() => {
    const q = search.trim().toLowerCase();
    const base = q
      ? meetings.filter((meeting) =>
          [meeting.title, meeting.id, meeting.provider_conference_id]
            .filter(Boolean)
            .some((value) => String(value).toLowerCase().includes(q))
        )
      : meetings;
    return base.slice(0, 10);
  }, [meetings, search]);

  return (
    <div className="space-y-6">
      {/* Voice-activated capture. Arms and waits; nothing is recorded until
          someone actually speaks, and the run stops itself on silence. */}
      {onArmCapture && (
        <section className="rounded-2xl border border-border bg-surface p-5 shadow-xs space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold text-text-main">
                {armedOrRecording ? (
                  <Radio className="h-4 w-4 animate-pulse text-primary" />
                ) : (
                  <Mic className="h-4 w-4 text-primary" />
                )}
                Record this meeting
              </h2>
              <p className="mt-1 text-xs text-text-muted">
                Starts listening now. Recording begins when someone speaks and stops on
                silence, then the notes are filed automatically.
              </p>
            </div>
            <span
              className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${
                stage === "recording"
                  ? "bg-danger/10 text-danger"
                  : armedOrRecording
                    ? "bg-primary-soft text-primary"
                    : "bg-canvas text-text-muted"
              }`}
            >
              {STAGE_LABEL[stage] || stage}
            </span>
          </div>

          {err && (
            <p className="rounded-lg border border-danger/25 bg-danger/5 px-3 py-2 text-xs text-danger">
              {err}
            </p>
          )}
          {(captureStatus?.problems?.length ?? 0) > 0 && (
            <ul className="space-y-1 rounded-lg border border-warning/25 bg-warning/5 px-3 py-2 text-[11px] text-text-muted">
              {captureStatus!.problems!.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}

          {!running && (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-[11px] font-medium text-text-muted">
                Meeting belongs to
                <select
                  value={landing}
                  onChange={(e) => setLanding(e.target.value)}
                  className="w-full rounded-lg border border-border bg-canvas px-2.5 py-2 text-xs text-text-main"
                >
                  <option value="">Select a project…</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-[11px] font-medium text-text-muted">
                Also discussed
                <select
                  value=""
                  onChange={(e) => e.target.value && toggleMulti(e.target.value)}
                  className="w-full rounded-lg border border-border bg-canvas px-2.5 py-2 text-xs text-text-main"
                >
                  <option value="">Add another project…</option>
                  {projects
                    .filter((p) => p.id !== landing)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {multi.includes(p.id) ? "✓ " : ""}
                        {p.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="space-y-1 text-[11px] font-medium text-text-muted">
                Max minutes
                <input
                  type="number"
                  min={1}
                  max={180}
                  value={maxMinutes}
                  onChange={(e) => setMaxMinutes(Number(e.target.value) || 20)}
                  className="w-full rounded-lg border border-border bg-canvas px-2.5 py-2 text-xs text-text-main"
                />
              </label>
              <label className="space-y-1 text-[11px] font-medium text-text-muted">
                Speakers (0 = auto)
                <input
                  type="number"
                  min={0}
                  max={12}
                  value={speakers}
                  onChange={(e) => setSpeakers(Number(e.target.value) || 0)}
                  className="w-full rounded-lg border border-border bg-canvas px-2.5 py-2 text-xs text-text-main"
                />
              </label>
            </div>
          )}

          {multi.length > 0 && !running && (
            <div className="flex flex-wrap gap-1.5">
              {multi.map((id) => (
                <span
                  key={id}
                  className="inline-flex items-center gap-1 rounded-full bg-primary-soft px-2.5 py-1 text-[10px] font-medium text-primary"
                >
                  {projects.find((p) => p.id === id)?.name || id}
                  <button
                    onClick={() => toggleMulti(id)}
                    className="hover:text-danger"
                    aria-label="Remove"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2">
            {!running ? (
              <button
                onClick={arm}
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-3.5 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mic className="h-3.5 w-3.5" />}
                {busy ? "Starting…" : "Start listening"}
              </button>
            ) : (
              <button
                onClick={() => onStopCapture?.()}
                className="inline-flex items-center gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3.5 py-2 text-xs font-semibold text-danger transition-colors hover:bg-danger/15"
              >
                <Square className="h-3.5 w-3.5" />
                Stop
              </button>
            )}
            {running && (
              <span className="text-[11px] text-text-muted">
                {stage === "armed"
                  ? "Waiting for a voice — start your Meet and talk."
                  : stage === "recording"
                    ? "Recording. It will stop on its own after silence."
                    : "Working…"}
              </span>
            )}
          </div>
        </section>
      )}

      <header className="space-y-2">
        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-primary/15 bg-primary-soft px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
          <Video className="h-3.5 w-3.5" />
          AI processing
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-text-main">Meetings</h1>
        <p className="max-w-2xl text-sm text-text-muted">
          Synora receives transcripts and automatically extracts project knowledge. Open a meeting to inspect the result.
        </p>
      </header>

      {autoSyncStatus && (
        <section className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-border bg-surface p-4 shadow-xs">
            <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Google Meet</div>
            <div className="mt-2 flex items-center gap-2 text-sm font-semibold text-text-main">
              <span className={"h-2 w-2 rounded-full " + (autoSyncStatus.connected ? "bg-success" : "bg-text-muted")} />
              {autoSyncStatus.connected ? "Connected" : "Not connected"}
            </div>
          </div>
          <div className="rounded-xl border border-border bg-surface p-4 shadow-xs">
            <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Automation</div>
            <div className="mt-2 flex items-center gap-2 text-sm font-semibold text-text-main">
              <CircleCheck className="h-4 w-4 text-success" />
              {autoSyncStatus.active ? "Running" : "Waiting"}
            </div>
          </div>
          <div className="rounded-xl border border-border bg-surface p-4 shadow-xs">
            <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Latest event</div>
            <div className="mt-2 text-xs font-mono text-text-main">
              {autoSyncStatus.lastEventAt ? new Date(autoSyncStatus.lastEventAt).toLocaleString() : "No events yet"}
            </div>
          </div>
        </section>
      )}

      <section className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-border px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-text-main">Recent meetings</h2>
            <p className="mt-0.5 text-[11px] text-text-muted">Select one to inspect its transcript and extracted knowledge.</p>
          </div>
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search"
              aria-label="Search meetings"
              className="w-full rounded-lg border border-border bg-canvas py-2 pl-8 pr-3 text-xs text-text-main outline-none focus:border-primary"
            />
          </div>
        </div>

        {visibleMeetings.length === 0 ? (
          <div className="px-5 py-12 text-center text-xs text-text-muted">No meetings found.</div>
        ) : (
          <div className="divide-y divide-border">
            {visibleMeetings.map((meeting) => (
              <button
                key={meeting.id}
                onClick={() => onSelectMeeting(meeting.id)}
                className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left hover:bg-canvas/70 transition-colors"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-xs font-semibold text-text-main">{meeting.title || "Untitled meeting"}</span>
                    <span className="rounded-full bg-canvas px-2 py-0.5 text-[10px] text-text-muted">
                      {meeting.provider || "meeting"}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-text-muted">
                    <Clock3 className="h-3 w-3" />
                    {meeting.start_time ? new Date(meeting.start_time).toLocaleString() : "Time unavailable"}
                    {meeting.status ? " • " + meeting.status : ""}
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-text-muted" />
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}