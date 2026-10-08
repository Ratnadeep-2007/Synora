"use client";

import React, { useMemo } from "react";
import {
  BrainCircuit,
  Layers3,
  Sparkles,
  PanelLeft,
  Maximize2,
  ArrowRight,
  ShieldCheck,
  RefreshCw,
  Zap,
} from "lucide-react";
import { ExcalidrawCanvas } from "@/components/canvas/ExcalidrawCanvas";
import { Project, WorkspaceAtlasData } from "@/lib/types";
import { ContextInboxPanel } from "@/components/views/ContextInboxPanel";

interface WorkspaceAtlasViewProps {
  atlas: WorkspaceAtlasData | null;
  projects: Project[];
  activeProjectId?: string | null;
  onChanged?: () => Promise<void> | void;
}

export const WorkspaceAtlasView = React.memo(function WorkspaceAtlasView({
  atlas,
  projects = [],
  activeProjectId,
  onChanged,
}: WorkspaceAtlasViewProps) {
  const projectCount = atlas?.projects?.length || projects.length || 0;
  const pending = atlas?.unknown_context?.pending || 0;
  const atlasVersion = atlas?.artifact?.version || 1;

  const initialAppState = useMemo(
    () => ({
      ...(atlas?.artifact?.app_state || {}),
      viewBackgroundColor: "#f6f5f1",
      theme: "light",
    }),
    [atlas?.artifact?.id]
  );

  const activeName = useMemo(
    () => projects.find((p) => p.id === activeProjectId)?.name || null,
    [projects, activeProjectId]
  );

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 view-enter">
      {/* Ambient HUD Header */}
      <header className="reveal border-b border-border pb-5 flex flex-col md:flex-row md:items-end justify-between gap-4" style={{ "--reveal-delay": "0ms" } as React.CSSProperties}>
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">
            <BrainCircuit className="h-3.5 w-3.5" />
            External Visual Brain
          </div>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-text-main flex items-center gap-3">
            <span>Project Atlas</span>
            <span className="font-mono text-sm px-2.5 py-0.5 rounded-lg bg-surface border border-border text-primary font-bold">
              Canvas v{atlasVersion}
            </span>
          </h1>
          <p className="mt-1 text-sm text-text-muted max-w-2xl leading-relaxed">
            One infinite workspace. Each project owns a free-form visual canvas; Synora chooses the notes, sketches, diagrams, or other representations that fit its current context.
          </p>
        </div>

        {/* Ambient Status HUD */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2 bg-surface px-3 py-1.5 rounded-xl border border-border text-xs text-text-muted">
            <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
            <span className="text-text-main font-medium">Project canvases synchronized</span>
          </div>

          <div className="flex items-center gap-1.5 bg-surface px-3 py-1.5 rounded-xl border border-border text-xs text-text-muted font-mono">
            <Layers3 className="w-3.5 h-3.5 text-primary" />
            <span>{projectCount} Projects Mapped</span>
          </div>

          {pending > 0 && (
            <div className="flex items-center gap-1.5 bg-warning/10 border border-warning/30 px-3 py-1.5 rounded-xl text-xs text-warning font-semibold">
              <PanelLeft className="w-3.5 h-3.5" />
              <span>{pending} Context Inquiries Pending</span>
            </div>
          )}
        </div>
      </header>

      {/* Active Project Scope Pill */}
      {activeName && (
        <div className="flex items-center justify-between text-xs px-4 py-2 rounded-xl bg-surface border border-border text-text-muted">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-primary" />
            <span>Active Focus: <strong className="text-text-main">{activeName}</strong></span>
          </div>
          <span className="text-[11px] font-mono text-text-muted">
            Strict project boundaries preserved • No memory contamination
          </span>
        </div>
      )}

      {/* The Living Canvas Surface */}
      <section className="reveal rounded-2xl border border-border bg-surface shadow-sm overflow-hidden relative" style={{ "--reveal-delay": "60ms" } as React.CSSProperties}>
        {/* Canvas Toolbar Top Bar */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border/80 bg-surface-soft text-xs">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-text-main">Project Canvases</span>
            <span className="text-[11px] text-text-muted font-mono">• Excalidraw Engine • free-form per project</span>
          </div>

          <div className="flex items-center gap-3 text-text-muted text-[11px]">
            <span className="flex items-center gap-1">
              <Maximize2 className="w-3.5 h-3.5 text-primary" />
              <span>Pinch/Scroll to zoom • Drag to pan</span>
            </span>
          </div>
        </div>

        {/* Excalidraw Canvas Mount (Isolated touch-action and overscroll-behavior) */}
        <div className="p-2 bg-canvas overscroll-none touch-none select-none">
          {atlas ? (
            <ExcalidrawCanvas
              key={atlas.artifact.project_id || "workspace_atlas"}
              projectId={atlas.artifact.project_id}
              projectName="Synora Project Atlas"
              version={atlas.artifact.version}
              initialElements={atlas.artifact.elements || []}
              initialAppState={initialAppState}
              compareMode={false}
              onSaveCanvas={undefined}
              onExportJson={undefined}
              readOnly
            />
          ) : (
            <div className="flex min-h-[640px] items-center justify-center rounded-xl border border-border bg-canvas text-xs text-text-muted space-y-2">
              <div className="text-center space-y-2">
                <RefreshCw className="w-6 h-6 text-primary animate-spin mx-auto" />
                <p>Synthesizing Project Atlas visual model...</p>
              </div>
            </div>
          )}
        </div>
      </section>

      <div className="rounded-xl border border-border bg-surface p-4 text-xs text-text-muted">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="font-semibold text-text-main">Synora canvas rule</span>
          <span>Content format is open-ended.</span>
          <span>Project columns are the only workspace boundary.</span>
          <span>Human-authored Excalidraw content remains preserved.</span>
        </div>
      </div>

      {/* Unknown Context Inbox Panel */}
      <ContextInboxPanel
        projects={projects}
        pendingCount={pending}
        onChanged={onChanged}
      />
    </div>
  );
});
