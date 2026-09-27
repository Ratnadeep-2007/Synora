"use client";

import React, { useState } from "react";

const SECTIONS = [
  "Workspace",
  "Members",
  "Permissions",
  "Sources",
  "Security",
  "Data & Retention",
  "AI Governance",
  "Notifications",
  "Audit",
] as const;

type SettingsSection = (typeof SECTIONS)[number];

interface SettingsViewProps {
  isAdmin?: boolean;
  workspaceName?: string;
  onSaveWorkspace?: (name: string) => Promise<void> | void;
}

export function SettingsView({ isAdmin = true, workspaceName = "Workspace", onSaveWorkspace }: SettingsViewProps) {
  const [section, setSection] = useState<SettingsSection>("Workspace");
  const [name, setName] = useState(workspaceName);
  const [saved, setSaved] = useState(false);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSaveWorkspace?.(name);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text-main">Settings</h1>
        <p className="text-sm text-text-muted mt-1">
          Workspace configuration and enterprise administration.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-6">
        {/* Section nav */}
        <nav className="rounded-xl bg-surface border border-border shadow-xs p-2 h-fit" aria-label="Settings sections">
          {SECTIONS.map((s) => {
            const adminOnly = ["Members", "Permissions", "Security", "Audit"].includes(s);
            if (adminOnly && !isAdmin) return null;
            const isActive = section === s;
            return (
              <button
                key={s}
                onClick={() => setSection(s)}
                aria-current={isActive ? "page" : undefined}
                className={`w-full text-left px-3 py-2 rounded-md text-xs font-medium transition-colors ${
                  isActive ? "bg-primary-soft text-primary font-semibold" : "text-text-muted hover:text-text-main hover:bg-canvas"
                }`}
              >
                {s}
                {adminOnly && <span className="ml-1.5 text-[10px] font-mono text-text-muted">admin</span>}
              </button>
            );
          })}
        </nav>

        {/* Section panel */}
        <div className="rounded-xl bg-surface border border-border shadow-xs p-6 space-y-4">
          <h2 className="text-sm font-semibold text-text-main uppercase tracking-wider">{section}</h2>

          {section === "Workspace" && (
            <form onSubmit={handleSave} className="space-y-4 max-w-md">
              <div className="space-y-1.5">
                <label htmlFor="workspace-name" className="text-xs font-semibold text-text-main">
                  Workspace name
                </label>
                <input
                  id="workspace-name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-md bg-canvas border border-border focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary text-text-main"
                />
                <p className="text-[11px] text-text-muted">Shown in the project selector and audit records.</p>
              </div>
              <button
                type="submit"
                className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-md transition-colors"
              >
                {saved ? "Saved" : "Save workspace"}
              </button>
            </form>
          )}

          {section === "Members" && (
            <div className="text-xs text-text-muted space-y-2">
              <p>Users, memberships, and roles are managed here.</p>
              <div className="rounded-md border border-border divide-y divide-border/60">
                {["Owner", "Admin", "Member", "Viewer", "Agent"].map((role) => (
                  <div key={role} className="px-3 py-2 flex items-center justify-between">
                    <span className="font-medium text-text-main">{role}</span>
                    <span className="font-mono text-[11px]">—</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {section === "Permissions" && (
            <div className="text-xs text-text-muted space-y-2">
              <p>Permission policies gate high-impact actions such as approving state changes.</p>
              <p>If you lack a permission, contact your workspace administrator. Inaccessible resources are never disclosed.</p>
            </div>
          )}

          {section === "Sources" && (
            <div className="text-xs text-text-muted">
              <p>Manage source connections, retention windows, and per-source permissions from the Sources screen.</p>
            </div>
          )}

          {section === "Security" && (
            <div className="text-xs text-text-muted space-y-2">
              <p>OAuth secrets and refresh tokens are stored server-side and never exposed to the browser.</p>
              <p>Request only the minimum OAuth scopes required for each connector.</p>
            </div>
          )}

          {section === "Data & Retention" && (
            <div className="text-xs text-text-muted">
              <p>Configure evidence retention and archival policies. Rollbacks create new versions — history is never deleted.</p>
            </div>
          )}

          {section === "AI Governance" && (
            <div className="text-xs text-text-muted space-y-2">
              <p>Low-impact categorizations may be automated with audit logging. High-impact architecture, scope, and decision changes require explicit human confirmation.</p>
            </div>
          )}

          {section === "Notifications" && (
            <div className="text-xs text-text-muted">
              <p>Operational notifications only: conflicts requiring review, transcript readiness, sync failures, expired authorizations, and approval requests.</p>
            </div>
          )}

          {section === "Audit" && (
            <div className="text-xs text-text-muted">
              <p>Security-sensitive and state-changing actions are recorded with actor, timestamp, evidence, and resulting version.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
