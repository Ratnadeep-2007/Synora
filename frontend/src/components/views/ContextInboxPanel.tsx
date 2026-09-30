"use client";

import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Check, CircleX, Inbox, Loader2, Plus, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Project, UnknownContextItem } from "@/lib/types";

interface ContextInboxPanelProps {
  projects: Project[];
  pendingCount: number;
  onChanged?: () => Promise<void> | void;
}

const SOURCE_LABEL: Record<string, string> = {
  whatsapp: "WhatsApp",
  google_meet: "Google Meet",
  excalidraw: "Excalidraw",
};

export function ContextInboxPanel({ projects, pendingCount, onChanged }: ContextInboxPanelProps) {
  const [items, setItems] = useState<UnknownContextItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.listUnknownContext("pending", 8);
      setItems(data);
      if (selectedId && !data.some((item) => item.id === selectedId)) {
        setSelectedId(data[0]?.id || null);
      }
    } catch {
      setItems([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // The Atlas page refreshes on a slower cadence; this panel only reloads when
    // the Atlas is opened or an action completes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingCount]);

  const selected = items.find((item) => item.id === selectedId) || null;
  const selectedProjectMatches = useMemo(
    () => (selected?.matches || []).slice(0, 3),
    [selected]
  );

  useEffect(() => {
    if (!selected) return;
    if (selected.matches?.length) return;
    api.getUnknownSuggestions(selected.id).then((resolved) => {
      setItems((prev) => prev.map((item) => (item.id === resolved.id ? resolved : item)));
    }).catch(() => {});
  }, [selected?.id]);

  const assign = async (itemId: string, projectId: string) => {
    setBusy(true);
    try {
      await api.assignUnknownItem(itemId, projectId);
      await load();
      await onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  const keep = async (itemId: string) => {
    setBusy(true);
    try {
      await api.keepUnknownItem(itemId);
      await load();
      await onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  const dismiss = async (itemId: string) => {
    setBusy(true);
    try {
      await api.dismissUnknownItem(itemId);
      await load();
      await onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  const createProject = async () => {
    if (!selected || !newProjectName.trim()) return;
    setCreating(true);
    try {
      await api.createProjectFromUnknown(selected.id, newProjectName.trim());
      setNewProjectName("");
      await load();
      await onChanged?.();
    } finally {
      setCreating(false);
    }
  };

  return (
    <section className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-border px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warning/10 text-warning">
            <Inbox className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-text-main">Context Inbox</h2>
            <p className="mt-1 max-w-2xl text-[11px] leading-5 text-text-muted">
              Only ambiguous or genuinely unrecognized project evidence reaches you. Everything else is routed automatically.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-warning/20 bg-warning/5 px-2.5 py-1 text-[10px] font-semibold text-warning">
            {pendingCount} pending
          </span>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-canvas px-2.5 py-1.5 text-[11px] font-medium text-text-muted hover:text-text-main disabled:opacity-50"
          >
            <RefreshCw className={"h-3.5 w-3.5 " + (loading ? "animate-spin" : "")} />
            Refresh
          </button>
        </div>
      </div>

      <div className="grid lg:grid-cols-[0.9fr_1.1fr]">
        <div className="border-b border-border lg:border-b-0 lg:border-r">
          {loading && items.length === 0 ? (
            <div className="flex min-h-44 items-center justify-center text-xs text-text-muted">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading context
            </div>
          ) : items.length === 0 ? (
            <div className="flex min-h-44 flex-col items-center justify-center px-5 text-center">
              <Check className="h-5 w-5 text-success" />
              <div className="mt-2 text-xs font-semibold text-text-main">Nothing needs you</div>
              <div className="mt-1 max-w-sm text-[11px] leading-5 text-text-muted">
                Synora has a confident destination for current source evidence.
              </div>
            </div>
          ) : (
            <div className="max-h-[360px] divide-y divide-border overflow-y-auto">
              {items.map((item) => {
                const active = item.id === selectedId;
                return (
                  <button
                    type="button"
                    key={item.id}
                    onClick={() => setSelectedId(item.id)}
                    className={"w-full px-5 py-4 text-left transition-colors " + (active ? "bg-primary-soft/60" : "hover:bg-canvas")}
                  >
                    <div className="flex items-center gap-2">
                      <span className="rounded-md bg-canvas px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                        {SOURCE_LABEL[item.source] || item.source}
                      </span>
                      <span className="font-mono text-[10px] text-text-muted">{item.id}</span>
                    </div>
                    <div className="mt-2 line-clamp-2 text-xs font-medium leading-5 text-text-main">
                      {item.content || "(no text)"}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="min-w-0 p-5">
          {!selected ? (
            <div className="flex min-h-44 items-center justify-center text-center text-xs text-text-muted">
              <div>
                <AlertTriangle className="mx-auto h-5 w-5 text-warning" />
                <div className="mt-2 font-medium">Select a context item</div>
                <div className="mt-1">Synora will show why it is uncertain and the projects it considers plausible.</div>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">
                  Original evidence
                </div>
                <p className="mt-2 text-sm leading-6 text-text-main">{selected.content}</p>
              </div>

              <div className="rounded-xl border border-warning/20 bg-warning/5 p-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-warning">
                  Why it was held
                </div>
                <p className="mt-1 text-[11px] leading-5 text-text-muted">
                  {selectedProjectMatches.length
                    ? "Multiple plausible project destinations exist, so Synora is waiting for one human routing decision."
                    : "No sufficiently strong project match was found from the available context."}
                </p>
              </div>

              {selectedProjectMatches.length > 0 && (
                <div className="space-y-2.5">
                  <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Suggested destination</div>
                  {selectedProjectMatches.map((match, index) => (
                    <div key={match.id} className="rounded-xl border border-border bg-canvas p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-xs font-semibold text-text-main">
                              {match.candidate_project_name || match.candidate_project_id}
                            </span>
                            {index === 0 && (
                              <span className="rounded-full bg-primary-soft px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">
                                top match
                              </span>
                            )}
                          </div>
                          {match.similarity_reason?.[0] && (
                            <div className="mt-1 text-[11px] leading-5 text-text-muted">{match.similarity_reason[0]}</div>
                          )}
                        </div>
                        <button
                          type="button"
                          onClick={() => assign(selected.id, match.candidate_project_id)}
                          disabled={busy}
                          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
                        >
                          Assign
                          <ArrowRight className="h-3 w-3" />
                        </button>
                      </div>
                      {match.conflicts?.length > 0 && (
                        <div className="mt-2 text-[10px] text-warning">{match.conflicts[0]}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <div className="grid gap-2 sm:grid-cols-2">
                <select
                  value=""
                  disabled={busy}
                  onChange={(event) => {
                    const projectId = event.target.value;
                    if (projectId) assign(selected.id, projectId);
                  }}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs text-text-main outline-none focus:border-primary"
                >
                  <option value="">Choose another project…</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>{project.name}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => keep(selected.id)}
                  disabled={busy}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-2 text-xs font-semibold text-text-main hover:bg-canvas disabled:opacity-50"
                >
                  Keep unknown
                </button>
              </div>

              <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                <div className="flex items-center gap-2 rounded-lg border border-border bg-canvas px-3 py-2">
                  <Plus className="h-3.5 w-3.5 text-text-muted" />
                  <input
                    value={newProjectName}
                    onChange={(event) => setNewProjectName(event.target.value)}
                    placeholder="Create a new project from this context"
                    className="w-full bg-transparent text-xs text-text-main outline-none placeholder:text-text-muted"
                  />
                </div>
                <button
                  type="button"
                  onClick={createProject}
                  disabled={creating || busy || !newProjectName.trim()}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-primary/20 bg-primary-soft px-3 py-2 text-xs font-semibold text-primary hover:bg-primary/10 disabled:opacity-50"
                >
                  {creating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                  Create
                </button>
              </div>

              <button
                type="button"
                onClick={() => dismiss(selected.id)}
                disabled={busy}
                className="inline-flex items-center gap-1.5 text-[11px] font-medium text-text-muted hover:text-text-main disabled:opacity-50"
              >
                <CircleX className="h-3.5 w-3.5" />
                Dismiss as irrelevant
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
