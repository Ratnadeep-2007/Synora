"use client";

import React, { useEffect, useState } from "react";
import { CheckCircle2, MessageCircle, Plug, Video } from "lucide-react";
import { SourceConnection, WhatsAppStatus } from "@/lib/types";
import { api } from "@/lib/api";

interface SourcesViewProps {
  connections: SourceConnection[];
  subscriptionsActive?: boolean;
  lastMeetEventAt?: string | null;
  pendingMeetEvents?: number;
  onConnectGoogle: () => void;
  onSyncGoogleMeet?: () => Promise<void>;
  onNavigateToArchitecture?: () => void;
}

function Status({ active, label }: { active: boolean; label: string }) {
  return (
    <span className={"inline-flex items-center gap-1.5 text-[11px] font-medium " + (active ? "text-success" : "text-text-muted")}>
      <span className={"h-1.5 w-1.5 rounded-full " + (active ? "bg-success" : "bg-text-muted")} />
      {label}
    </span>
  );
}

export function SourcesView({
  connections,
  subscriptionsActive = false,
  onConnectGoogle,
}: SourcesViewProps) {
  const [waStatus, setWaStatus] = useState<WhatsAppStatus | null>(null);
  const googleConn = connections.find((connection) => connection.provider === "google");

  useEffect(() => {
    const load = () => api.getWhatsAppStatus().then(setWaStatus).catch(() => setWaStatus(null));
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  const whatsappSession = waStatus?.details?.session_status || waStatus?.status || "unconfigured";
  const whatsappConnected = whatsappSession === "connected";

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-border bg-surface px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          <Plug className="h-3.5 w-3.5 text-primary" />
          Connected sources
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-text-main">Sources</h1>
        <p className="max-w-2xl text-sm text-text-muted">
          Connect the information streams Synora uses. After connection, project processing is automatic.
        </p>
      </header>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-border bg-surface p-5 shadow-xs">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-soft text-primary">
                <Video className="h-4 w-4" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-text-main">Google Meet</h2>
                <p className="text-[11px] text-text-muted">Meeting transcripts</p>
              </div>
            </div>
            <Status
              active={googleConn?.status === "active"}
              label={googleConn?.status === "active" ? "Connected" : "Not connected"}
            />
          </div>

          <div className="mt-5 rounded-xl border border-border bg-canvas p-4 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-text-muted">Automatic sync</span>
              <span className="font-semibold text-text-main">{subscriptionsActive ? "On" : "Off"}</span>
            </div>
            {googleConn?.account_email && (
              <div className="mt-2 flex items-center justify-between gap-3">
                <span className="text-text-muted">Account</span>
                <span className="truncate font-medium text-text-main">{googleConn.account_email}</span>
              </div>
            )}
          </div>

          <button
            onClick={onConnectGoogle}
            className="mt-4 w-full rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
          >
            {googleConn?.status === "active" ? "Reconnect Google Meet" : "Connect Google Meet"}
          </button>
        </div>

        <div className="rounded-2xl border border-border bg-surface p-5 shadow-xs">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-canvas text-text-main">
                <MessageCircle className="h-4 w-4" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-text-main">WhatsApp</h2>
                <p className="text-[11px] text-text-muted">Group messages via Baileys</p>
              </div>
            </div>
            <Status
              active={whatsappConnected}
              label={
                whatsappConnected
                  ? "Connected"
                  : whatsappSession === "reconnecting"
                  ? "Reconnecting"
                  : "Not connected"
              }
            />
          </div>

          <div className="mt-5 rounded-xl border border-border bg-canvas p-4 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-text-muted">Active groups</span>
              <span className="font-mono font-semibold text-text-main">
                {whatsappConnected ? waStatus?.details?.active_groups_count ?? "—" : "—"}
              </span>
            </div>
          </div>

          {!whatsappConnected && (
            <div className="mt-4 rounded-xl border border-border bg-canvas/60 p-4 text-[11px] leading-5 text-text-muted">
              Start the Baileys bridge and scan the WhatsApp QR code from Linked Devices. Synora then handles group processing automatically.
            </div>
          )}
        </div>
      </section>

      <div className="inline-flex items-center gap-2 rounded-xl border border-primary/15 bg-primary-soft/40 px-4 py-3 text-[11px] text-primary">
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
        No manual processing controls are required here.
      </div>
    </div>
  );
}