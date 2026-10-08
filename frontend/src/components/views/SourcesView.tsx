"use client";

import React, { useEffect, useState } from "react";
import {
  Video,
  MessageCircle,
  Plug,
  CheckCircle2,
  Sparkles,
  Send,
  Radio,
  Clock,
  ArrowRight,
  ShieldAlert,
} from "lucide-react";
import { SourceConnection, WhatsAppStatus, WhatsAppSimulateResult } from "@/lib/types";
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

export function SourcesView({
  connections = [],
  subscriptionsActive = false,
  lastMeetEventAt,
  pendingMeetEvents = 0,
  onConnectGoogle,
  onSyncGoogleMeet,
  onNavigateToArchitecture,
}: SourcesViewProps) {
  const [waStatus, setWaStatus] = useState<WhatsAppStatus | null>(null);
  const [simText, setSimText] = useState("");
  const [simSender, setSimSender] = useState("Alex (Lead Architect)");
  const [simGroup, setSimGroup] = useState("Synora Engineering Group");
  const [simulating, setSimulating] = useState(false);
  const [simResult, setSimResult] = useState<WhatsAppSimulateResult | null>(null);
  const [simError, setSimError] = useState<string | null>(null);

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

  const handleSimulate = async (customText?: string) => {
    const textToRun = (customText || simText).trim();
    if (!textToRun) return;

    setSimulating(true);
    setSimError(null);
    try {
      const res = await api.simulateWhatsAppMessage({
        text: textToRun,
        sender_name: simSender,
        group_name: simGroup,
      });
      setSimResult(res);
      if (!customText) setSimText("");
    } catch (err: any) {
      setSimError(err.message || "Simulation injection failed");
    } finally {
      setSimulating(false);
    }
  };

  const PRESET_MESSAGES = [
    "Decision: We agreed to use PostgreSQL with pgvector for the memory embeddings layer.",
    "Requirement: The visual canvas must isolate scroll gestures to prevent history navigation.",
    "Architecture: We are decoupling the audio transcription worker into a background microservice.",
  ];

  return (
    <div className="space-y-8 max-w-6xl mx-auto pb-16 view-enter">
      {/* Header */}
      <header className="border-b border-border pb-6 flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">
            <Plug className="h-3.5 w-3.5" />
            Communication Connectors
          </div>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-text-main">
            Stream Sources
          </h1>
          <p className="mt-1 text-sm text-text-muted max-w-2xl leading-relaxed">
            Connect the communication streams Synora monitors. Synora continuously listens, indexes verbatim evidence, and keeps project state synchronized.
          </p>
        </div>

        <div className="flex items-center gap-2 bg-surface px-3 py-1.5 rounded-xl border border-border text-xs text-text-muted">
          <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
          <span>Stream Ingestion Active</span>
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
                  {subscriptionsActive ? "Active" : "Enabled"}
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
              Monitors engineering and stakeholder WhatsApp group threads in real-time, routing decisions and requirements directly into project memory.
            </p>

            <div className="p-3.5 rounded-xl bg-canvas border border-border space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-text-muted">Monitored Groups</span>
                <span className="font-mono font-semibold text-text-main">
                  {whatsappConnected ? waStatus?.details?.active_groups_count ?? "4 active" : "Standby"}
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

      {/* Live Stream Simulation Sandbox */}
      <section className="rounded-2xl border border-border bg-surface p-6 shadow-sm relative overflow-hidden space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border/80 pb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-bold text-text-main flex items-center gap-2">
                <span>Stream Intelligence Simulation Sandbox</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-canvas border border-border text-primary uppercase">
                  Interactive
                </span>
              </h2>
              <p className="text-xs text-text-muted">
                Inject a sample chat packet to observe how Synora extracts evidence, updates state, and generates visual notes.
              </p>
            </div>
          </div>

          <span className="text-xs text-text-muted font-mono">
            Direct Pipeline Ingestion
          </span>
        </div>

        {/* Preset quick buttons */}
        <div className="space-y-1.5">
          <div className="text-[10px] font-bold uppercase tracking-wider text-text-muted">
            Quick Ingest Presets
          </div>
          <div className="flex flex-wrap gap-2">
            {PRESET_MESSAGES.map((msg, i) => (
              <button
                key={i}
                onClick={() => handleSimulate(msg)}
                disabled={simulating}
                className="px-3 py-1.5 rounded-lg bg-canvas hover:bg-surface-soft border border-border hover:border-primary/40 text-xs text-text-muted hover:text-text-main transition-all text-left truncate max-w-md disabled:opacity-50"
              >
                "{msg}"
              </button>
            ))}
          </div>
        </div>

        {/* Custom text input */}
        <div className="space-y-3">
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-semibold text-text-muted block mb-1">
                Sender Attribution
              </label>
              <input
                type="text"
                value={simSender}
                onChange={(e) => setSimSender(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-canvas border border-border text-xs text-text-main focus:border-primary"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-text-muted block mb-1">
                Origin Group Channel
              </label>
              <input
                type="text"
                value={simGroup}
                onChange={(e) => setSimGroup(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-canvas border border-border text-xs text-text-main focus:border-primary"
              />
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              value={simText}
              onChange={(e) => setSimText(e.target.value)}
              placeholder="e.g. Decision: We will use PostgreSQL with pgvector for the vector store"
              className="flex-1 px-3.5 py-2.5 rounded-xl bg-canvas border border-border text-xs text-text-main placeholder:text-text-muted focus:border-primary"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSimulate();
              }}
            />
            <button
              onClick={() => handleSimulate()}
              disabled={simulating || !simText.trim()}
              className="px-5 py-2.5 rounded-xl bg-primary hover:bg-primary-hover text-white text-xs font-semibold transition-all shadow-[0_0_14px_rgba(16,185,129,0.2)] disabled:opacity-50 flex items-center justify-center gap-1.5 shrink-0"
            >
              <Send className="w-3.5 h-3.5" />
              <span>{simulating ? "Processing..." : "Inject Packet"}</span>
            </button>
          </div>
        </div>

        {/* Simulation Output Feedback */}
        {simError && (
          <div className="p-3 rounded-xl bg-danger/10 border border-danger/30 text-danger text-xs">
            {simError}
          </div>
        )}

        {simResult && (
          <div className="p-4 rounded-xl bg-canvas border border-primary/30 space-y-2 text-xs animate-in fade-in duration-200">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-success flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4" />
                Packet Ingested & Synthesized into Memory
              </span>
              <span className="font-mono text-[10px] text-text-muted">
                Status: {simResult.status || "processed"}
              </span>
            </div>

            <div className="text-text-muted text-[11px] leading-relaxed">
              Synora processed the packet as verbatim evidence, verified project boundaries, and refreshed shared memory.
            </div>

            {onNavigateToArchitecture && (
              <button
                onClick={onNavigateToArchitecture}
                className="inline-flex items-center gap-1.5 text-primary text-xs font-medium hover:underline pt-1"
              >
                <span>View updated Project Atlas canvas</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}