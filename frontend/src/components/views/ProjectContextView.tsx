"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, FileStack, Loader2 } from "lucide-react";
import { CandidateKnowledgeItem, Conflict, EvidenceItem, Project, ProjectMemoryBriefing } from "@/lib/types";
import { api } from "@/lib/api";
import { SourceInputsPanel } from "./SourceInputsPanel";

function ago(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const hours = Math.max(0, Math.floor((Date.now() - date.getTime()) / 3_600_000));
  if (hours < 1) return "Just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return days < 7 ? `${days}d ago` : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function sourceName(source: string) {
  return source.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function ProjectContextView({
  project,
  projects,
  evidence,
  candidates,
  conflicts,
  onOpenEvidence,
  onChanged,
  onReviewConflict,
}: {
  project?: Project | null;
  projects: Project[];
  evidence: EvidenceItem[];
  candidates: CandidateKnowledgeItem[];
  conflicts: Conflict[];
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
  onChanged: () => Promise<void> | void;
  onReviewConflict: (conflictId: string, action: "approve" | "reject" | "mark_unresolved") => Promise<void>;
}) {
  const [reviewingConflictId, setReviewingConflictId] = useState<string | null>(null);
  const [briefing, setBriefing] = useState<ProjectMemoryBriefing | null>(null);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [briefingError, setBriefingError] = useState(false);
  const memoryRefreshKey = JSON.stringify([
    evidence.map(item => item.id),
    candidates.map(item => [item.id, item.status]),
    conflicts.map(item => [item.id, item.status]),
  ]);
  useEffect(() => {
    let cancelled = false;
    const projectId = project?.id;
    if (!projectId) {
      setBriefing(null);
      setBriefingLoading(false);
      return;
    }
    setBriefing((current) => current?.project_id === projectId ? current : null);
    setBriefingLoading(true);
    setBriefingError(false);
    api.getProjectMemoryBriefing(projectId).then((data) => {
      if (!cancelled) setBriefing(data);
    }).catch(() => {
      if (!cancelled) setBriefingError(true);
    }).finally(() => {
      if (!cancelled) setBriefingLoading(false);
    });
    return () => { cancelled = true; };
  }, [project?.id, memoryRefreshKey]);
  const currentBriefing = briefing?.project_id === project?.id ? briefing : null;
  const memoryRows = (["constraints", "decisions", "open_questions", "requirements"] as const).flatMap((section) =>
    (currentBriefing?.project_state[section] || []).slice(0, 3).map((item, index) => ({
      key: `${section}-${index}`,
      kind: section === "constraints" ? "Constraint" : section === "decisions" ? "Decision" : section === "requirements" ? "Requirement" : "Open question",
      text: typeof item === "string" ? item : item.text || item.content || item.title || "",
      evidenceIds: typeof item === "string" ? [] : item.evidence_ids || [],
    }))
  ).filter((item) => item.text);
  const latestCandidates = [...candidates].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4);
  const latestEvidence = [...evidence].sort((a, b) =>
    new Date(b.occurred_at || b.created_at).getTime() - new Date(a.occurred_at || a.created_at).getTime()
  ).slice(0, 5);
  const openConflicts = conflicts.filter((item) => item.status === "open" || item.status === "under_review");

  if (!project) {
    return <div className="mx-auto max-w-5xl px-5 py-10 sm:px-8">
      <div className="rounded-xl border border-border bg-surface p-8 text-center shadow-xs">
        <FileStack className="mx-auto h-8 w-8 text-text-muted" />
        <h1 className="mt-3 text-lg font-semibold">Choose a project to add context</h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-text-muted">Project Context keeps each source, transcript, and memory update inside one selected project.</p>
        <p className="mt-4 text-xs text-text-dim">Create or select a project from the workspace menu to continue.</p>
      </div>
    </div>;
  }

  return (
    <main className="mx-auto w-full max-w-7xl space-y-5 px-4 pb-12 pt-6 sm:px-7 sm:pt-9 lg:px-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-text-dim">
            <span className="grid h-6 w-6 place-items-center rounded-md border border-border bg-surface text-text-muted"><FileStack className="h-3.5 w-3.5" /></span>
            Project workspace <span className="text-border-active">/</span> Context
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-main sm:text-[30px]">{project.name} context</h1>
          <p className="mt-1.5 max-w-2xl text-sm text-text-muted">Add source material and review what Synora extracts for this project.</p>
        </div>
      </header>

      {openConflicts.length > 0 && <section className="rounded-xl border border-warning/30 bg-warning/5 p-4 shadow-xs" aria-label="Conflicts to review">
        <div className="mb-3 flex items-start gap-2.5"><AlertTriangle className="mt-0.5 h-4 w-4 text-warning" /><div><h2 className="text-sm font-semibold">Review before updating memory ({openConflicts.length})</h2><p className="mt-1 text-xs text-text-muted">These uploads disagree with the project’s current decisions or requirements. Memory stays unchanged until you choose.</p></div></div>
        <div className="space-y-3">{openConflicts.map((conflict) => <article key={conflict.id} className="rounded-lg border border-border bg-surface p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-xs font-semibold">{conflict.title}</h3><span className="rounded border border-border px-1.5 py-0.5 text-[9px] uppercase text-text-muted">{conflict.type} · {conflict.severity}</span></div>
          <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">{conflict.description}</p>
          <div className="mt-2 flex flex-wrap gap-2 text-[10px]"><button onClick={() => onOpenEvidence(conflict.title, `${conflict.type} conflict`, conflict.evidence_ids || [])} className="text-primary hover:underline">Inspect source evidence ({conflict.evidence_ids?.length || 0})</button></div>
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <button disabled={reviewingConflictId === conflict.id} onClick={async () => { setReviewingConflictId(conflict.id); try { await onReviewConflict(conflict.id, "reject"); } finally { setReviewingConflictId(null); } }} className="rounded-md border border-border px-3 py-1.5 text-[11px] font-medium text-danger disabled:opacity-50">Keep current memory</button>
            <button disabled={reviewingConflictId === conflict.id} onClick={async () => { setReviewingConflictId(conflict.id); try { await onReviewConflict(conflict.id, "approve"); } finally { setReviewingConflictId(null); } }} className="rounded-md bg-primary px-3 py-1.5 text-[11px] font-semibold text-white disabled:opacity-50">{reviewingConflictId === conflict.id ? "Applying…" : "Approve proposal"}</button>
          </div>
        </article>)}</div>
      </section>}

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(280px,.7fr)] xl:items-start">
        <SourceInputsPanel key={project.id} projects={projects} selectedProject={project} onChanged={onChanged} />

        <aside className="space-y-4">
          <section className="overflow-hidden rounded-xl border border-border bg-surface shadow-xs" aria-label="Current project memory">
            <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3.5">
              <div><h2 className="text-xs font-semibold">Current project memory</h2><p className="mt-0.5 text-[10px] text-text-muted">Selected active project knowledge</p></div>
              {briefingLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin text-text-muted" aria-label="Loading memory" /> : currentBriefing && <span className="text-[10px] text-text-dim">v{currentBriefing.state_version}</span>}
            </div>
            {memoryRows.length > 0 && <div className="divide-y divide-border-subtle">{memoryRows.slice(0, 5).map((item) => <article key={item.key} className="px-4 py-3">
              <span className="text-[9px] font-semibold uppercase tracking-wide text-text-dim">{item.kind}</span>
              <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-text-main">{item.text}</p>
              {item.evidenceIds.length > 0 && <button type="button" onClick={() => onOpenEvidence(item.text, item.kind, item.evidenceIds)} className="mt-1.5 text-[10px] text-primary hover:underline">Inspect source evidence ({item.evidenceIds.length})</button>}
            </article>)}</div>}
            {briefingError && <p role="status" className="px-4 py-3 text-[11px] text-warning">Could not refresh memory. Reopen the Context tab to retry.</p>}
            {!briefingError && !briefingLoading && !memoryRows.length && <p className="px-4 py-5 text-[11px] text-text-muted">Approved project knowledge will appear here as memory is updated.</p>}
            {currentBriefing && (!currentBriefing.context_metadata.complete || memoryRows.length > 5) && <p className="border-t border-border-subtle px-4 py-2 text-[10px] text-text-muted">Showing selected context. Full details remain in project state and source evidence.</p>}
          </section>
          <section className="overflow-hidden rounded-xl border border-border bg-surface shadow-xs">
            <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3.5">
              <div><h2 className="text-xs font-semibold">Recent source material</h2><p className="mt-0.5 text-[10px] text-text-muted">Evidence connected to this project</p></div>
              <span className="rounded-md bg-surface-muted px-2 py-1 text-[10px] font-medium text-text-muted">{evidence.length}</span>
            </div>
            {latestEvidence.length ? <div className="divide-y divide-border-subtle">
              {latestEvidence.map((item) => <button key={item.id} onClick={() => onOpenEvidence(`${sourceName(item.source)} evidence`, item.source, [item.id])} className="w-full px-4 py-3 text-left transition hover:bg-surface-muted/60">
                <span className="flex items-center justify-between gap-3"><span className="text-[10px] font-semibold text-text-main">{sourceName(item.source)}</span><span className="text-[10px] text-text-dim">{ago(item.occurred_at || item.created_at)}</span></span>
                <span className="mt-1 line-clamp-2 block text-[11px] leading-relaxed text-text-muted">{item.content}</span>
              </button>)}
            </div> : <div className="px-4 py-7 text-center"><FileStack className="mx-auto h-5 w-5 text-text-dim" /><p className="mt-2 text-xs font-medium">No sources yet</p><p className="mt-1 text-[10px] text-text-muted">Add a note, document, image, or audio transcript.</p></div>}
          </section>

          <section className="overflow-hidden rounded-xl border border-border bg-surface shadow-xs">
            <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3.5">
              <div><h2 className="text-xs font-semibold">Latest extracted context</h2><p className="mt-0.5 text-[10px] text-text-muted">Signals from newly ingested sources</p></div>
              <span className="rounded-md bg-surface-muted px-2 py-1 text-[10px] font-medium text-text-muted">{candidates.length}</span>
            </div>
            {latestCandidates.length ? <div className="divide-y divide-border-subtle">
              {latestCandidates.map((candidate) => <div key={candidate.id} className="px-4 py-3">
                <div className="flex items-center justify-between gap-3"><span className="truncate text-[11px] font-semibold text-text-main">{candidate.title}</span><span className="shrink-0 rounded-md border border-border px-1.5 py-0.5 text-[9px] text-text-muted">{candidate.status}</span></div>
                <p className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-text-muted">{candidate.content}</p>
              </div>)}
            </div> : <div className="px-4 py-5 text-[11px] text-text-muted">Extracted facts and proposals will appear here after ingestion.</div>}
          </section>

        </aside>
      </section>
    </main>
  );
}
