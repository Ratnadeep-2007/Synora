"use client";

import React, { useState } from "react";
import {
  Video,
  Clock,
  Users,
  Search,
  Sparkles,
  ArrowRight,
  ShieldCheck,
  Cpu,
  Layers,
  ChevronRight,
  Radio,
  FileText,
} from "lucide-react";
import { MeetingItem } from "@/lib/types";
import { ProgressLine } from "@/components/ui/primitives";

export interface VexaCaptureStatus {
  ok: boolean;
  meeting_id: string;
  meeting_code?: string;
  status: string;
  processed?: boolean;
  entries_count?: number;
  resolved_projects?: string[];
  recording_id?: string | null;
  transcription_provider?: string | null;
  transcription_model?: string | null;
  transcription_job_id?: string | null;
  transcription_fallback_used?: boolean;
  transcription_fallback_reason?: string | null;
  sarvam_job_id?: string | null;
  whisper_job_id?: string | null;
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
  starting: "Connecting Vexa Bot...",
  waiting_for_recording: "Admitted • Awaiting Audio Stream",
  recording_ready: "Recording Ingest Active",
  transcribing: "Neural Audio Transcription",
  transcribing_sarvam: "Sarvam Speech-to-Text",
  transcribing_whisper: "Whisper Neural Fallback",
  ingesting: "Consolidating into Project Brain",
  completed: "Synthesized & Synchronized",
  stopping: "Finalizing Audio Stream...",
  stopped: "Stopped",
  failed: "Stream Ingest Interrupted",
};

export function MeetingsView({
  meetings = [],
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

  const captureStatus = vexaCaptureStatus?.status || "idle";
  const isRunning = [
    "starting",
    "waiting_for_recording",
    "recording_ready",
    "transcribing",
    "transcribing_sarvam",
    "transcribing_whisper",
    "ingesting",
    "stopping",
  ].includes(captureStatus);

  const startCapture = async () => {
    if (!meetingUrl.trim()) {
      setError("Paste a valid Google Meet link first.");
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

  const filteredMeetings = meetings.filter((meeting) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      (meeting.title || "").toLowerCase().includes(q) ||
      (meeting.id || "").toLowerCase().includes(q) ||
      (meeting.provider_conference_id || "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-8 max-w-6xl mx-auto pb-16 view-enter">
      {/* Header */}
      <header className="reveal border-b border-border pb-6 flex flex-col md:flex-row md:items-end justify-between gap-4" style={{ "--reveal-delay": "0ms" } as React.CSSProperties}>
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">
            <Video className="h-3.5 w-3.5" />
            Audio Memory Stream
          </div>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-text-main">
            Meetings & Conversations
          </h1>
          <p className="mt-1 text-sm text-text-muted max-w-2xl leading-relaxed">
            Real-time audio streams and conferences transcribed and synthesized into verified project memory without manual note-taking.
          </p>
        </div>

        {/* Telemetry Indicator */}
        <div className="flex items-center gap-2 bg-surface px-3 py-1.5 rounded-xl border border-border text-xs text-text-muted">
          <span
            className={`w-2 h-2 rounded-full ${
              autoSyncStatus?.connected ? "bg-primary animate-pulse" : "bg-text-muted"
            }`}
          />
          <span>
            {autoSyncStatus?.connected ? "Google Meet Stream Active" : "Stream Standby"}
          </span>
        </div>
      </header>

      {/* Vexa Neural Capture Console */}
      {onStartVexaCapture && (
        <section className="reveal rounded-2xl border border-border bg-surface p-5 sm:p-6 shadow-sm relative overflow-hidden space-y-4" style={{ "--reveal-delay": "60ms" } as React.CSSProperties}>
          {isRunning && <ProgressLine className="absolute top-0 left-0 right-0" />}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                <Radio className="w-4 h-4 animate-pulse" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-text-main flex items-center gap-2">
                  <span>Google Meet Neural Capture Deck</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-canvas border border-border text-primary uppercase">
                    Sarvam + Whisper
                  </span>
                </h2>
                <p className="text-xs text-text-muted">
                  Vexa joins the conference directly, streams high-fidelity audio, and extracts project facts.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-text-muted px-2.5 py-1 rounded-full bg-canvas border border-border">
                Status: <strong className="text-primary">{STATUS_LABELS[captureStatus] || captureStatus}</strong>
              </span>
            </div>
          </div>

          {error && (
            <div className="p-3 rounded-xl bg-danger/10 border border-danger/25 text-danger text-xs">
              {error}
            </div>
          )}

          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <input
                type="url"
                value={meetingUrl}
                onChange={(e) => setMeetingUrl(e.target.value)}
                placeholder="https://meet.google.com/xxx-yyyy-zzz"
                disabled={isRunning}
                className="w-full px-3.5 py-2.5 rounded-xl bg-canvas border border-border focus:border-primary text-xs text-text-main placeholder:text-text-muted"
              />
            </div>

            {!isRunning ? (
              <button
                onClick={startCapture}
                disabled={busy}
                className="px-5 py-2.5 rounded-xl bg-primary hover:bg-primary-hover text-white text-xs font-semibold transition-all shadow-[0_0_14px_rgba(16,185,129,0.2)] disabled:opacity-50 shrink-0"
              >
                {busy ? "Deploying Bot..." : "Deploy Vexa Bot"}
              </button>
            ) : (
              <button
                onClick={() => onStopVexaCapture?.()}
                className="px-5 py-2.5 rounded-xl bg-danger/20 hover:bg-danger/30 text-danger border border-danger/30 text-xs font-semibold transition-all shrink-0"
              >
                Terminate Capture
              </button>
            )}
          </div>
        </section>
      )}

      {/* Filter / Search Bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-text-muted absolute left-3.5 top-3" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search meetings by title or ID..."
            className="w-full pl-9 pr-3 py-2 rounded-xl bg-surface border border-border text-xs text-text-main placeholder:text-text-muted focus:border-primary"
          />
        </div>

        <span className="text-xs font-mono text-text-muted">
          {filteredMeetings.length} Meeting Session{filteredMeetings.length === 1 ? "" : "s"}
        </span>
      </div>

      {/* Visual Memory Timeline */}
      <section className="space-y-4">
        <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-text-muted">
          Chronological Memory Stream
        </div>

        {filteredMeetings.length === 0 ? (
          <div className="p-12 text-center text-xs text-text-muted border border-dashed border-border rounded-2xl bg-surface/50 space-y-2">
            <Video className="w-8 h-8 text-text-muted/40 mx-auto" />
            <p>No meeting memory entries recorded yet.</p>
            <p className="text-[11px] text-text-muted/60">
              Deploy Vexa to a live Google Meet or connect your Google Workspace account to begin automatic transcription.
            </p>
          </div>
        ) : (
          <div className="space-y-4 relative before:absolute before:inset-0 before:left-4 before:w-0.5 before:bg-border/60 before:-z-0">
            {filteredMeetings.map((meeting, mIdx) => {
              const participants = meeting.participants || [];
              const transcripts = meeting.transcripts || [];
              const liveTranscripts = transcripts.filter((t) => t.state === "AVAILABLE").length;
              const startTime = meeting.start_time
                ? new Date(meeting.start_time).toLocaleString([], {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : "Historical";

              return (
                <div
                  key={meeting.id}
                  onClick={() => onSelectMeeting(meeting.id)}
                  className="reveal relative z-10 p-5 rounded-2xl bg-surface border border-border hover:border-primary/40 transition-all cursor-pointer group shadow-xs hover:shadow-sm space-y-4"
                  style={{ "--reveal-delay": `${Math.min(mIdx, 8) * 50}ms` } as React.CSSProperties}
                >
                  {/* Top Bar: Title, Date, Action */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-3">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary group-hover:scale-105 transition-transform">
                        <Video className="w-4 h-4" />
                      </div>
                      <div>
                        <h3 className="text-sm font-bold text-text-main group-hover:text-primary transition-colors">
                          {meeting.title || "Untitled Meeting Session"}
                        </h3>
                        <div className="flex items-center gap-2 text-[11px] text-text-muted font-mono mt-0.5">
                          <Clock className="w-3 h-3" />
                          <span>{startTime}</span>
                          <span>•</span>
                          <span>{meeting.provider || "Google Meet"}</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 self-end sm:self-auto">
                      <span className="text-xs font-medium text-primary flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                        <span>Inspect Memory</span>
                        <ChevronRight className="w-3.5 h-3.5" />
                      </span>
                    </div>
                  </div>

                  {/* 4-Stage Intelligence Flow: Meeting → Evidence → Extracted Intelligence → Project Impact */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 pt-1 text-xs">
                    {/* Stage 1: Audio Source */}
                    <div className="p-3 rounded-xl bg-canvas border border-border space-y-1">
                      <div className="text-[9px] font-bold uppercase tracking-wider text-text-muted flex items-center gap-1">
                        <span>1. Audio Ingest</span>
                      </div>
                      <div className="font-semibold text-text-main text-[11px] truncate">
                        {participants.length > 0 ? `${participants.length} Speakers` : "Neural Stream"}
                      </div>
                      <div className="text-[10px] text-text-muted truncate">
                        {meeting.provider_conference_id || "Live Ingest"}
                      </div>
                    </div>

                    {/* Stage 2: Transcribed Evidence */}
                    <div className="p-3 rounded-xl bg-canvas border border-border space-y-1">
                      <div className="text-[9px] font-bold uppercase tracking-wider text-text-muted flex items-center gap-1">
                        <span>2. Evidence</span>
                      </div>
                      <div className="font-semibold text-primary text-[11px]">
                        {transcripts.length > 0
                          ? `${transcripts.length} transcript${transcripts.length === 1 ? "" : "s"}`
                          : "No transcript yet"}
                      </div>
                      <div className="text-[10px] text-text-muted">
                        {liveTranscripts > 0
                          ? `${liveTranscripts} available · speaker attributed`
                          : "Awaiting capture or sync"}
                      </div>
                    </div>

                    {/* Stage 3: Extracted Intelligence */}
                    <div className="p-3 rounded-xl bg-canvas border border-border space-y-1">
                      <div className="text-[9px] font-bold uppercase tracking-wider text-text-muted flex items-center gap-1">
                        <span>3. Intelligence</span>
                      </div>
                      <div className="font-semibold text-text-main text-[11px]">
                        Decisions & Reqs
                      </div>
                      <div className="text-[10px] text-text-muted">
                        Synthesized by Synora
                      </div>
                    </div>

                    {/* Stage 4: Project State Impact */}
                    <div className="p-3 rounded-xl bg-canvas border border-border space-y-1">
                      <div className="text-[9px] font-bold uppercase tracking-wider text-text-muted flex items-center gap-1">
                        <span>4. Project Impact</span>
                      </div>
                      <div className="font-semibold text-success text-[11px] flex items-center gap-1">
                        <ShieldCheck className="w-3 h-3" />
                        <span>State Synced</span>
                      </div>
                      <div className="text-[10px] text-text-muted">
                        Living Atlas visual notes updated
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
