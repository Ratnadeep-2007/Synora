"use client";

import React, { useMemo } from "react";
import { BrainCircuit, Layers3, Maximize2, PanelLeft, Sparkles } from "lucide-react";
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
            One living workspace
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-text-main">Project Atlas</h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-text-muted">
            One infinite Excalidraw canvas. Read each project top-to-bottom: intent → visual architecture → evidence-backed context. Diagrams carry the story; text is used where precision matters.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <Layers3 className="h-3.5 w-3.5 text-primary" />
            <span className="font-semibold text-text-main">{projectCount}</span> projects
          </div>
          <div className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-xs text-text-muted">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            <span className="font-semibold text-text-main">DB backed</span>
          </div>
          <div className={"inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs " + (pending ? "border-warning/20 bg-warning/5 text-warning" : "border-success/20 bg-success/5 text-success")}>
            <PanelLeft className="h-3.5 w-3.5" />
            {pending ? pending + " context item" + (pending === 1 ? "" : "s") + " need review" : "No context review needed"}
          </div>
        </div>
      </header>

      {activeName && (
        <div className="text-[11px] text-text-muted">
          Active project: <span className="font-semibold text-text-main">{activeName}</span>
          <span className="ml-1.5">• the atlas shows every project, not just the active one.</span>
        </div>
      )}

      <section className="overflow-hidden rounded-2xl border border-border bg-surface shadow-xs">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <div>
            <h2 className="text-sm font-semibold text-text-main">Infinite project canvas</h2>
            <p className="mt-0.5 text-[11px] text-text-muted">
              Context Inbox → project intent → architecture → evidence-backed context stories
            </p>
          </div>
          <div className="inline-flex items-center gap-1.5 rounded-full border border-success/20 bg-success/5 px-2.5 py-1 text-[10px] font-semibold text-success">
            AI synchronized
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
          ["Architecture", "Experience → logic → data → integrations"],
          ["Decision", "Situation → choice → basis → consequence"],
          ["Requirement", "Need → behaviour → validation"],
          ["Question", "Known → gap → evidence → resolution"],
        ].map(([label, flow]) => (
          <div key={label} className="rounded-lg border border-border bg-canvas px-3 py-2.5">
            <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-text-muted">{label}</div>
            <div className="mt-1 text-[10px] font-medium text-text-main">{flow}</div>
            {label === "Architecture" && (
              <div className="mt-1 text-[9px] text-text-muted">Oval = actor/result • diamond = decision/gap • arrows = flow</div>
            )}
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
