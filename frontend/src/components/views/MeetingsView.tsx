"use client";

import React, { useMemo, useState } from "react";
import { ArrowRight, CircleCheck, Clock3, Search, Video } from "lucide-react";
import { MeetingItem } from "@/lib/types";

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
}

export function MeetingsView({ meetings, autoSyncStatus, onSelectMeeting }: MeetingsViewProps) {
  const [search, setSearch] = useState("");

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