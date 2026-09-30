"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  PenTool,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  GitBranch,
  Shield,
  Layers,
  Sparkles,
  GitCompareArrows,
  Download,
  ExternalLink,
  Plus,
} from "lucide-react";
import { ExcalidrawArtifact, ExcalidrawProposal } from "@/lib/types";
import { api } from "@/lib/api";
import { ExcalidrawCanvas } from "@/components/canvas/ExcalidrawCanvas";
import { ExcalidrawSyncBar } from "@/components/common/ExcalidrawSyncBar";
import {
  VisualRevisionDiff,
  VisualRevisionPanel,
  VisualRevisionSummary,
} from "@/components/common/VisualRevisionPanel";

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
  proposals,
  currentStateVersion,
  decisions = [],
  syncStatus = "synchronized",
  lastSyncAt = null,
  onRetrySync,
  onGenerateProposal,
  onReviewProposal,
  onIngestScene,
  onSyncLivingWorkspace,
  onAiGenerateVisuals,
}: ArchitectureViewProps) {
  const [isSyncingWorkspace, setIsSyncingWorkspace] = useState(false);
  const [processingProposalId, setProcessingProposalId] = useState<string | null>(null);

  // Immutable visual revision history
  const [revisions, setRevisions] = useState<VisualRevisionSummary[]>([]);
  const [currentRevisionNumber, setCurrentRevisionNumber] = useState<number | null>(null);
  const [compareFrom, setCompareFrom] = useState<number | null>(null);
  const [revisionDiff, setRevisionDiff] = useState<VisualRevisionDiff | null>(null);
  const [compareElements, setCompareElements] = useState<any[]>([]);
  const [compareAddedIds, setCompareAddedIds] = useState<string[]>([]);
  const [compareChangedIds, setCompareChangedIds] = useState<string[]>([]);
  const [isRevisionBusy, setIsRevisionBusy] = useState(false);

  const projectId = artifact?.project_id;

  const loadRevisions = async () => {
    if (!projectId) return;
    try {
      const data = await api.getVisualRevisions(projectId);
      setRevisions(data?.revisions || []);
      setCurrentRevisionNumber(data?.current_revision_number ?? null);
    } catch {
      setRevisions([]);
    }
  };

  const clearCompare = () => {
    setCompareFrom(null);
    setRevisionDiff(null);
    setCompareElements([]);
    setCompareAddedIds([]);
    setCompareChangedIds([]);
  };

  const elementSignature = (el: any) =>
    JSON.stringify(
      {
        type: el?.type,
        text: el?.text,
        x: el?.x,
        y: el?.y,
        width: el?.width,
        height: el?.height,
        points: el?.points,
        startBinding: el?.startBinding,
        endBinding: el?.endBinding,
        backgroundColor: el?.backgroundColor,
        strokeColor: el?.strokeColor,
      },
      Object.keys({
        type: el?.type,
        text: el?.text,
        x: el?.x,
        y: el?.y,
        width: el?.width,
        height: el?.height,
        points: el?.points,
        startBinding: el?.startBinding,
        endBinding: el?.endBinding,
        backgroundColor: el?.backgroundColor,
        strokeColor: el?.strokeColor,
      }).sort()
    );

  const buildCompareScene = (historicalElements: any[], currentElements: any[], revisionNumber: number) => {
    const historical = Array.isArray(historicalElements) ? historicalElements : [];
    const current = Array.isArray(currentElements) ? currentElements : [];
    const historicalById = new Map(historical.map((el) => [String(el?.id), el]));
    const currentById = new Map(current.map((el) => [String(el?.id), el]));

    const added = current.filter((el) => el?.id && !historicalById.has(String(el.id))).map((el) => String(el.id));
    const changed = current
      .filter((el) => {
        if (!el?.id || !historicalById.has(String(el.id))) return false;
        return elementSignature(historicalById.get(String(el.id))) !== elementSignature(el);
      })
      .map((el) => String(el.id));

    const currentStyled = current.map((el) => {
      const id = String(el?.id || "");
      if (!added.includes(id) && !changed.includes(id)) return el;
      const styled = { ...el };
      styled.opacity = 100;
      styled.strokeWidth = Math.max(Number(el?.strokeWidth || 2), 3);
      if (el?.type === "text") {
        styled.strokeColor = changed.includes(id) ? "#b45309" : "#15803d";
      } else if (el?.type === "arrow" || el?.type === "line") {
        styled.strokeColor = changed.includes(id) ? "#b45309" : "#15803d";
        styled.strokeStyle = "solid";
      } else {
        styled.strokeColor = changed.includes(id) ? "#b45309" : "#15803d";
        if (!el?.backgroundColor || el.backgroundColor === "transparent") {
          styled.backgroundColor = changed.includes(id) ? "#fffbeb" : "#ecfdf5";
        }
      }
      return styled;
    });

    const historicalGhosts = historical
      .filter((el) => {
        const id = String(el?.id || "");
        if (!id) return false;
        const matching = currentById.get(id);
        return !matching || elementSignature(matching) !== elementSignature(el);
      })
      .map((el) => {
        const id = String(el?.id || "");
        const ghost = {
          ...el,
          id: `compare-ghost-${revisionNumber}-${id}`,
          opacity: 42,
          strokeColor: "#94a3b8",
          strokeStyle: "dashed",
          locked: true,
        };
        if (ghost.type === "text") {
          ghost.strokeColor = "#64748b";
          ghost.opacity = 48;
        } else if (ghost.type === "arrow" || ghost.type === "line") {
          ghost.strokeColor = "#94a3b8";
          ghost.opacity = 42;
          delete ghost.startBinding;
          delete ghost.endBinding;
        } else {
          ghost.backgroundColor = "transparent";
          ghost.strokeColor = "#94a3b8";
        }
        ghost.boundElements = null;
        return ghost;
      });

    return {
      scene: [...historicalGhosts, ...currentStyled],
      addedIds: added,
      changedIds: changed,
    };
  };

  useEffect(() => {
    loadRevisions();
    clearCompare();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, artifact?.version]);

  const handleSelectCompare = async (revisionNumber: number) => {
    if (!projectId || currentRevisionNumber === null) return;
    try {
      setIsRevisionBusy(true);
      setCompareFrom(revisionNumber);

      const [diff, historicalRevision] = await Promise.all([
        api.compareVisualRevisions(projectId, revisionNumber, currentRevisionNumber),
        api.getVisualRevision(projectId, revisionNumber),
      ]);

      const historicalElements =
        historicalRevision?.elements ||
        historicalRevision?.scene ||
        historicalRevision?.snapshot?.elements ||
        [];

      const currentElements = artifact?.elements || [];
      const compareScene = buildCompareScene(historicalElements, currentElements, revisionNumber);

      setRevisionDiff(diff);
      setCompareElements(compareScene.scene);
      setCompareAddedIds(compareScene.addedIds);
      setCompareChangedIds(compareScene.changedIds);
    } catch (err: any) {
      clearCompare();
      alert(`Compare failed: ${err.message}`);
    } finally {
      setIsRevisionBusy(false);
    }
  };

  const handleRestoreRevision = async (revisionNumber: number) => {
    if (!projectId) return;
    if (!window.confirm(`Restore revision ${revisionNumber}? This creates a NEW revision and never overwrites history.`)) {
      return;
    }
    try {
      setIsRevisionBusy(true);
      await api.restoreVisualRevision(
        projectId,
        revisionNumber,
        `Restored from revision ${revisionNumber} via Excalidraw workspace`
      );
      setRevisionDiff(null);
      setCompareFrom(null);
      await loadRevisions();
    } catch (err: any) {
      alert(`Restore failed: ${err.message}`);
    } finally {
      setIsRevisionBusy(false);
    }
  };

  const [promptText, setPromptText] = useState("");
  const [isPromptGenerating, setIsPromptGenerating] = useState(false);

  const handlePromptToDiagram = async () => {
    if (!projectId || !promptText.trim()) return;
    try {
      setIsPromptGenerating(true);
      const res = await api.generateDiagramFromText(projectId, promptText.trim(), true);
      setPromptText("");
      if (res?.elements) {
        await onIngestScene({
          name: artifact?.name || "System Architecture",
          elements: res.elements,
          app_state: artifact?.app_state,
        });
      }
      await loadRevisions();
    } catch (err: any) {
      alert(`Generation failed: ${err.message}`);
    } finally {
      setIsPromptGenerating(false);
    }
  };

  const handleExportExcalidraw = () => {
    if (!artifact) return;
    const scene = {
      type: "excalidraw",
      version: 2,
      source: "https://synesis.app",
      elements: artifact.elements,
      appState: artifact.app_state || { viewBackgroundColor: "#ffffff", gridSize: 20 },
      files: {},
    };
    const blob = new Blob([JSON.stringify(scene, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${artifact.name || "architecture"}-v${artifact.version}.excalidraw`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleReview = async (proposalId: string, action: "approve" | "reject") => {
    try {
      setProcessingProposalId(proposalId);
      await onReviewProposal(proposalId, action);
    } finally {
      setProcessingProposalId(null);
    }
  };

  const pendingProposals = proposals.filter((p) => p.status === "pending");
  const reviewedProposals = proposals.filter((p) => p.status !== "pending");

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Clean Human-Friendly Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border/40">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-text-main flex items-center gap-2">
            <PenTool className="w-5 h-5 text-primary" />
            <span>Living workspace</span>
          </h1>
          <p className="text-xs text-text-muted mt-0.5">
            A visual workspace for the current project state, architecture, workflows, and decisions.
          </p>
        </div>
      </div>

      {/* Synchronization Bar */}
      <ExcalidrawSyncBar
        status={isSyncingWorkspace ? "updating" : syncStatus}
        lastSyncAt={lastSyncAt || artifact?.updated_at}
        onRetry={onRetrySync}
      />

      {/* AI-first operating status */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-xl border border-border bg-surface p-3.5 shadow-xs">
          <div className="text-[10px] uppercase tracking-wider font-bold text-text-muted">Operating mode</div>
          <div className="mt-1.5 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
            <span className="text-sm font-semibold text-text-main">AI Autopilot</span>
          </div>
          <div className="mt-1 text-[11px] text-text-muted">Routine analysis and visual updates are automated.</div>
        </div>

        <div className="rounded-xl border border-border bg-surface p-3.5 shadow-xs">
          <div className="text-[10px] uppercase tracking-wider font-bold text-text-muted">Human intervention</div>
          <div className="mt-1.5 text-sm font-semibold text-text-main">Ambiguous context only</div>
          <div className="mt-1 text-[11px] text-text-muted">Only unresolved or low-confidence routing needs attention.</div>
        </div>

        <div className="rounded-xl border border-border bg-surface p-3.5 shadow-xs">
          <div className="text-[10px] uppercase tracking-wider font-bold text-text-muted">Project state</div>
          <div className="mt-1.5 text-sm font-semibold text-primary">v{currentStateVersion}</div>
          <div className="mt-1 text-[11px] text-text-muted">Authoritative state used by the agent.</div>
        </div>

        <div className="rounded-xl border border-border bg-surface p-3.5 shadow-xs">
          <div className="text-[10px] uppercase tracking-wider font-bold text-text-muted">Diagram</div>
          <div className="mt-1.5 text-sm font-semibold text-text-main">v{artifact?.version || 1}</div>
          <div className="mt-1 text-[11px] text-text-muted">{artifact?.elements?.length || 0} elements • DB-backed</div>
        </div>
      </div>

      {/* Direct Automated Text -> Excalidraw Generator */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 p-2.5 bg-surface border border-border rounded-xl shadow-2xs">
        <input
          type="text"
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !isPromptGenerating && promptText.trim()) {
              handlePromptToDiagram();
            }
          }}
          placeholder="Type your system architecture or flow (e.g. Next.js Client -> FastAPI Gateway -> PostgreSQL & Redis)..."
          className="flex-1 px-3.5 py-2 text-xs bg-canvas border border-border rounded-lg text-text-main placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <button
          onClick={handlePromptToDiagram}
          disabled={isPromptGenerating || !promptText.trim()}
          className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary/90 rounded-lg flex items-center justify-center gap-2 transition-colors disabled:opacity-50 shrink-0 shadow-2xs"
          title="Directly compile text to Excalidraw diagram"
        >
          <Sparkles className={`w-3.5 h-3.5 ${isPromptGenerating ? "animate-spin text-amber-300" : "text-amber-300"}`} />
          <span>{isPromptGenerating ? "Generating..." : "Generate Diagram"}</span>
        </button>
        {onAiGenerateVisuals && (
          <button
            onClick={async () => {
              try {
                setIsPromptGenerating(true);
                await onAiGenerateVisuals("", true);
                await loadRevisions();
              } catch (err: any) {
                alert(`State diagram alignment failed: ${err.message}`);
              } finally {
                setIsPromptGenerating(false);
              }
            }}
            disabled={isPromptGenerating}
            className="px-3.5 py-2 text-xs font-semibold text-text-main bg-surface hover:bg-surface-hover border border-border rounded-lg flex items-center justify-center gap-2 transition-colors disabled:opacity-50 shrink-0 shadow-2xs"
            title="Auto-generate and synchronize diagram directly from Project State, requirements, and decisions"
          >
            <Sparkles className="w-3.5 h-3.5 text-primary" />
            <span>Auto-Align from State</span>
          </button>
        )}
      </div>

      {/* Primary Human-Facing Agent Output: Embedded Interactive Excalidraw Canvas */}
      {compareFrom !== null && currentRevisionNumber !== null && (
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-xl bg-primary-soft/50 border border-primary/20 text-xs">
          <div className="flex items-center gap-3 min-w-0">
            <GitCompareArrows className="w-4 h-4 text-primary shrink-0" />
            <div className="min-w-0">
              <p className="font-semibold text-text-main">Compare r{compareFrom} with current r{currentRevisionNumber}</p>
              <p className="text-[11px] text-text-muted">
                Historical elements are ghosted. Added elements are green. Changed elements are amber.
              </p>
            </div>
          </div>
          <button
            onClick={clearCompare}
            disabled={isRevisionBusy}
            className="px-2.5 py-1.5 rounded-md border border-border bg-surface text-text-main font-medium shrink-0 disabled:opacity-50"
          >
            Exit compare
          </button>
        </div>
      )}

      <ExcalidrawCanvas
        projectName={artifact?.name || "System Architecture"}
        version={artifact?.version || 1}
        initialElements={artifact?.elements || []}
        initialAppState={artifact?.app_state}
        isSyncing={isSyncingWorkspace}
        onSyncAgentOutput={onSyncLivingWorkspace}
        onSaveCanvas={onIngestScene}
        onExportJson={handleExportExcalidraw}
        compareMode={compareFrom !== null && compareElements.length > 0}
        compareElements={compareElements}
        compareAddedIds={compareAddedIds}
        compareChangedIds={compareChangedIds}
        compareFromRevision={compareFrom}
        compareToRevision={currentRevisionNumber}
      />

      {/* Authoritative Diagram Artifact Breakdown & Decision Citations */}
      <div className="p-5 rounded-xl bg-surface border border-border shadow-xs space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-primary-soft flex items-center justify-center font-bold text-primary">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-text-main">
                  {artifact?.name || "System Architecture Diagram"}
                </h3>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-primary-soft text-primary">
                  v{artifact?.version || 1}
                </span>
              </div>
              <span className="text-xs text-text-muted">
                Authoritative visual architecture model synchronized with Project State
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-success/10 text-success border border-success/20 flex items-center gap-1 font-mono">
              <CheckCircle2 className="w-3 h-3" />
              <span>Synced</span>
            </span>
          </div>
        </div>

        {/* Visual Pipeline Flow Nodes */}
        <div className="pt-3 border-t border-border space-y-2">
          <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted block">
            Architecture Sequence
          </span>
          <div className="flex flex-wrap items-center gap-2 p-3 bg-canvas rounded-lg border border-border">
            {(artifact?.extracted_nodes || ["User", "Requirements", "Decisions", "Services", "Data"]).map(
              (node, idx, arr) => (
                <React.Fragment key={idx}>
                  <div className="px-2.5 py-1 rounded bg-surface border border-border text-xs font-medium text-text-main flex items-center gap-1.5 shadow-2xs">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                    <span>{node}</span>
                  </div>
                  {idx < arr.length - 1 && (
                    <ArrowRight className="w-3 h-3 text-text-muted shrink-0" />
                  )}
                </React.Fragment>
              )
            )}
          </div>
        </div>

      </div>


      {/* Immutable visual revision history (current view stays clean) */}
      <VisualRevisionPanel
        revisions={revisions}
        currentRevisionNumber={currentRevisionNumber}
        compareFrom={compareFrom}
        diff={revisionDiff}
        busy={isRevisionBusy}
        onSelectCompare={handleSelectCompare}
        onRestore={handleRestoreRevision}
        onClearCompare={clearCompare}
      />

      {/* Historical Proposals */}
      {reviewedProposals.length > 0 && (
        <div className="space-y-3 pt-4 border-t border-border">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wider">
            Visual Change Audit History
          </h3>
          <div className="space-y-2">
            {reviewedProposals.map((prop) => (
              <div
                key={prop.id}
                className="p-3 bg-surface rounded-lg border border-border flex items-center justify-between text-xs"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 rounded font-mono font-semibold text-[10px] uppercase ${
                      prop.status === "approved"
                        ? "bg-success/10 text-success border border-success/20"
                        : "bg-danger/10 text-danger border border-danger/20"
                    }`}
                  >
                    {prop.status}
                  </span>
                  <span className="text-text-main font-medium">{prop.reason}</span>
                </div>
                <div className="text-text-muted font-mono text-[11px]" suppressHydrationWarning>
                  {prop.approved_at ? new Date(prop.approved_at).toLocaleString() : ""}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
