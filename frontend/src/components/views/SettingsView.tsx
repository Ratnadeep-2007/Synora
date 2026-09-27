"use client";

import React, { useState } from "react";

export type SettingsSection =
  | "Workspace"
  | "Members"
  | "Permissions"
  | "Security"
  | "Notifications"
  | "Audit";

interface SettingItem {
  id: SettingsSection;
  label: string;
  adminOnly?: boolean;
}

interface SettingGroup {
  category: string;
  items: SettingItem[];
}

const SETTING_GROUPS: SettingGroup[] = [
  {
    category: "Workspace",
    items: [
      { id: "Workspace", label: "Workspace name", adminOnly: false },
    ],
  },
  {
    category: "Access",
    items: [
      { id: "Members", label: "Members", adminOnly: true },
      { id: "Permissions", label: "Permissions", adminOnly: true },
    ],
  },
  {
    category: "System",
    items: [
      { id: "Security", label: "Security", adminOnly: true },
      { id: "Notifications", label: "Notifications", adminOnly: false },
      { id: "Audit", label: "Audit", adminOnly: true },
    ],
  },
];

interface SettingsViewProps {
  isAdmin?: boolean;
  workspaceName?: string;
  onSaveWorkspace?: (name: string) => Promise<void> | void;
}

export function SettingsView({
  isAdmin = true,
  workspaceName = "Workspace",
  onSaveWorkspace,
}: SettingsViewProps) {
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
        <nav className="rounded-xl bg-surface border border-border shadow-xs p-3 h-fit space-y-4" aria-label="Settings sections">
          {SETTING_GROUPS.map((group) => {
            const visibleItems = group.items.filter((item) => !item.adminOnly || isAdmin);
            if (visibleItems.length === 0) return null;

            return (
              <div key={group.category} className="space-y-1">
                <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                  {group.category}
                </div>
                {visibleItems.map((item) => {
                  const isActive = section === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => setSection(item.id)}
                      aria-current={isActive ? "page" : undefined}
                      className={`w-full text-left px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center justify-between ${
                        isActive
                          ? "bg-primary-soft text-primary font-semibold"
                          : "text-text-muted hover:text-text-main hover:bg-canvas"
                      }`}
                    >
                      <span>{item.label}</span>
                      {item.adminOnly && (
                        <span className="text-[9px] font-mono text-text-muted">admin</span>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </nav>

        {/* Section panel */}
        <div className="rounded-xl bg-surface border border-border shadow-xs p-6 space-y-4">
          <h2 className="text-sm font-semibold text-text-main uppercase tracking-wider">
            {section === "Workspace" ? "Workspace Configuration" : section}
          </h2>

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
            <div className="text-xs text-text-muted space-y-3">
              <p>Team members and human access roles for this workspace.</p>
              <div className="rounded-md border border-border divide-y divide-border/60">
                {["Owner", "Admin", "Member", "Viewer"].map((role) => (
                  <div key={role} className="px-3 py-2.5 flex items-center justify-between">
                    <span className="font-medium text-text-main">{role}</span>
                    <span className="font-mono text-[11px] text-text-muted">—</span>
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

          {section === "Security" && (
            <div className="text-xs text-text-muted space-y-2">
              <p>OAuth secrets and refresh tokens are stored server-side and never exposed to the browser.</p>
              <p>Source integrations request only the minimum required scopes.</p>
            </div>
          )}

          {section === "Notifications" && (
            <div className="text-xs text-text-muted space-y-2">
              <p>Operational notifications: conflicts requiring review, sync readiness, and approval requests.</p>
            </div>
          )}

          {section === "Audit" && (
            <div className="text-xs text-text-muted space-y-2">
              <p>Security-sensitive and state-changing actions are recorded with actor, timestamp, evidence, and resulting version.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
