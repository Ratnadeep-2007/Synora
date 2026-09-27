"use client";

import React, { useState, useEffect } from "react";
import {
  Plug,
  CheckCircle2,
  Shield,
  Clock,
  ExternalLink,
  RefreshCw,
  MessageSquare,
  PenTool,
  MessageCircle,
  Send,
  Smartphone,
  Sparkles,
  ArrowRight,
  Bot,
  Zap,
} from "lucide-react";
import { SourceConnection, WhatsAppMessageItem, WhatsAppSimulateResult, WhatsAppStatus } from "@/lib/types";
import { api } from "@/lib/api";

interface SourcesViewProps {
  connections: SourceConnection[];
  subscriptionsActive?: boolean;
  lastMeetEventAt?: string | null;
  pendingMeetEvents?: number;
  onConnectGoogle: () => void;
  onSyncGoogleMeet?: () => Promise<void>;
  onReconcileMeet?: () => Promise<void>;
  onSyncSlack?: (channel: string) => Promise<void>;
  onNavigateToArchitecture?: () => void;
  onRefreshData?: () => Promise<void>;
}

export function SourcesView({
  connections,
  subscriptionsActive = false,
  lastMeetEventAt = null,
  pendingMeetEvents = 0,
  onConnectGoogle,
  onSyncGoogleMeet,
  onReconcileMeet,
  onSyncSlack,
  onNavigateToArchitecture,
  onRefreshData,
}: SourcesViewProps) {
  const [slackChannel, setSlackChannel] = useState("general");
  const [isSyncingSlack, setIsSyncingSlack] = useState(false);
  const [slackResult, setSlackResult] = useState<string | null>(null);

  // WhatsApp Baileys State
  const [waStatus, setWaStatus] = useState<WhatsAppStatus | null>(null);
  const [waMessageText, setWaMessageText] = useState("");
  const [waSender, setWaSender] = useState("");
  const [waGroup, setWaGroup] = useState("");
  const [isSendingWa, setIsSendingWa] = useState(false);
  const [waResult, setWaResult] = useState<WhatsAppSimulateResult | null>(null);
  const [waHistory, setWaHistory] = useState<WhatsAppMessageItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);

  useEffect(() => {
    loadWhatsAppInfo();
  }, []);

  const loadWhatsAppInfo = async () => {
    try {
      const [status, history] = await Promise.allSettled([
        api.getWhatsAppStatus(),
        api.getWhatsAppHistory(undefined, 8),
      ]);
      if (status.status === "fulfilled") setWaStatus(status.value);
      if (history.status === "fulfilled") setWaHistory(history.value);
    } catch (err) {
      console.error("Failed to load WhatsApp info:", err);
    }
  };

  const handleSlackSync = async () => {
    if (!onSyncSlack) return;
    try {
      setIsSyncingSlack(true);
      setSlackResult(null);
      await onSyncSlack(slackChannel);
      setSlackResult(`Successfully synced messages from #${slackChannel}`);
    } catch (err: any) {
      alert(`Slack sync failed: ${err.message}`);
    } finally {
      setIsSyncingSlack(false);
    }
  };

  const handleSendWhatsApp = async (overrideText?: string) => {
    const textToSend = overrideText || waMessageText;
    if (!textToSend.trim()) return;

    try {
      setIsSendingWa(true);
      setWaResult(null);
      const res = await api.simulateWhatsAppMessage({
        text: textToSend.trim(),
        sender_name: waSender.trim() || "WhatsApp User",
        group_name: waGroup.trim() || "WhatsApp Group",
      });
      setWaResult(res);
      setWaMessageText("");
      await loadWhatsAppInfo();
      if (onRefreshData) {
        await onRefreshData();
      }
    } catch (err: any) {
      alert(`WhatsApp ingestion failed: ${err.message}`);
    } finally {
      setIsSendingWa(false);
    }
  };

  const presetTemplates: Array<{ label: string; text: string }> = [];

  const googleConn = connections.find((c) => c.provider === "google");

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text-main">
          Source Connections & Connectors
        </h1>
        <p className="text-sm text-text-muted mt-1">
          Connected enterprise ingestion tools for Google Meet, Slack, WhatsApp (Baileys), and Excalidraw. Secrets and tokens are securely isolated server-side.
        </p>
      </div>

      {/* 4 SOURCE CARDS */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        {/* Source 1: Google Meet */}
        <div className="p-5 rounded-xl bg-surface border border-border shadow-xs flex flex-col justify-between space-y-4">
          <div className="space-y-3.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-lg bg-primary-soft flex items-center justify-center font-bold text-primary border border-primary/20 text-xs">
                  GM
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-main">Google Meet</h3>
                  <span className="text-[11px] text-text-muted">Native transcription · Auto sync</span>
                </div>
              </div>
              <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border flex items-center gap-1 font-mono ${
                googleConn && googleConn.status === "active"
                  ? "bg-success/10 text-success border-success/20"
                  : "bg-amber-500/10 text-amber-600 border-amber-500/20"
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${googleConn?.status === "active" ? "bg-success" : "bg-warning"}`} />
                <span>{googleConn?.status === "active" ? "Connected" : "Not Linked"}</span>
              </span>
            </div>

            <div className="space-y-1.5 text-xs text-text-muted pt-2 border-t border-border">
              <div className="flex items-center justify-between">
                <span>Account:</span>
                <strong className="text-text-main truncate max-w-[120px] font-mono text-[10px]">{googleConn?.account_email || "Not Linked"}</strong>
              </div>
              <div className="flex items-center justify-between">
                <span>Automatic sync:</span>
                <span className="text-primary font-medium text-[11px]">
                  {subscriptionsActive ? "Active" : "Paused"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Last event:</span>
                <span className="font-mono text-[11px]" suppressHydrationWarning>
                  {lastMeetEventAt ? new Date(lastMeetEventAt).toLocaleString() : "No events yet"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Transcript processing:</span>
                <span className="font-mono text-[11px]">{pendingMeetEvents} pending</span>
              </div>
            </div>

            <div className="p-2 bg-canvas rounded border border-border text-[10px] font-mono text-text-muted truncate">
              {googleConn?.scopes?.join(", ") || "meetings.space.readonly"}
            </div>
          </div>

          <div className="pt-3 border-t border-border flex justify-end gap-2">
            {onReconcileMeet && (
              <button
                onClick={onReconcileMeet}
                className="px-2.5 py-1 text-xs font-medium text-text-main bg-surface hover:bg-canvas border border-border rounded flex items-center gap-1 transition-colors"
                title="Manual reconciliation: recovers missed or failed transcript events"
              >
                <RefreshCw className="w-3 h-3" />
                <span>Sync now</span>
              </button>
            )}
            <button
              onClick={onConnectGoogle}
              className="px-2.5 py-1 text-xs font-semibold text-primary bg-primary-soft hover:bg-primary/20 border border-primary/20 rounded flex items-center gap-1 transition-colors"
            >
              <RefreshCw className="w-3 h-3" />
              <span>{googleConn ? "Link Account" : "Connect Google"}</span>
            </button>
          </div>
        </div>

        {/* Source 2: Slack */}
        <div className="p-5 rounded-xl bg-surface border border-border shadow-xs flex flex-col justify-between space-y-4">
          <div className="space-y-3.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-lg bg-emerald-500/10 text-emerald-600 flex items-center justify-center font-bold border border-emerald-500/20 text-xs">
                  <MessageSquare className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-main">Slack</h3>
                  <span className="text-[11px] text-text-muted">Channels & Threads</span>
                </div>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-success/10 text-success border border-success/20 flex items-center gap-1 font-mono">
                <CheckCircle2 className="w-3 h-3" />
                <span>Active</span>
              </span>
            </div>

            <div className="space-y-1.5 text-xs text-text-muted pt-2 border-t border-border">
              <div className="flex items-center justify-between">
                <span>Security:</span>
                <strong className="text-text-main font-mono text-[10px]">HMAC-SHA256</strong>
              </div>
              <div className="flex items-center justify-between">
                <span>Ingestion:</span>
                <span className="text-emerald-600 font-medium text-[11px]">Real-time Webhook</span>
              </div>
            </div>

            <div className="flex items-center gap-1.5">
              <input
                type="text"
                value={slackChannel}
                onChange={(e) => setSlackChannel(e.target.value)}
                placeholder="Channel (e.g. general)"
                className="px-2 py-1 text-[11px] bg-canvas border border-border rounded text-text-main flex-1 focus:outline-none focus:border-emerald-500 font-mono"
              />
              <button
                onClick={handleSlackSync}
                disabled={isSyncingSlack}
                className="px-2 py-1 text-[11px] font-semibold text-emerald-600 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 rounded flex items-center gap-1 transition-colors shrink-0"
              >
                <RefreshCw className={`w-3 h-3 ${isSyncingSlack ? "animate-spin" : ""}`} />
                <span>Sync</span>
              </button>
            </div>
          </div>

          <div className="pt-3 border-t border-border flex justify-between items-center text-[10px] text-text-muted">
            <span>Channels: #general, #architecture</span>
            {slackResult && <span className="text-emerald-600 font-medium truncate max-w-[120px]">✓ Synced</span>}
          </div>
        </div>

        {/* Source 3: WhatsApp Baileys (NEW) */}
        <div className="p-5 rounded-xl bg-surface border border-emerald-500/30 shadow-xs flex flex-col justify-between space-y-4 relative overflow-hidden">
          <div className="absolute -top-6 -right-6 w-20 h-20 bg-emerald-500/10 rounded-full blur-xl pointer-events-none" />

          <div className="space-y-3.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-lg bg-emerald-500 text-white flex items-center justify-center font-bold shadow-xs">
                  <MessageCircle className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-main flex items-center gap-1.5">
                    <span>WhatsApp</span>
                    <span className="px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-600 text-[9px] font-mono font-bold">
                      Baileys
                    </span>
                  </h3>
                  <span className="text-[11px] text-text-muted">Group Chat Multi-Project</span>
                </div>
              </div>
              <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border flex items-center gap-1 font-mono ${
                waStatus && waStatus.details?.session_status === "connected"
                  ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
                  : "bg-canvas text-text-muted border-border"
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${waStatus && waStatus.details?.session_status === "connected" ? "bg-emerald-500 animate-pulse" : "bg-text-muted"}`} />
                <span>{waStatus ? waStatus.details?.session_status || waStatus.status : "Not connected"}</span>
              </span>
            </div>

            <div className="space-y-1.5 text-xs text-text-muted pt-2 border-t border-border">
              <div className="flex items-center justify-between">
                <span>Protocol:</span>
                <strong className="text-text-main text-[11px]">Baileys WebSocket</strong>
              </div>
              <div className="flex items-center justify-between">
                <span>Active Groups:</span>
                <strong className="text-text-main font-mono text-[11px]">
                  {waStatus?.details?.active_groups_count ?? "—"}
                </strong>
              </div>
              <div className="flex items-center justify-between">
                <span>Latency:</span>
                <strong className="text-text-main font-mono text-[11px]">
                  {waStatus ? `${waStatus.latency_ms} ms` : "—"}
                </strong>
              </div>
            </div>

            <div className="p-2 bg-canvas rounded border border-border text-[10px] text-text-muted flex items-center justify-between">
              <span className="font-mono">WhatsApp group messages</span>
              <span className="font-semibold text-text-main">Evidence intake</span>
            </div>
          </div>

          <div className="pt-3 border-t border-border flex justify-end">
            <span className="text-[10px] text-text-muted font-mono flex items-center gap-1">
              <Shield className={`w-3 h-3 ${waStatus && waStatus.details?.session_status === "connected" ? "text-emerald-600" : "text-text-muted"}`} />
              <span>{waStatus ? `Session: ${waStatus.details?.session_status || waStatus.status}` : "No session"}</span>
            </span>
          </div>
        </div>

        {/* Source 4: Excalidraw */}
        <div className="p-5 rounded-xl bg-surface border border-border shadow-xs flex flex-col justify-between space-y-4">
          <div className="space-y-3.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-lg bg-purple-500/10 text-purple-600 flex items-center justify-center font-bold border border-purple-500/20 text-xs">
                  <PenTool className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-main">Excalidraw</h3>
                  <span className="text-[11px] text-text-muted">Living Whiteboard Canvas</span>
                </div>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-success/10 text-success border border-success/20 flex items-center gap-1 font-mono">
                <CheckCircle2 className="w-3 h-3" />
                <span>Active</span>
              </span>
            </div>

            <div className="space-y-1.5 text-xs text-text-muted pt-2 border-t border-border">
              <div className="flex items-center justify-between">
                <span>Role A (Input):</span>
                <strong className="text-text-main text-[11px]">Visual Architecture Evidence</strong>
              </div>
              <div className="flex items-center justify-between">
                <span>Role B (Output):</span>
                <strong className="text-text-main text-[11px]">Gated Proposals & Diff</strong>
              </div>
            </div>

            <div className="p-2 bg-canvas rounded border border-border text-[10px] font-mono text-text-muted truncate">
              application/vnd.excalidraw+json
            </div>
          </div>

          <div className="pt-3 border-t border-border flex justify-end">
            {onNavigateToArchitecture && (
              <button
                onClick={onNavigateToArchitecture}
                className="px-2.5 py-1 text-xs font-semibold text-purple-600 bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 rounded flex items-center gap-1 transition-colors"
              >
                <span>Open Canvas</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* WHATSAPP BAILEYS GROUP CHAT & LIVING WHITEBOARD SIMULATOR */}
      <div className="p-6 rounded-2xl bg-surface border border-emerald-500/30 shadow-sm space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-border/80">
          <div>
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-emerald-500 text-white flex items-center justify-center font-bold text-xs">
                <MessageCircle className="w-4 h-4" />
              </div>
              <h2 className="text-base font-bold text-text-main">
                WhatsApp Group Chat Ingestion & Living Whiteboard Sync
              </h2>
            </div>
            <p className="text-xs text-text-muted mt-1">
              Connect a WhatsApp group via <strong>Baileys</strong>. Group messages are ingested as immutable evidence and matched to the project under discussion.
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span className="px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-600 border border-emerald-500/20 text-xs font-semibold flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>Baileys Bridge Online</span>
            </span>
          </div>
        </div>

        {/* Message templates are user-defined. No preset discussions ship with the product. */}
        {presetTemplates.length > 0 && (
        <div className="space-y-2">
          <span className="text-[11px] font-bold uppercase tracking-wider text-text-muted flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-emerald-600" />
            <span>Saved message templates:</span>
          </span>
          <div className="flex flex-wrap gap-2">
            {presetTemplates.map((preset, idx) => (
              <button
                key={idx}
                onClick={() => {
                  setWaMessageText(preset.text);
                  handleSendWhatsApp(preset.text);
                }}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-canvas hover:bg-emerald-500/10 hover:text-emerald-700 border border-border hover:border-emerald-500/30 text-text-main transition-colors text-left flex items-center gap-1.5"
              >
                <Sparkles className="w-3 h-3 text-emerald-600 shrink-0" />
                <span>{preset.label}</span>
              </button>
            ))}
          </div>
        </div>
        )}

        {/* Input Box & Sender Controls */}
        <div className="space-y-3 p-4 rounded-xl bg-canvas border border-border/80">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div>
              <label className="text-[10px] font-bold uppercase text-text-muted block mb-1">
                Sender (PushName / Participant)
              </label>
              <input
                type="text"
                value={waSender}
                onChange={(e) => setWaSender(e.target.value)}
                className="w-full px-3 py-1.5 text-xs bg-surface border border-border rounded-lg text-text-main focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase text-text-muted block mb-1">
                WhatsApp Group Name
              </label>
              <input
                type="text"
                value={waGroup}
                onChange={(e) => setWaGroup(e.target.value)}
                className="w-full px-3 py-1.5 text-xs bg-surface border border-border rounded-lg text-text-main focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div>
            <label className="text-[10px] font-bold uppercase text-text-muted block mb-1">
              WhatsApp Group Message
            </label>
            <textarea
              rows={3}
              value={waMessageText}
              onChange={(e) => setWaMessageText(e.target.value)}
              placeholder="Paste the WhatsApp group message to ingest..."
              className="w-full px-3 py-2 text-xs bg-surface border border-border rounded-lg text-text-main focus:outline-none focus:border-emerald-500 font-sans"
            />
          </div>

          <div className="flex justify-end items-center gap-3 pt-1">
            <button
              onClick={() => handleSendWhatsApp()}
              disabled={isSendingWa || !waMessageText.trim()}
              className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-2 shadow-xs transition-colors disabled:opacity-50"
            >
              <Send className={`w-3.5 h-3.5 ${isSendingWa ? "animate-pulse" : ""}`} />
              <span>{isSendingWa ? "Analyzing & Updating Canvas..." : "Send WhatsApp Message"}</span>
            </button>
          </div>
        </div>

        {/* Live Result Callout */}
        {waResult && (waResult.status === "ignored" || !waResult.processed) && (
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 space-y-2.5 animate-in fade-in duration-200">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-amber-900 flex items-center gap-1.5">
                <Shield className="w-4 h-4 text-amber-600" />
                <span>Message Ignored — Living Whiteboards Left Untouched</span>
              </span>
              <span className="text-[10px] font-mono text-amber-800 bg-amber-500/20 px-2 py-0.5 rounded font-bold">
                Status: Leave It (Ignored)
              </span>
            </div>
            <p className="text-xs text-amber-900 font-medium">
              {waResult.reason || waResult.message}
            </p>
            <p className="text-[11px] text-text-muted">
              Synora identified that this conversation is either casual banter (greetings, lunch, coffee) or is not about any created project in your workspace. The agent left all Excalidraw whiteboards unchanged to prevent diagram pollution.
            </p>
          </div>
        )}

        {waResult && waResult.processed && waResult.matched_project && (
          <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 space-y-3 animate-in fade-in duration-200">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-emerald-800 flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                <span>Autonomous Multi-Project Context Resolution & Whiteboard Update</span>
              </span>
              <span className="text-[10px] font-mono text-emerald-700 bg-emerald-500/20 px-2 py-0.5 rounded font-bold">
                {Math.round((waResult.confidence || 0.95) * 100)}% Confidence
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
              {/* Target Project */}
              <div className="p-3 rounded-lg bg-surface border border-emerald-500/20 space-y-1">
                <span className="text-[10px] font-bold uppercase text-text-muted">Target Project Identified</span>
                <p className="font-bold text-text-main truncate text-sm text-emerald-700">
                  {waResult.matched_project.name}
                </p>
                <span className="text-[10px] font-mono text-text-muted block">
                  id: {waResult.matched_project.id}
                </span>
                <p className="text-[11px] text-text-muted mt-1 leading-snug">
                  Reason: {waResult.reasoning}
                </p>
              </div>

              {/* Architectural Decision Extracted */}
              <div className="p-3 rounded-lg bg-surface border border-emerald-500/20 space-y-1">
                <span className="text-[10px] font-bold uppercase text-text-muted">Extracted Architectural Intent</span>
                <p className="font-semibold text-text-main text-xs line-clamp-2">
                  {waResult.extracted_title || "Architectural decision captured"}
                </p>
                <div className="flex items-center gap-1.5 pt-1">
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-soft border border-border text-text-muted">
                    {waResult.extracted_category || "decision_candidate"}
                  </span>
                  <span className="text-[10px] font-mono text-text-muted">
                    ev: {waResult.evidence_id}
                  </span>
                </div>
              </div>

              {/* Whiteboard Changes */}
              <div className="p-3 rounded-lg bg-surface border border-emerald-500/20 space-y-1 flex flex-col justify-between">
                <div>
                  <span className="text-[10px] font-bold uppercase text-text-muted">Living Whiteboard Changes</span>
                  <p className="font-bold text-text-main text-xs text-purple-700">
                    Updated Excalidraw Canvas to v{waResult.artifact_version}
                  </p>
                  {waResult.nodes_added && waResult.nodes_added.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {waResult.nodes_added.map((node) => (
                        <span key={node} className="px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-700 text-[10px] font-semibold border border-purple-500/20">
                          + {node}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {onNavigateToArchitecture && (
                  <button
                    onClick={onNavigateToArchitecture}
                    className="w-full mt-2 py-1.5 px-3 rounded bg-purple-600 hover:bg-purple-700 text-white text-[11px] font-semibold flex items-center justify-center gap-1.5 transition-colors shadow-xs"
                  >
                    <span>View on Architecture Whiteboard</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Ingested WhatsApp message history (real records only) */}
        {waHistory.length > 0 && (
          <div className="space-y-3 pt-2">
            <div className="flex items-center justify-between text-xs text-text-muted">
              <span className="font-bold uppercase tracking-wider text-[10px]">
                Ingested WhatsApp Group Messages ({waHistory.length})
              </span>
              <button
                onClick={loadWhatsAppInfo}
                className="text-[11px] text-emerald-600 hover:underline flex items-center gap-1"
              >
                <RefreshCw className="w-3 h-3" />
                <span>Refresh</span>
              </button>
            </div>

            <div className="divide-y divide-border rounded-xl border border-border bg-surface overflow-hidden text-xs">
              {waHistory.map((item) => (
                <div key={item.id} className="p-3 flex items-start justify-between gap-4 hover:bg-canvas transition-colors">
                  <div className="space-y-1 flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-text-main text-xs">
                        {item.group_name || "WhatsApp Group"}
                      </span>
                      <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-700 border border-emerald-500/20 font-semibold">
                        Project: {item.project_id}
                      </span>
                      {item.confidence && (
                        <span className="text-[10px] font-mono text-text-muted">
                          {(item.confidence * 100).toFixed(0)}% match
                        </span>
                      )}
                    </div>
                    <p className="text-text-muted text-xs line-clamp-2">
                      {item.content}
                    </p>
                    {item.reasoning && (
                      <span className="text-[10px] text-text-muted font-mono block">
                        Reason: {item.reasoning}
                      </span>
                    )}
                  </div>

                  <span className="text-[10px] text-text-muted font-mono shrink-0">
                    {item.created_at ? new Date(item.created_at).toLocaleTimeString() : "Just now"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
