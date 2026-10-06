"use client";

import React, { useState } from "react";
import { ArrowRight, CircleCheck, Clock3, Search, Video } from "lucide-react";
import { MeetingItem } from "@/lib/types";

export interface VexaCaptureStatus {
  ok: boolean;
  meeting_id: string;
  meeting_code?: string;
  status: string;
  processed?: boolean;
  entries_count?: number;
  resolved_projects?: string[];
  recording_id?: string | null;
  sarvam_job_id?: string | null;
  error?: string | null;
}

interface MeetingsViewProps {
  meetings: MeetingItem[];
  autoSyncStatus?: {
    connected: boolean;
    active: boolean;
    lastEventAt?: string | null;
  };
  onSelectMeeting: (meetingId: string) => void;
  vexaCaptureStatus?: VexaCaptureStatus | null;
  onStartVexaCapture?: (meetingUrl: string) => Promise<void>;
  onStopVexaCapture?: () => Promise<void>;
}

const STATUS_LABELS: Record<string, string> = {
  idle: "Idle",
  starting: "Starting",
  waiting_for_recording: "Waiting for recording",
  recording_ready: "Recording ready",
  transcribing: "Transcribing",
  ingesting: "Updating Synora",
  completed: "Completed",
  stopping: "Finalizing recording",
  stopped: "Stopped",
  failed: "Failed",
};

export function MeetingsView({
  meetings,
  autoSyncStatus,
  onSelectMeeting,
  vexaCaptureStatus,
  onStartVexaCapture,
  onStopVexaCapture,
}: MeetingsViewProps) {
  const [search, setSearch] = useState("");
  const [meetingUrl, setMeetingUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const status = vexaCaptureStatus?.status || "idle";
  const running = [
    "starting",
    "waiting_for_recording",
    "recording_ready",
    "transcribing",
    "ingesting",
    "stopping",
  ].includes(status);

  const startCapture = async () => {
    if (!meetingUrl.trim()) {
      setError("Paste a Google Meet URL first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onStartVexaCapture?.(meetingUrl.trim());
    } catch (err: any) {
      setError(err?.message || "Could not start Vexa capture.");
    } finally {
      setBusy(false);
    }
  };

  const visibleMeetings = (() => {
    const q = search.trim().toLowerCase();
    const filtered = q
      ? meetings.filter((meeting) =>
          [meeting.title, meeting.id, meeting.provider_conference_id]
            .filter(Boolean)
            .some((value) => String(value).toLowerCase().includes(q))
        )
      : meetings;
    return filtered.slice(0, 20);
  })();

  return (
    <div className="space-y-6">
      {onStartVexaCapture && (
        <section className="rounded-2xl border border-border bg-surface p-5 shadow-xs space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold text-text-main">
                <Video className="h-4 w-4 text-primary" />
                Google Meet capture
              </h2>
              <p className="mt-1 text-xs text-text-muted">
                Vexa joins the meeting from this machine, records it, and Sarvam transcribes
                the completed recording. Synora routes the transcript automatically.
              </p>
            </div>
            <span className="shrink-0 rounded-full bg-canvas px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
              {STATUS_LABELS[status] || status}
            </span>
          </div>

          {error && (
            <p className="rounded-lg border border-danger/25 bg-danger/5 px-3 py-2 text-xs text-danger">
              {error}
            </p>
          )}
          {vexaCaptureStatus?.error && (
            <p className="rounded-lg border border-danger/25 bg-danger/5 px-3 py-2 text-xs text-danger">
              {vexaCaptureStatus.error}
            </p>
          )}

          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              value={meetingUrl}
              onChange={(e) => setMeetingUrl(e.target.value)}
              placeholder="https://meet.google.com/abc-defg-hij"
              className="flex-1 rounded-lg border border-border bg-canvas px-3 py-2 text-xs text-text-main outline-none focus:border-primary"
              disabled={running}
            />
            {!running ? (
              <button
                onClick={startCapture}
                disabled={busy}
                className="rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {busy ? "Starting…" : "Start capture"}
              </button>
            ) : (
              <button
                onClick={() => onStopVexaCapture?.()}
                className="rounded-lg border border-danger/30 bg-danger/10 px-4 py-2 text-xs font-semibold text-danger"
              >
                Stop capture
              </button>
            )}
          </div>

          <p className="text-[11px] text-text-muted">
            The other participant only needs the Google Meet link. The Vexa bot may need
            to be admitted from the Meet waiting room.
          </p>

          {vexaCaptureStatus?.processed && (
            <p className="text-[11px] text-success">
              {vexaCaptureStatus.entries_count || 0} transcript entries processed. Project
              routing, shared memory, and Project Atlas updates are complete.
            </p>
          )}
        </section>
      )}

      <header className="space-y-2">
        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-primary/15 bg-primary-soft px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
          <Video className="h-3.5 w-3.5" />
          AI processing
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-text-main">Meetings</h1>
        <p className="max-w-2xl text-sm text-text-muted">
          Synora receives meeting transcripts and extracts evidence-backed project knowledge.
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
            <p className="mt-0.5 text-[11px] text-text-muted">
              Select one to inspect its transcript and extracted knowledge.
            </p>
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
                    <span className="truncate text-xs font-semibold text-text-main">
                      {meeting.title || "Untitled meeting"}
                    </span>
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
