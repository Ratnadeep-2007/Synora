"use client";

import React, { useEffect, useState } from "react";
import { BrainCircuit, Copy, Database, KeyRound, Save, ShieldCheck } from "lucide-react";
import { getFrontendUserId, setFrontendUserId } from "@/lib/api";

export type SettingsSection =
  | "Workspace"
  | "Members"
  | "Permissions"
  | "Security"
  | "Notifications"
  | "Audit";

interface SettingsViewProps {
  isAdmin?: boolean;
  workspaceName?: string;
  onSaveWorkspace?: (name: string) => Promise<void> | void;
}

export function SettingsView({ workspaceName = "Workspace", onSaveWorkspace }: SettingsViewProps) {
  const [name, setName] = useState(workspaceName);
  const [saved, setSaved] = useState(false);
  const [sessionId, setSessionId] = useState("");
  const [restoreId, setRestoreId] = useState("");
  const [restoreMsg, setRestoreMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => setName(workspaceName), [workspaceName]);
  useEffect(() => setSessionId(getFrontendUserId()), []);

  const copySessionId = async () => {
    try {
      await navigator.clipboard.writeText(sessionId);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = sessionId;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const handleRestore = (event: React.FormEvent) => {
    event.preventDefault();
    if (!setFrontendUserId(restoreId)) {
      setRestoreMsg("Paste a valid session ID first.");
      return;
    }
    setRestoreMsg("Identity restored — reloading with your meetings…");
    setTimeout(() => window.location.reload(), 700);
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    await onSaveWorkspace?.(name.trim() || "Workspace");
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
  };

  return (
    <div className="space-y-6 view-enter">
      <header className="space-y-2">
        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-border bg-surface px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          <ShieldCheck className="h-3.5 w-3.5 text-primary" />
          Workspace settings
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-text-main">Settings</h1>
        <p className="max-w-2xl text-sm text-text-muted">
          Keep configuration simple. Synora handles routine intelligence automatically.
        </p>
      </header>

      <section className="rounded-2xl border border-border bg-surface p-5 shadow-xs">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-soft text-primary">
            <Database className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-main">Workspace identity</h2>
            <p className="mt-0.5 text-[11px] text-text-muted">This name appears in the project selector.</p>
          </div>
        </div>

        <form onSubmit={handleSave} className="mt-5 max-w-lg">
          <label htmlFor="workspace-name" className="text-xs font-semibold text-text-main">Workspace name</label>
          <div className="mt-2 flex gap-2">
            <input
              id="workspace-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="flex-1 rounded-lg border border-border bg-canvas px-3 py-2.5 text-xs text-text-main outline-none focus:border-primary"
            />
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2.5 text-xs font-semibold text-white hover:bg-primary-hover"
            >
              <Save className="h-3.5 w-3.5" />
              {saved ? "Saved" : "Save"}
            </button>
          </div>
        </form>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-border bg-surface p-5 shadow-xs">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold text-text-main">Session identity</h2>
          </div>
          <p className="mt-3 text-xs leading-5 text-text-muted">
            Meetings and projects are scoped to this browser identity. On a second
            browser or device, paste the ID from your first browser below to see
            the same workspace.
          </p>
          <div className="mt-3 flex gap-2">
            <input
              value={sessionId}
              readOnly
              aria-label="Current session ID"
              className="flex-1 rounded-lg border border-border bg-canvas px-3 py-2 text-[11px] font-mono text-text-main outline-none"
            />
            <button
              type="button"
              onClick={copySessionId}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-canvas px-3 py-2 text-xs font-semibold text-text-main hover:border-primary/40"
            >
              <Copy className="h-3.5 w-3.5" />
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <form onSubmit={handleRestore} className="mt-2 flex gap-2">
            <input
              value={restoreId}
              onChange={(event) => {
                setRestoreId(event.target.value);
                setRestoreMsg(null);
              }}
              placeholder="Paste a session ID from another browser…"
              aria-label="Restore session ID"
              className="flex-1 rounded-lg border border-border bg-canvas px-3 py-2 text-[11px] font-mono text-text-main outline-none focus:border-primary placeholder:text-text-dim"
            />
            <button
              type="submit"
              className="rounded-lg bg-primary px-3.5 py-2 text-xs font-semibold text-white hover:bg-primary-hover"
            >
              Restore
            </button>
          </form>
          {restoreMsg && <p className="mt-2 text-[11px] text-text-muted">{restoreMsg}</p>}
        </div>

        <div className="rounded-2xl border border-border bg-surface p-5 shadow-xs">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold text-text-main">Operating model</h2>
          </div>
          <p className="mt-3 text-xs leading-5 text-text-muted">
            AI handles ingestion, understanding, routing, knowledge extraction, state synchronization, and architecture updates.
          </p>
          <div className="mt-3 rounded-xl border border-primary/15 bg-primary-soft/40 p-3 text-[11px] font-semibold text-primary">
            Human action: resolve ambiguous or unknown context only.
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-surface p-5 shadow-xs">
          <div className="text-sm font-semibold text-text-main">Storage</div>
          <p className="mt-3 text-xs leading-5 text-text-muted">
            Project state, evidence, and Excalidraw scenes are stored in the database. No automatic local diagram files are created.
          </p>
        </div>
      </section>
    </div>
  );
}