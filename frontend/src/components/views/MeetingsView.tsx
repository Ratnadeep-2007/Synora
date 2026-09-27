"use client";

import React, { useState, useRef } from "react";
import {
  Video,
  Play,
  CheckCircle2,
  Clock,
  Users,
  ArrowRight,
  RefreshCw,
  Sparkles,
  FileText,
  Upload,
  X,
  Zap,
  Search,
} from "lucide-react";
import { MeetingItem } from "@/lib/types";
import { EmptyState } from "@/components/common/EmptyState";

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

export function MeetingsView({
  meetings,
  autoSyncStatus,
  onSelectMeeting,
  onProcessPipeline,
  onSyncGoogleMeet,
  onIngestTranscript,
}: MeetingsViewProps) {
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [isSyncingMeet, setIsSyncingMeet] = useState(false);
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  // Ingest Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [ingestTitle, setIngestTitle] = useState("");
  const [ingestProvider, setIngestProvider] = useState("manual_transcript");
  const [ingestTranscript, setIngestTranscript] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleProcess = async (e: React.MouseEvent, meetingId: string) => {
    e.stopPropagation();
    try {
      setProcessingId(meetingId);
      await onProcessPipeline(meetingId);
    } finally {
      setProcessingId(null);
    }
  };

  const handleSyncMeet = async () => {
    if (!onSyncGoogleMeet) return;
    try {
      setIsSyncingMeet(true);
      await onSyncGoogleMeet();
    } finally {
      setIsSyncingMeet(false);
    }
  };

  const handleSubmitIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ingestTranscript.trim()) {
      alert("Please enter or paste transcript dialogue.");
      return;
    }
    if (!onIngestTranscript) return;

    try {
      setIsSubmitting(true);
      await onIngestTranscript({
        title: ingestTitle.trim() || "Imported Meeting Transcript",
        raw_transcript: ingestTranscript,
        provider: ingestProvider,
      });
      setIsModalOpen(false);
      setIngestTranscript("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      if (content) {
        setIngestTranscript(content);
        if (!ingestTitle) {
          setIngestTitle(file.name.replace(/\.[^/.]+$/, ""));
        }
      }
    };
    reader.readAsText(file);
  };

  const sources = Array.from(new Set(meetings.map((m) => m.provider || "unknown")));
  const statuses = Array.from(new Set(meetings.map((m) => m.status || "unknown")));

  const filteredMeetings = meetings.filter((m) => {
    if (sourceFilter !== "all" && (m.provider || "unknown") !== sourceFilter) return false;
    if (statusFilter !== "all" && (m.status || "unknown") !== statusFilter) return false;
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      (m.title || "").toLowerCase().includes(q) ||
      m.id.toLowerCase().includes(q) ||
      (m.provider_conference_id || "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-main">
            Meetings
          </h1>
          <p className="text-sm text-text-muted mt-1">
            Native Google Meet transcription with automatic transcript synchronization.
            Select a meeting to inspect its transcript and extracted intelligence.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {onIngestTranscript && (
            <button
              onClick={() => setIsModalOpen(true)}
              className="px-3.5 py-2 text-xs font-semibold text-text-main bg-surface hover:bg-canvas border border-border rounded-md flex items-center gap-1.5 transition-colors shadow-xs"
              title="Manual transcript import — distinct from automatic Google Meet synchronization"
            >
              <Zap className="w-3.5 h-3.5 text-text-muted" />
              <span>Manual transcript import</span>
            </button>
          )}

          {onSyncGoogleMeet && (
            <button
              onClick={handleSyncMeet}
              disabled={isSyncingMeet}
              className="px-3.5 py-2 text-xs font-semibold text-text-main bg-surface hover:bg-surface/80 border border-border rounded-md flex items-center gap-1.5 transition-colors shadow-xs shrink-0 self-start md:self-auto disabled:opacity-50"
              title="Manual reconciliation: recovers events missed during outages or failed processing"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isSyncingMeet ? "animate-spin" : ""}`} />
              <span>{isSyncingMeet ? "Reconciling..." : "Sync now"}</span>
            </button>
          )}
        </div>
      </div>

      {/* Automatic sync status */}
      {autoSyncStatus && (
        <div className="p-5 rounded-xl bg-surface border border-border shadow-xs flex flex-wrap items-center justify-between gap-5">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1">
              Google Meet
            </div>
            <div className="flex items-center gap-1.5 text-sm font-semibold text-text-main">
              <span className={`w-2 h-2 rounded-full ${autoSyncStatus.connected ? "bg-success" : "bg-text-muted"}`} />
              <span>{autoSyncStatus.connected ? "Connected" : "Not connected"}</span>
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1">
              Automatic sync
            </div>
            <div className="flex items-center gap-1.5 text-sm font-semibold text-text-main">
              <span className={`w-2 h-2 rounded-full ${autoSyncStatus.active ? "bg-success animate-pulse" : "bg-warning"}`} />
              <span>{autoSyncStatus.active ? "Active" : "Paused"}</span>
              {typeof autoSyncStatus.subscriptionsCount === "number" && (
                <span className="text-[11px] font-mono text-text-muted">
                  {autoSyncStatus.subscriptionsCount} subscription{autoSyncStatus.subscriptionsCount === 1 ? "" : "s"}
                </span>
              )}
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1">
              Last event
            </div>
            <div className="text-sm font-mono text-text-main" suppressHydrationWarning>
              {autoSyncStatus.lastEventAt ? new Date(autoSyncStatus.lastEventAt).toLocaleString() : "No events yet"}
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-1">
              Transcript processing
            </div>
            <div className="text-sm font-mono text-text-main">
              {autoSyncStatus.pendingCount || 0} pending
            </div>
          </div>
        </div>
      )}

      {/* Filters: Search, Source, Status */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="w-3.5 h-3.5 text-text-muted absolute left-2.5 top-2.5" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search meetings…"
            aria-label="Search meetings"
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
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status"
          className="px-2.5 py-1.5 text-xs rounded-md bg-surface border border-border text-text-main focus:outline-none focus:ring-1 focus:ring-primary/40"
        >
          <option value="all">All statuses</option>
          {statuses.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {filteredMeetings.length === 0 ? (
          meetings.length === 0 ? (
          <div className="p-12 text-center text-sm text-text-muted bg-surface rounded-xl border border-border space-y-4">
            <Video className="w-10 h-10 text-text-muted mx-auto" />
            <div>
              <p className="font-semibold text-text-main text-base">No meetings found</p>
              <p className="text-xs text-text-muted mt-1 max-w-md mx-auto">
                {autoSyncStatus?.connected
                  ? "Automatic transcript synchronization is active. New native Meet transcripts appear here once Google generates them."
                  : "Connect Google Meet to enable automatic transcript synchronization, or use manual transcript import."}
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
              {onIngestTranscript && (
                <button
                  onClick={() => setIsModalOpen(true)}
                  className="px-4 py-2 bg-surface hover:bg-canvas text-text-main border border-border rounded-md text-xs font-semibold shadow-xs inline-flex items-center gap-2 transition-colors"
                >
                  <Zap className="w-4 h-4 text-text-muted" />
                  <span>Manual transcript import</span>
                </button>
              )}
            </div>
          </div>
          ) : (
            <EmptyState
              title="No meetings match these filters"
              description="Adjust the search, source, or status filters to find the meeting you are looking for."
            />
          )
        ) : (
          filteredMeetings.map((m) => (
            <div
              key={m.id}
              onClick={() => onSelectMeeting(m.id)}
              className="p-6 rounded-xl bg-surface border border-border shadow-xs hover:border-primary/40 transition-all cursor-pointer flex flex-col md:flex-row md:items-center justify-between gap-4 group"
            >
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-primary px-2 py-0.5 rounded bg-primary-soft border border-primary/20">
                    {m.provider || "Unknown source"}
                  </span>
                  {m.provider_conference_id?.startsWith("manual_") && (
                    <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-canvas text-text-muted border border-border">
                      Developer / Seeded Data
                    </span>
                  )}
                  <span className="text-xs text-text-muted font-mono">
                    ID: {m.provider_conference_id || m.id}
                  </span>
                </div>

                <h3 className="text-base font-semibold text-text-main group-hover:text-primary transition-colors">
                  {m.title || m.id}
                </h3>

                <div className="flex items-center gap-4 text-xs text-text-muted">
                  <div className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" />
                    <span suppressHydrationWarning>
                      {m.start_time ? new Date(m.start_time).toLocaleString() : "No timestamp"}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Users className="w-3.5 h-3.5" />
                    <span>{m.participants?.length || 0} Participants</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="font-mono">{m.status || "unknown"}</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 shrink-0">
                <button
                  onClick={(e) => handleProcess(e, m.id)}
                  disabled={processingId === m.id}
                  className="px-3.5 py-2 rounded-md bg-primary hover:bg-primary-hover text-surface text-xs font-semibold shadow-xs flex items-center gap-1.5 transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${processingId === m.id ? "animate-spin" : ""}`} />
                  <span>{processingId === m.id ? "Extracting..." : "Process Pipeline"}</span>
                </button>

                <button className="p-2 text-text-muted hover:text-text-main rounded-md hover:bg-canvas transition-colors">
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Ingestion Modal (Zero-Quota Alternative) */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-in fade-in duration-150">
          <div className="bg-surface border border-border rounded-xl shadow-xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
            <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-canvas/40">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                  <Zap className="w-4 h-4 text-primary" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-text-main">
                    Manual transcript import
                  </h2>
                  <p className="text-xs text-text-muted">
                    Manual file or pasted text — distinct from automatic Google Meet synchronization.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-text-muted hover:text-text-main p-1 rounded-md transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmitIngest} className="p-6 space-y-4 overflow-y-auto flex-1">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-text-main mb-1">
                    Meeting Title
                  </label>
                  <input
                    type="text"
                    required
                    value={ingestTitle}
                    onChange={(e) => setIngestTitle(e.target.value)}
                    placeholder="e.g. Architecture Sync"
                    className="w-full px-3 py-2 text-xs bg-canvas border border-border rounded-md text-text-main focus:outline-none focus:border-primary"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-text-main mb-1">
                    Source / Ingestion Type
                  </label>
                  <select
                    value={ingestProvider}
                    onChange={(e) => setIngestProvider(e.target.value)}
                    className="w-full px-3 py-2 text-xs bg-canvas border border-border rounded-md text-text-main focus:outline-none focus:border-primary"
                  >
                    <option value="manual_transcript">Manual transcript import</option>
                    <option value="google">Native Google Meet transcription</option>
                    <option value="whisper_stt">Local Offline Whisper AI</option>
                    <option value="zoom_teams">Zoom / MS Teams Export</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-main mb-1.5">
                  Dialogue Transcript Content
                </label>

                <textarea
                  rows={8}
                  required
                  value={ingestTranscript}
                  onChange={(e) => setIngestTranscript(e.target.value)}
                  placeholder={`Priya Sharma: We decided to store sessions in Redis.\nArjun Mehta: Agreed, and I will prepare the migration plan.`}
                  className="w-full font-mono text-xs px-3 py-2.5 bg-canvas border border-border rounded-md text-text-main focus:outline-none focus:border-primary leading-relaxed resize-y"
                />
                <p className="text-[11px] text-text-muted mt-1">
                  Accepts <code>Speaker: Message</code>, timestamped lines, WebVTT subtitle files, or copy-pasted Google Meet notes.
                </p>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-border">
                <div>
                  <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileUpload}
                    accept=".txt,.vtt,.srt"
                    className="hidden"
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="px-3 py-1.5 text-xs text-text-muted hover:text-text-main border border-border rounded-md flex items-center gap-1.5 transition-colors"
                  >
                    <Upload className="w-3.5 h-3.5" />
                    <span>Upload File (.txt, .vtt, .srt)</span>
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-main transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmitting || !ingestTranscript.trim()}
                    className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-md shadow-xs flex items-center gap-2 transition-colors disabled:opacity-50"
                  >
                    {isSubmitting ? (
                      <>
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        <span>Ingesting & Processing...</span>
                      </>
                    ) : (
                      <>
                        <Zap className="w-3.5 h-3.5 text-yellow-300" />
                        <span>Ingest & Extract Knowledge</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
