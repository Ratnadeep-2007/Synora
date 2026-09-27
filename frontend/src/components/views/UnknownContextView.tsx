"use client";

import React, { useEffect, useState } from "react";
import { Inbox, Check, AlertTriangle, Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import { Project, UnknownContextItem } from "@/lib/types";
import { EmptyState } from "@/components/common/EmptyState";
import { StatusBadge } from "@/components/common/StatusBadge";

interface UnknownContextViewProps {
  projects: Project[];
  onChanged?: () => Promise<void> | void;
}

const SOURCE_LABEL: Record<string, string> = {
  whatsapp: "WhatsApp",
  google_meet: "Google Meet",
  excalidraw: "Excalidraw",
};

export function UnknownContextView({ projects, onChanged }: UnknownContextViewProps) {
  const [items, setItems] = useState<UnknownContextItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [creatingFor, setCreatingFor] = useState<string | null>(null);
  const [newProjectName, setNewProjectName] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.listUnknownContext(statusFilter || undefined);
      setItems(data);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const loadSuggestions = async (itemId: string) => {
    try {
      const withMatches = await api.getUnknownSuggestions(itemId);
      setItems((prev) => prev.map((i) => (i.id === itemId ? withMatches : i)));
      return withMatches;
    } catch {
      return null;
    }
  };

  const selectItem = async (item: UnknownContextItem) => {
    setSelectedId(item.id);
    if (!item.matches || item.matches.length === 0) {
      await loadSuggestions(item.id);
    }
  };

  const handleAssign = async (itemId: string, projectId: string) => {
    setBusy(true);
    try {
      await api.assignUnknownItem(itemId, projectId);
      await load();
      setSelectedId(null);
      await onChanged?.();
    } catch (err: any) {
      alert(`Assignment failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleKeep = async (itemId: string) => {
    setBusy(true);
    try {
      await api.keepUnknownItem(itemId);
      await load();
      setSelectedId(null);
    } finally {
      setBusy(false);
    }
  };

  const handleDismiss = async (itemId: string) => {
    setBusy(true);
    try {
      await api.dismissUnknownItem(itemId);
      await load();
      setSelectedId(null);
    } finally {
      setBusy(false);
    }
  };

  const handleCreateProject = async (itemId: string) => {
    if (!newProjectName.trim()) return;
    setBusy(true);
    try {
      await api.createProjectFromUnknown(itemId, newProjectName.trim());
      setCreatingFor(null);
      setNewProjectName("");
      await load();
      setSelectedId(null);
      await onChanged?.();
    } catch (err: any) {
      alert(`Project creation failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  const selected = items.find((i) => i.id === selectedId) || null;
  const pendingCount = items.filter((i) => i.status === "pending").length;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-wider font-semibold text-primary">Unknown Context</p>
          <h1 className="text-xl font-semibold tracking-tight text-text-main mt-1">Needs classification</h1>
          <p className="text-xs text-text-muted mt-1 max-w-2xl">
            Source content that could not be confidently mapped to a project. Nothing is guessed and nothing is
            discarded: review each item and decide where it belongs.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted font-mono">{pendingCount} pending</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            aria-label="Filter items by status"
            className="px-2.5 py-1.5 text-xs rounded-md bg-surface border border-border text-text-main"
          >
            <option value="pending">Pending</option>
            <option value="assigned">Assigned</option>
            <option value="kept">Kept</option>
            <option value="dismissed">Dismissed</option>
            <option value="">All</option>
          </select>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[0.9fr_1.1fr] gap-4">
        {/* Triage list */}
        <section className="rounded-xl bg-surface border border-border overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Items ({items.length})
            </span>
          </div>
          {loading ? (
            <div className="p-8 text-center text-xs text-text-muted">Loading…</div>
          ) : items.length === 0 ? (
            <div className="p-8">
              <EmptyState
                icon="success"
                title="Nothing to classify"
                description="Every source event has been confidently mapped to a project."
              />
            </div>
          ) : (
            <div className="divide-y divide-border max-h-[620px] overflow-y-auto">
              {items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => selectItem(item)}
                  className={`w-full text-left px-4 py-3 hover:bg-canvas transition-colors ${
                    item.id === selectedId ? "bg-primary-soft/50" : ""
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-mono font-semibold uppercase px-1.5 py-0.5 rounded bg-canvas text-primary border border-border">
                      {SOURCE_LABEL[item.source] || item.source}
                    </span>
                    <StatusBadge
                      kind={item.status === "pending" ? "review" : item.status === "assigned" ? "success" : "neutral"}
                      label={item.status}
                    />
                  </div>
                  <p className="text-xs text-text-main leading-relaxed line-clamp-2">{item.content || "(no text)"}</p>
                  <div className="flex items-center gap-2 text-[11px] text-text-muted mt-1">
                    <span>{item.actor_id || "Unknown sender"}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Detail + possible matches */}
        <section className="rounded-xl bg-surface border border-border p-5 space-y-4 h-fit lg:sticky lg:top-20">
          {!selected ? (
            <div className="py-10 text-center text-xs text-text-muted">
              <Inbox className="w-6 h-6 mx-auto mb-2 opacity-40" />
              Select an item to review its context and possible matches.
            </div>
          ) : (
            <>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <span className="text-[11px] uppercase tracking-wider font-semibold text-text-muted">
                    {SOURCE_LABEL[selected.source] || selected.source} · original evidence
                  </span>
                  <p className="text-sm text-text-main mt-1 leading-relaxed">{selected.content}</p>
                </div>
                <span className="text-[10px] font-mono text-text-muted shrink-0">{selected.id}</span>
              </div>

              <div className="p-3 rounded-lg bg-canvas border border-border text-[11px] text-text-muted space-y-1">
                <div>Sender: <strong className="text-text-main">{selected.actor_id || "unknown"}</strong></div>
                <div>Source event: <span className="font-mono">{selected.source_event_id || "—"}</span></div>
                {selected.evidence_id && (
                  <div>Evidence: <span className="font-mono">{selected.evidence_id}</span></div>
                )}
              </div>

              <div className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">Possible matches</h3>
                {selected.matches.length === 0 ? (
                  <p className="text-xs text-text-muted">
                    No explainable project match found. Keep it unknown or create a new project.
                  </p>
                ) : (
                  selected.matches.map((m) => (
                    <div key={m.id} className="p-3 rounded-lg border border-border bg-canvas/60 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-text-main">
                          {m.candidate_project_name || m.candidate_project_id}
                        </span>
                        <button
                          disabled={busy}
                          onClick={() => handleAssign(selected.id, m.candidate_project_id)}
                          className="px-3 py-1 rounded-md bg-primary text-white text-xs font-semibold disabled:opacity-50"
                        >
                          Assign
                        </button>
                      </div>
                      {m.similarity_reason.length > 0 && (
                        <div className="space-y-1">
                          <span className="text-[11px] font-semibold text-text-muted">Why:</span>
                          <ul className="space-y-0.5">
                            {m.similarity_reason.map((reason, idx) => (
                              <li key={idx} className="flex items-start gap-1.5 text-xs text-text-main">
                                <Check className="w-3.5 h-3.5 text-success shrink-0 mt-0.5" />
                                <span>{reason}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {m.conflicts.length > 0 && (
                        <div className="flex items-start gap-1.5 text-[11px] text-warning">
                          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                          <span>{m.conflicts.join("; ")}</span>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-border">
                <button
                  disabled={busy}
                  onClick={() => handleKeep(selected.id)}
                  className="px-3 py-1.5 rounded-md border border-border text-xs font-semibold text-text-main hover:bg-canvas disabled:opacity-50"
                >
                  Keep Unknown
                </button>
                <button
                  disabled={busy}
                  onClick={() => setCreatingFor(creatingFor === selected.id ? null : selected.id)}
                  className="px-3 py-1.5 rounded-md border border-border text-xs font-semibold text-text-main hover:bg-canvas inline-flex items-center gap-1.5 disabled:opacity-50"
                >
                  <Plus className="w-3.5 h-3.5" /> Create Project
                </button>
                <button
                  disabled={busy}
                  onClick={() => handleDismiss(selected.id)}
                  className="px-3 py-1.5 rounded-md text-xs font-medium text-text-muted hover:text-text-main inline-flex items-center gap-1.5 disabled:opacity-50"
                >
                  <X className="w-3.5 h-3.5" /> Dismiss
                </button>
              </div>

              {creatingFor === selected.id && (
                <div className="p-3 rounded-lg border border-primary/30 bg-primary-soft/40 space-y-2">
                  <label className="text-[11px] font-semibold text-text-main" htmlFor="unknown-new-project">
                    New project name
                  </label>
                  <input
                    id="unknown-new-project"
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    placeholder="e.g. Claims Platform"
                    className="w-full px-3 py-2 text-xs rounded-md bg-surface border border-border text-text-main"
                  />
                  <button
                    disabled={busy || !newProjectName.trim()}
                    onClick={() => handleCreateProject(selected.id)}
                    className="px-3 py-1.5 rounded-md bg-primary text-white text-xs font-semibold disabled:opacity-50"
                  >
                    Create and assign
                  </button>
                </div>
              )}

              {projects.length > 0 && (
                <div className="space-y-1.5 pt-1">
                  <label className="text-[11px] font-semibold text-text-muted" htmlFor="unknown-assign-existing">
                    Or assign to an existing project
                  </label>
                  <select
                    id="unknown-assign-existing"
                    disabled={busy}
                    defaultValue=""
                    onChange={(e) => {
                      if (e.target.value) handleAssign(selected.id, e.target.value);
                    }}
                    className="w-full px-3 py-2 text-xs rounded-md bg-canvas border border-border text-text-main"
                  >
                    <option value="">Select a project…</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
