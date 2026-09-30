"use client";

import React, { useEffect, useState } from "react";
import { BrainCircuit, CheckCircle2, Clock3, Maximize2, PenTool } from "lucide-react";
import { ExcalidrawArtifact, ExcalidrawProposal } from "@/lib/types";
import { api } from "@/lib/api";
import { ExcalidrawCanvas } from "@/components/canvas/ExcalidrawCanvas";
import { ExcalidrawSyncBar } from "@/components/common/ExcalidrawSyncBar";

interface ArchitectureViewProps {
  artifact: ExcalidrawArtifact | null;
  proposals: ExcalidrawProposal[];
  currentStateVersion: number;
  decisions?: Array<{ id: string; text: string; date: string; evidence_ids?: string[]; approved_by?: string; detail?: string }>;
  syncStatus?: "synchronized" | "updating" | "pending" | "outdated" | "failed";
  lastSyncAt?: string | null;
  onRetrySync?: () => Promise<void>;
  onGenerateProposal: (stateVersion?: number) => Promise<void>;
  onReviewProposal: (proposalId: string, action: "approve" | "reject", reason?: string) => Promise<void>;
  onIngestScene: (scene: { name: string; elements: any[]; app_state?: any }) => Promise<void>;
  onSyncLivingWorkspace?: () => Promise<void>;
  onAiGenerateVisuals?: (focusPrompt?: string, directApply?: boolean) => Promise<void>;
}

export function ArchitectureView({
  artifact,
  currentStateVersion,
  syncStatus = "synchronized",
  lastSyncAt = null,
  onRetrySync,
}: ArchitectureViewProps) {
  const projectId = artifact?.project_id;
  const [revisionCount, setRevisionCount] = useState(0);
  const [currentRevision, setCurrentRevision] = useState<number | null>(null);

  useEffect(() => {
    if (!projectId) return;
    api.getVisualRevisions(projectId)
      .then((data) => {
        setRevisionCount(data?.revisions?.length || 0);
        setCurrentRevision(data?.current_revision_number ?? null);
      })
      .catch(() => {
        setRevisionCount(0);
        setCurrentRevision(null);
      });
  }, [projectId, artifact?.version]);

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-2">
            <div className="inline-flex w-fit items-center gap-2 rounded-full border border-primary/15 bg-primary-soft px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
              <BrainCircuit className="h-3.5 w-3.5" />
              AI-maintained workspace
            </div>
            <h1 className="text-2xl font-semibold tracking-tight text-text-main">Architecture</h1>
            <p className="max-w-2xl text-sm text-text-muted">
              Synora turns current project knowledge into a living architecture diagram. The canvas is stored in the database.
            </p>
          </div>
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface p-4 shadow-xs">
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Project state</div>
          <div className="mt-2 text-lg font-semibold text-primary">v{currentStateVersion}</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4 shadow-xs">
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Diagram</div>
          <div className="mt-2 text-lg font-semibold text-text-main">v{artifact?.version || 1}</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4 shadow-xs">
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Visual revisions</div>
          <div className="mt-2 flex items-center gap-1.5 text-lg font-semibold text-text-main">
            <Clock3 className="h-4 w-4 text-text-muted" />
            {revisionCount}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4 shadow-xs">
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Storage</div>
          <div className="mt-2 flex items-center gap-1.5 text-sm font-semibold text-success">
            <CheckCircle2 className="h-4 w-4" />
            PostgreSQL
          </div>
        </div>
      </section>

      <ExcalidrawSyncBar
        status={syncStatus}
        lastSyncAt={lastSyncAt || artifact?.updated_at}
        onRetry={onRetrySync}
      />

      <section className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <div className="flex items-center gap-2">
            <PenTool className="h-4 w-4 text-primary" />
            <div>
              <h2 className="text-sm font-semibold text-text-main">
                {artifact?.name || "System architecture"}
              </h2>
              <p className="text-[11px] text-text-muted">
                {currentRevision ? "Current visual revision " + currentRevision : "Current visual workspace"}
              </p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-success/20 bg-success/5 px-2.5 py-1 text-[10px] font-semibold text-success">
            <CheckCircle2 className="h-3.5 w-3.5" />
            AI synchronized
          </span>
        </div>

        <div className="p-2">
          <ExcalidrawCanvas
            projectName={artifact?.name || "System Architecture"}
            version={artifact?.version || 1}
            initialElements={artifact?.elements || []}
            initialAppState={artifact?.app_state}
            compareMode={false}
            onSaveCanvas={undefined}
            onExportJson={undefined}
          />
        </div>
      </section>

      <div className="flex items-center justify-center gap-2 text-[11px] text-text-muted">
        <Maximize2 className="h-3.5 w-3.5" />
        <span>Use fullscreen to inspect the architecture in detail. Routine visual updates are handled by Synora.</span>
      </div>
    </div>
  );
}