"use client";

import React, { useEffect, useState } from "react";
import { CheckCircle2, MessageCircle, PenTool, RefreshCw, Shield, Video } from "lucide-react";
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
  return <span className={`inline-flex items-center gap-1.5 text-[11px] font-medium ${active ? "text-success" : "text-text-muted"}`}><span className={`w-1.5 h-1.5 rounded-full ${active ? "bg-success" : "bg-text-muted"}`} />{label}</span>;
}

export function SourcesView({ connections, subscriptionsActive = false, lastMeetEventAt = null, pendingMeetEvents = 0, onConnectGoogle, onSyncGoogleMeet, onNavigateToArchitecture }: SourcesViewProps) {
  const [waStatus, setWaStatus] = useState<WhatsAppStatus | null>(null);
  const googleConn = connections.find((c) => c.provider === "google");

  useEffect(() => { api.getWhatsAppStatus().then(setWaStatus).catch(() => setWaStatus(null)); }, []);

  const googleConnected = googleConn?.status === "active";
  const whatsappConnected = waStatus?.details?.session_status === "connected";

  return (
    <div className="space-y-6">
      <header>
        <p className="text-[11px] uppercase tracking-wider font-semibold text-primary">Sources</p>
        <h1 className="text-xl font-semibold tracking-tight text-text-main mt-1">Where Synora gets project information</h1>
        <p className="text-xs text-text-muted mt-1 max-w-2xl">Connect the sources used by this project. Source evidence remains separate from authoritative project state.</p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <section className="p-5 rounded-xl bg-surface border border-border">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3"><div className="w-9 h-9 rounded-lg bg-primary-soft text-primary flex items-center justify-center"><Video className="w-4 h-4" /></div><div><h2 className="text-sm font-semibold text-text-main">Google Meet</h2><p className="text-[11px] text-text-muted">Meeting transcripts</p></div></div>
            <Status active={googleConnected} label={googleConnected ? "Connected" : "Not connected"} />
          </div>
          <div className="mt-4 pt-3 border-t border-border text-xs space-y-2">
            <div className="flex justify-between gap-3"><span className="text-text-muted">Account</span><span className="font-medium text-text-main truncate">{googleConn?.account_email || "—"}</span></div>
            <div className="flex justify-between"><span className="text-text-muted">Automatic sync</span><span className="text-text-main">{subscriptionsActive ? "On" : "Off"}</span></div>
            <div className="flex justify-between"><span className="text-text-muted">Pending events</span><span className="text-text-main">{pendingMeetEvents}</span></div>
          </div>
          <div className="mt-4 flex gap-2">
            <button onClick={onConnectGoogle} className="flex-1 px-3 py-1.5 rounded-md bg-primary text-white text-xs font-semibold">{googleConnected ? "Reconnect" : "Connect"}</button>
            {onSyncGoogleMeet && <button onClick={onSyncGoogleMeet} className="px-3 py-1.5 rounded-md border border-border text-xs text-text-main hover:bg-canvas" title="Reconcile recent Meet events"><RefreshCw className="w-3.5 h-3.5" /></button>}
          </div>
          {lastMeetEventAt && <p className="mt-2 text-[11px] text-text-muted">Last event: {new Date(lastMeetEventAt).toLocaleString()}</p>}
        </section>

        <section className="p-5 rounded-xl bg-surface border border-border">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3"><div className="w-9 h-9 rounded-lg bg-canvas text-text-main flex items-center justify-center border border-border"><MessageCircle className="w-4 h-4" /></div><div><h2 className="text-sm font-semibold text-text-main">WhatsApp</h2><p className="text-[11px] text-text-muted">Group messages via Baileys</p></div></div>
            <Status active={whatsappConnected} label={whatsappConnected ? "Connected" : "Not connected"} />
          </div>
          <div className="mt-4 pt-3 border-t border-border text-xs space-y-2">
            <div className="flex justify-between"><span className="text-text-muted">Session</span><span className="text-text-main">{waStatus?.details?.session_status || waStatus?.status || "—"}</span></div>
            <div className="flex justify-between"><span className="text-text-muted">Active groups</span><span className="text-text-main font-mono">{waStatus?.details?.active_groups_count ?? "—"}</span></div>
            <div className="flex justify-between"><span className="text-text-muted">Latency</span><span className="text-text-main font-mono">{waStatus ? `${waStatus.latency_ms} ms` : "—"}</span></div>
          </div>
          <div className="mt-4 p-3 rounded-lg bg-canvas border border-border text-[11px] text-text-muted">Messages enter Synora as evidence and are matched to a project context under connector policy.</div>
        </section>

        <section className="p-5 rounded-xl bg-surface border border-border">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3"><div className="w-9 h-9 rounded-lg bg-canvas text-text-main flex items-center justify-center border border-border"><PenTool className="w-4 h-4" /></div><div><h2 className="text-sm font-semibold text-text-main">Excalidraw</h2><p className="text-[11px] text-text-muted">Living visual workspace</p></div></div>
            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-success"><CheckCircle2 className="w-3.5 h-3.5" />Ready</span>
          </div>
          <div className="mt-4 pt-3 border-t border-border space-y-2 text-xs text-text-muted"><p>Visual architecture, workflows, decisions, and requirements.</p><p>Important visual changes can be reviewed before they are applied.</p></div>
          {onNavigateToArchitecture && <button onClick={onNavigateToArchitecture} className="mt-4 w-full px-3 py-1.5 rounded-md border border-border text-xs font-semibold text-text-main hover:bg-canvas">Open workspace</button>}
        </section>
      </div>

      <section className="p-4 rounded-lg border border-border bg-canvas text-[11px] text-text-muted flex items-start gap-2"><Shield className="w-3.5 h-3.5 shrink-0 mt-0.5 text-primary" /><span>Credentials stay server-side. Source access follows permissions and connector state.</span></section>
    </div>
  );
}
