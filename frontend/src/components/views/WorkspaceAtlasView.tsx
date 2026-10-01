"use client";

import React, { useMemo } from "react";
import { ArrowRight, BrainCircuit, Layers3, Maximize2, PanelLeft, Sparkles } from "lucide-react";
import { ExcalidrawCanvas } from "@/components/canvas/ExcalidrawCanvas";
import { Project, WorkspaceAtlasData } from "@/lib/types";
import { ContextInboxPanel } from "@/components/views/ContextInboxPanel";

interface WorkspaceAtlasViewProps {
  atlas: WorkspaceAtlasData | null;
  projects: Project[];
  activeProjectId?: string | null;
  onChanged?: () => Promise<void> | void;
}

export function WorkspaceAtlasView({
  atlas,
  projects,
  activeProjectId,
  onChanged,
}: WorkspaceAtlasViewProps) {
  const projectCount = atlas?.projects?.length || 0;
  const pending = atlas?.unknown_context?.pending || 0;

  const activeName = useMemo(
    () => projects.find((p) => p.id === activeProjectId)?.name || null,
    [projects, activeProjectId]
  );

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/15 bg-primary-soft px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
            <BrainCircuit className="h-3.5 w-3.5" />
            One shared memory
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-text-main">Project Atlas</h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-text-muted">
            One infinite Excalidraw workspace. WhatsApp and completed meeting transcripts feed the same project-bounded memory, which Synora turns into visual notes automatically.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <Layers3 className="h-3.5 w-3.5 text-primary" />
            <span className="font-semibold text-text-main">{projectCount}</span> projects
          </div>
          <div className="inline-flex items-center gap-2 rounded-lg border border-success/20 bg-success/5 px-3 py-2 text-xs text-success">
            <Sparkles className="h-3.5 w-3.5" />
            <span className="font-semibold">AI auto-maintained</span>
          </div>
          <div className={"inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs " + (pending ? "border-warning/20 bg-warning/5 text-warning" : "border-success/20 bg-success/5 text-success")}>
            <PanelLeft className="h-3.5 w-3.5" />
            {pending ? pending + " context item" + (pending === 1 ? "" : "s") + " need attention" : "No unresolved context"}
          </div>
        </div>
      </header>

      {activeName && (
        <div className="text-[11px] text-text-muted">
          Active project: <span className="font-semibold text-text-main">{activeName}</span>
          <span className="ml-1.5">• the atlas shows every project and never mixes their memory.</span>
        </div>
      )}

      <section className="overflow-hidden rounded-2xl border border-border bg-surface shadow-xs">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <div>
            <h2 className="text-sm font-semibold text-text-main">Infinite project canvas</h2>
            <p className="mt-0.5 text-[11px] text-text-muted">
              Sources → evidence → project memory → visual notes
            </p>
          </div>
          <div className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary-soft px-2.5 py-1 text-[10px] font-semibold text-primary">
            Project boundaries enforced
          </div>
        </div>

        <div className="p-2">
          {atlas ? (
            <ExcalidrawCanvas
              key={atlas.artifact.id + ":" + atlas.artifact.version}
              projectId={atlas.artifact.project_id}
              projectName="Synora Project Atlas"
              version={atlas.artifact.version}
              initialElements={atlas.artifact.elements || []}
              initialAppState={{
                ...(atlas.artifact.app_state || {}),
                viewBackgroundColor: "#f7f8f5",
                theme: "light",
              }}
              compareMode={false}
              onSaveCanvas={undefined}
              onExportJson={undefined}
              readOnly
            />
          ) : (
            <div className="flex min-h-[640px] items-center justify-center rounded-xl border border-border bg-canvas text-xs text-text-muted">
              Preparing the Project Atlas…
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-2 sm:grid-cols-4">
        {[
          ["Sources", "WhatsApp + completed meeting transcript"],
          ["Memory", "One engine • one boundary per project"],
          ["Notes", "Decision • requirement • constraint • question"],
          ["Visual", "Architecture first • evidence-backed context"],
        ].map(([label, flow], index) => (
          <div key={label} className="rounded-lg border border-border bg-canvas px-3 py-2.5">
            <div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.14em] text-text-muted">
              <span>{label}</span>
              {index < 3 && <ArrowRight className="h-3 w-3" />}
            </div>
            <div className="mt-1 text-[10px] font-medium text-text-main">{flow}</div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-center gap-2 text-[11px] text-text-muted">
        <Maximize2 className="h-3.5 w-3.5" />
        <span>Zoom out to see the whole workspace; zoom in to inspect one project column.</span>
      </div>

      <ContextInboxPanel
        projects={projects}
        pendingCount={pending}
        onChanged={onChanged}
      />
    </div>
  );
}
