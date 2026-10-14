"use client";

import React, { useEffect, useState } from "react";
import {
  Video,
  MessageCircle,
  Plug,
} from "lucide-react";
import { Project, SourceConnection, WhatsAppStatus } from "@/lib/types";
import { ContextInboxPanel } from "./ContextInboxPanel";
import { api } from "@/lib/api";

interface SourcesViewProps {
  connections: SourceConnection[];
  projects?: Project[];
  unknownPendingCount?: number;
  onChanged?: () => Promise<void> | void;
  subscriptionsActive?: boolean;
  lastMeetEventAt?: string | null;
  pendingMeetEvents?: number;
  onConnectGoogle: () => void;
  onSyncGoogleMeet?: () => Promise<void>;
}

export function SourcesView({
  connections = [],
  projects = [],
  unknownPendingCount = 0,
  onChanged,
  subscriptionsActive = false,
  lastMeetEventAt,
  pendingMeetEvents = 0,
  onConnectGoogle,
  onSyncGoogleMeet,
}: SourcesViewProps) {
  const [waStatus, setWaStatus] = useState<WhatsAppStatus | null>(null);

  const googleConn = connections.find((c) => c.provider === "google");

  useEffect(() => {
    const load = () =>
      api.getWhatsAppStatus().then(setWaStatus).catch(() => setWaStatus(null));
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  const whatsappSession = waStatus?.details?.session_status || waStatus?.status || "unconfigured";
  const whatsappConnected = whatsappSession === "connected";

  return (
    <div className="space-y-8 max-w-6xl mx-auto pb-16 view-enter">
      {/* Header */}
      <header className="border-b border-border pb-6 flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">
            <Plug className="h-3.5 w-3.5" />
            Connections
          </div>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-text-main">
            Stream Sources
          </h1>
          <p className="mt-1 text-sm text-text-muted max-w-2xl leading-relaxed">
            Manage connected accounts for automatic meeting and group-message ingestion. Unmatched content waits in the inbox below.
          </p>
        </div>

      </header>

      {/* Main Stream Connectors (2-Column Grid) */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Google Meet Stream Card */}
        <section className="rounded-2xl border border-border bg-surface p-6 shadow-xs flex flex-col justify-between space-y-5">
          <div className="space-y-4">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                  <Video className="w-6 h-6" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-text-main">Google Meet Stream</h2>
                  <p className="text-xs text-text-muted">Audio streams & meeting transcripts</p>
                </div>
              </div>

              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${
                  googleConn?.status === "active"
                    ? "bg-success/10 text-success border border-success/20"
                    : "bg-surface-soft text-text-muted border border-border"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    googleConn?.status === "active" ? "bg-success" : "bg-text-muted"
                  }`}
                />
                {googleConn?.status === "active" ? "Connected" : "Standby"}
              </span>
            </div>

            <p className="text-xs text-text-muted leading-relaxed">
              Receives conference audio, synchronizes transcripts via Sarvam and Whisper, and extracts authoritative architectural decisions.
            </p>

            <div className="p-3.5 rounded-xl bg-canvas border border-border space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-text-muted">Auto-Sync Webhook</span>
                <span className="font-semibold text-text-main">
                  {subscriptionsActive ? "Active" : "Not configured"}
                </span>
              </div>
              {googleConn?.account_email && (
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Authorized Account</span>
                  <span className="font-mono text-primary truncate max-w-[180px]">
                    {googleConn.account_email}
                  </span>
                </div>
              )}
              {lastMeetEventAt && (
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Last Event</span>
                  <span className="font-mono text-text-muted text-[11px]">
                    {new Date(lastMeetEventAt).toLocaleTimeString()}
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <button
              onClick={onConnectGoogle}
              className="w-full py-2.5 px-4 rounded-xl bg-primary hover:bg-primary-hover text-white text-xs font-semibold transition-all shadow-[0_0_14px_rgba(16,185,129,0.2)]"
            >
              {googleConn?.status === "active"
                ? "Reconnect Google Workspace"
                : "Authorize Google Meet Stream"}
            </button>
            {onSyncGoogleMeet && googleConn?.status === "active" && (
              <button
                onClick={onSyncGoogleMeet}
                className="w-full py-2 px-3 rounded-xl bg-canvas hover:bg-surface text-text-muted hover:text-text-main border border-border text-xs transition-colors"
              >
                Trigger Immediate Meet Sync
              </button>
            )}
          </div>
        </section>

        {/* WhatsApp Baileys Stream Card */}
        <section className="rounded-2xl border border-border bg-surface p-6 shadow-xs flex flex-col justify-between space-y-5">
          <div className="space-y-4">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
                  <MessageCircle className="w-6 h-6" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-text-main">WhatsApp Stream</h2>
                  <p className="text-xs text-text-muted">Group messages via Baileys bridge</p>
                </div>
              </div>

              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${
                  whatsappConnected
                    ? "bg-success/10 text-success border border-success/20"
                    : "bg-surface-soft text-text-muted border border-border"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    whatsappConnected ? "bg-success" : "bg-text-muted"
                  }`}
                />
                {whatsappConnected ? "Connected" : "Bridge Standby"}
              </span>
            </div>

            <p className="text-xs text-text-muted leading-relaxed">
              Monitors WhatsApp group text, voice notes, audio, and shared images. Transcribed speech and image descriptions can provide project evidence for review.
            </p>

            <div className="p-3.5 rounded-xl bg-canvas border border-border space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-text-muted">Monitored Groups</span>
                <span className="font-mono font-semibold text-text-main">
                  {whatsappConnected ? waStatus?.details?.active_groups_count ?? 0 : "Standby"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-text-muted">Bridge Protocol</span>
                <span className="font-mono text-primary text-[11px]">
                  Baileys Multi-Device v2
                </span>
              </div>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-canvas/60 border border-border text-[11px] text-text-muted leading-relaxed">
            {whatsappConnected
              ? "WhatsApp bridge is active and receiving live socket frames."
              : "Start the Baileys bridge process to link via QR code. Messages will automatically route to Synora."}
          </div>
        </section>
      </div>

      <ContextInboxPanel projects={projects} pendingCount={unknownPendingCount} onChanged={onChanged} />
    </div>
  );
}
