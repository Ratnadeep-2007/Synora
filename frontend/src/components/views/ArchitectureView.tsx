"use client";

import React, { useRef, useState } from "react";
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
  Upload,
  Download,
  ExternalLink,
  Plus,
} from "lucide-react";
import { ExcalidrawArtifact, ExcalidrawProposal } from "@/lib/types";

interface VisualRevision {
  id: string;
  artifact_id: string;
  project_id: string;
  tenant_id: string;
  revision_number: number;
  parent_revision_id?: string | null;
  derived_from_state_version?: number | null;
  snapshot: { elements: any[]; app_state?: any; extracted_nodes?: string[] };
  change_summary: Record<string, any>;
  source_event_ids: string[];
  proposal_id?: string | null;
  actor_id: string;
  created_at: string;
}

interface VisualRevisionDiff {
  project_id: string;
  artifact_id: string;
  from_revision: number;
  to_revision: number;
  added_elements: any[];
  removed_elements: any[];
  changed_elements: any[];
  unchanged_count: number;
  overlay_elements?: any[];
  added_count?: number;
  removed_count?: number;
  changed_count?: number;
}
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
  revisions?: VisualRevision[];
  onLoadRevision?: (revision: VisualRevision) => Promise<void>;
  onCompareRevisions?: (fromRevision: number, toRevision: number) => Promise<VisualRevisionDiff>;
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
  revisions = [],
  onLoadRevision,
  onCompareRevisions,
}: ArchitectureViewProps) {
  const [isAiGenerating, setIsAiGenerating] = useState(false);
  const [isSyncingWorkspace, setIsSyncingWorkspace] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [processingProposalId, setProcessingProposalId] = useState<string | null>(null);
  const [selectedRevision, setSelectedRevision] = useState<number | null>(null);
  const [revisionDiff, setRevisionDiff] = useState<VisualRevisionDiff | null>(null);
  const [isComparing, setIsComparing] = useState(false);
  const [previewRevision, setPreviewRevision] = useState<VisualRevision | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setIsImporting(true);
      const text = await file.text();
      const parsed = JSON.parse(text);

      const elements = Array.isArray(parsed) ? parsed : parsed.elements || [];
      const appState = parsed.appState || { viewBackgroundColor: "#ffffff" };
      const name = file.name.replace(/\.[^/.]+$/, "") || "Uploaded Architecture Scene";

      await onIngestScene({
        name,
        elements,
        app_state: appState,
      });
    } catch (err: any) {
      alert(`Failed to parse or ingest Excalidraw file: ${err.message}`);
    } finally {
      setIsImporting(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
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

  const handleGenerate = async () => {
    try {
      setIsGenerating(true);
      await onGenerateProposal(currentStateVersion);
    } finally {
      setIsGenerating(false);
    }
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

        <div className="flex items-center gap-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".excalidraw,.json"
            className="hidden"
          />

          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isImporting}
            className="px-3 py-1.5 text-xs font-medium text-text-main bg-surface hover:bg-surface/80 border border-border rounded-lg flex items-center gap-1.5 transition-colors shadow-2xs disabled:opacity-50"
            title="Import an .excalidraw or JSON file"
          >
            <Upload className="w-3.5 h-3.5 text-text-muted" />
            <span>{isImporting ? "Importing..." : "Import"}</span>
          </button>

          {artifact && (
            <button
              onClick={handleExportExcalidraw}
              className="px-3 py-1.5 text-xs font-medium text-text-main bg-surface hover:bg-surface/80 border border-border rounded-lg flex items-center gap-1.5 transition-colors shadow-2xs"
              title="Download scene as .excalidraw file"
            >
              <Download className="w-3.5 h-3.5 text-text-muted" />
              <span>Export</span>
            </button>
          )}

          {onSyncLivingWorkspace && (
            <button
              onClick={async () => {
                try {
                  setIsSyncingWorkspace(true);
                  await onSyncLivingWorkspace();
                } finally {
                  setIsSyncingWorkspace(false);
                }
              }}
              disabled={isSyncingWorkspace}
              className="px-3 py-1.5 text-xs font-medium text-primary bg-primary-soft hover:bg-primary/20 border border-primary/20 rounded-lg flex items-center gap-1.5 transition-colors shadow-2xs disabled:opacity-50"
              title="Update visual diagram with the latest project decisions and state"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isSyncingWorkspace ? "animate-spin" : ""}`} />
              <span>{isSyncingWorkspace ? "Updating..." : "Update from State"}</span>
            </button>
          )}

          <button
            onClick={handleGenerate}
            disabled={isGenerating}
            className="px-3 py-1.5 text-xs font-medium text-text-main bg-surface hover:bg-surface/80 border border-border rounded-lg flex items-center gap-1.5 transition-colors shadow-2xs disabled:opacity-50"
            title="Generate proposed diagram changes based on the latest project state"
          >
            <Sparkles className="w-3.5 h-3.5 text-text-muted" />
            <span>{isGenerating ? "Drafting..." : "Propose Changes"}</span>
          </button>

          {onAiGenerateVisuals && (
            <button
              onClick={async () => {
                try {
                  setIsAiGenerating(true);
                  await onAiGenerateVisuals(undefined, false);
                } finally {
                  setIsAiGenerating(false);
                }
              }}
              disabled={isAiGenerating}
              className="px-3.5 py-1.5 text-xs font-medium text-primary bg-primary-soft hover:bg-primary/20 border border-primary/20 rounded-lg flex items-center gap-1.5 transition-colors shadow-2xs disabled:opacity-50"
              title="Create a reviewable visual architecture proposal"
            >
              <Sparkles className={`w-3.5 h-3.5 ${isAiGenerating ? "animate-spin" : ""}`} />
              <span>{isAiGenerating ? "Designing Scene..." : "Generate visual proposal"}</span>
            </button>
          )}
        </div>
      </div>

      {/* Synchronization Bar */}
      <ExcalidrawSyncBar
        status={isSyncingWorkspace ? "updating" : syncStatus}
        lastSyncAt={lastSyncAt || artifact?.updated_at}
        onRetry={onRetrySync}
      />

      {/* Primary Human-Facing Agent Output: Embedded Interactive Excalidraw Canvas */}
      <ExcalidrawCanvas
        projectName={artifact?.name || "System Architecture"}
        version={artifact?.version || 1}
        initialElements={artifact?.elements || []}
        initialAppState={artifact?.app_state}
        isSyncing={isSyncingWorkspace}
        onSyncAgentOutput={onSyncLivingWorkspace}
        onSaveCanvas={onIngestScene}
        onExportJson={handleExportExcalidraw}
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


      {/* Immutable visual revision history */}
      {revisions.length > 0 && (
        <div className="p-5 rounded-xl bg-surface border border-border shadow-xs space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-text-main">Visual history</h2>
              <p className="text-xs text-text-muted mt-0.5">
                The canvas always shows the latest revision. Older revisions remain available for inspection and comparison.
              </p>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-primary-soft text-primary border border-primary/20">
              {revisions.length} revisions
            </span>
          </div>

          <div className="space-y-2">
            {revisions.slice(0, 8).map((revision) => {
              const isCurrent = revision.revision_number === artifact?.version;
              return (
                <div key={revision.id} className="flex flex-col md:flex-row md:items-center justify-between gap-3 p-3 rounded-lg bg-canvas border border-border">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono font-semibold text-text-main">v{revision.revision_number}</span>
                      {isCurrent && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-success/10 text-success border border-success/20">Latest</span>
                      )}
                      {revision.derived_from_state_version && (
                        <span className="text-[10px] text-text-muted">State v{revision.derived_from_state_version}</span>
                      )}
                    </div>
                    <div className="text-xs text-text-muted mt-1">
                      {revision.change_summary?.action || "Visual revision"} · {revision.actor_id} ·{" "}
                      {new Date(revision.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {onLoadRevision && (
                      <button
                        className="px-2.5 py-1.5 text-xs font-medium bg-surface border border-border rounded-md hover:bg-surface/80"
                        onClick={() => setPreviewRevision(revision)}
                      >
                        View
                      </button>
                    )}
                    {onCompareRevisions && !isCurrent && (
                      <button
                        className="px-2.5 py-1.5 text-xs font-medium text-primary bg-primary-soft border border-primary/20 rounded-md hover:bg-primary/20 disabled:opacity-50"
                        disabled={isComparing}
                        onClick={async () => {
                          try {
                            setIsComparing(true);
                            setSelectedRevision(revision.revision_number);
                            setRevisionDiff(await onCompareRevisions(revision.revision_number, artifact?.version || 1));
                          } finally {
                            setIsComparing(false);
                          }
                        }}
                      >
                        Compare with latest
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {revisionDiff && (
            <div className="p-4 rounded-lg border border-border bg-canvas">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold text-text-main">
                  v{revisionDiff.from_revision} → v{revisionDiff.to_revision}
                </span>
                <button
                  className="text-xs text-text-muted hover:text-text-main"
                  onClick={() => setRevisionDiff(null)}
                >
                  Close
                </button>
              </div>
              <div className="grid grid-cols-3 gap-2 mt-3 text-center">
                <div className="p-2 rounded bg-surface border border-border">
                  <div className="text-sm font-semibold text-success">{revisionDiff.added_count ?? revisionDiff.added_elements.length}</div>
                  <div className="text-[10px] text-text-muted">Added</div>
                </div>
                <div className="p-2 rounded bg-surface border border-border">
                  <div className="text-sm font-semibold text-danger">{revisionDiff.removed_count ?? revisionDiff.removed_elements.length}</div>
                  <div className="text-[10px] text-text-muted">Removed</div>
                </div>
                <div className="p-2 rounded bg-surface border border-border">
                  <div className="text-sm font-semibold text-primary">{revisionDiff.changed_count ?? revisionDiff.changed_elements.length}</div>
                  <div className="text-[10px] text-text-muted">Changed</div>
                </div>
              </div>
              <div className="mt-3 p-3 rounded-lg bg-surface border border-border text-xs text-text-muted">
                Comparison is non-destructive. The main canvas stays on the latest revision; history is shown only for comparison.
                {revisionDiff.overlay_elements?.length
                  ? ` ${revisionDiff.overlay_elements.length} overlay elements are prepared for visual comparison.`
                  : ""}
              </div>
            </div>
          )}
        </div>
      )}

      {previewRevision && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-6">
          <div className="w-full max-w-6xl h-[86vh] bg-surface border border-border rounded-xl shadow-xl flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <div>
                <div className="text-sm font-semibold text-text-main">
                  Historical revision v{previewRevision.revision_number}
                </div>
                <div className="text-xs text-text-muted">
                  Read-only preview. The live canvas remains on the latest revision.
                </div>
              </div>
              <button
                className="px-3 py-1.5 text-xs font-medium border border-border rounded-md hover:bg-canvas"
                onClick={() => setPreviewRevision(null)}
              >
                Close
              </button>
            </div>
            <div className="flex-1 min-h-0">
              <ExcalidrawCanvas
                projectName={`${artifact?.name || "Architecture"} · v${previewRevision.revision_number}`}
                version={previewRevision.revision_number}
                initialElements={previewRevision.snapshot?.elements || []}
                initialAppState={previewRevision.snapshot?.app_state}
              />
            </div>
          </div>
        </div>
      )}

      {/* Pending Diagram Proposals */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-text-main flex items-center gap-2">
              <GitBranch className="w-4 h-4 text-warning" />
              <span>Pending Diagram Proposals</span>
            </h2>
            <p className="text-xs text-text-muted mt-0.5">
              Review and approve agent-suggested diagram updates before they are saved to your project.
            </p>
          </div>
          <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-medium bg-warning/10 text-warning border border-warning/20">
            {pendingProposals.length} Pending
          </span>
        </div>

        {pendingProposals.length === 0 ? (
          <div className="p-8 rounded-xl bg-surface/50 border border-dashed border-border text-center space-y-2">
            <CheckCircle2 className="w-8 h-8 text-success mx-auto" />
            <p className="text-sm font-medium text-text-main">
              Visual Architecture is fully synchronized with Project State v{currentStateVersion}
            </p>
            <p className="text-xs text-text-muted">
              No pending diagram modification proposals requiring human approval.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {pendingProposals.map((prop) => {
              const isProcessing = processingProposalId === prop.id;
              const diff = prop.diff_preview;

              return (
                <div
                  key={prop.id}
                  className="p-6 rounded-xl bg-surface border-2 border-warning/40 shadow-xs space-y-5"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase font-bold bg-warning/20 text-warning border border-warning/30">
                          Pending Human Approval
                        </span>
                        <span className="text-xs text-text-muted font-mono">
                          Derived from State v{prop.derived_from_state_version}
                        </span>
                      </div>
                      <h4 className="text-base font-semibold text-text-main mt-1">
                        {prop.reason}
                      </h4>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => handleReview(prop.id, "reject")}
                        disabled={isProcessing}
                        className="px-3 py-1.5 text-xs font-semibold text-danger bg-danger/10 hover:bg-danger/20 border border-danger/20 rounded-md flex items-center gap-1 transition-colors disabled:opacity-50"
                      >
                        <XCircle className="w-3.5 h-3.5" />
                        <span>Reject</span>
                      </button>
                      <button
                        onClick={() => handleReview(prop.id, "approve")}
                        disabled={isProcessing}
                        className="px-3.5 py-1.5 text-xs font-semibold text-white bg-success hover:bg-success/90 rounded-md flex items-center gap-1 transition-colors shadow-xs disabled:opacity-50"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>{isProcessing ? "Applying..." : "Approve Diagram Update"}</span>
                      </button>
                    </div>
                  </div>

                  {/* Structured Diff Preview */}
                  <div className="p-4 bg-canvas rounded-lg border border-border space-y-4">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted block">
                      Structured Visual Diff Preview
                    </span>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Nodes Added */}
                      <div className="space-y-1.5">
                        <span className="text-xs font-medium text-text-muted">Nodes Added (+):</span>
                        <div className="flex flex-wrap gap-1.5">
                          {diff.nodes_added.length > 0 ? (
                            diff.nodes_added.map((node, i) => (
                              <span
                                key={i}
                                className="px-2.5 py-1 rounded text-xs font-semibold bg-success/15 text-success border border-success/30 font-mono"
                              >
                                + {node}
                              </span>
                            ))
                          ) : (
                            <span className="text-xs text-text-muted italic">None</span>
                          )}
                        </div>
                      </div>

                      {/* Nodes Removed */}
                      <div className="space-y-1.5">
                        <span className="text-xs font-medium text-text-muted">Nodes Removed (-):</span>
                        <div className="flex flex-wrap gap-1.5">
                          {diff.nodes_removed.length > 0 ? (
                            diff.nodes_removed.map((node, i) => (
                              <span
                                key={i}
                                className="px-2.5 py-1 rounded text-xs font-semibold bg-danger/15 text-danger border border-danger/30 font-mono"
                              >
                                - {node}
                              </span>
                            ))
                          ) : (
                            <span className="text-xs text-text-muted italic">None</span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Proposed Sequence Flow */}
                    <div className="space-y-1.5 pt-2 border-t border-border">
                      <span className="text-xs font-medium text-text-muted">Proposed Flow After Approval:</span>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {diff.nodes_after.map((node, i, arr) => (
                          <React.Fragment key={i}>
                            <span
                              className={`px-2.5 py-1 rounded text-xs font-medium border ${
                                diff.nodes_added.includes(node)
                                  ? "bg-success/15 text-success border-success/30 font-bold"
                                  : "bg-surface text-text-main border-border"
                              }`}
                            >
                              {node}
                            </span>
                            {i < arr.length - 1 && (
                              <ArrowRight className="w-3 h-3 text-text-muted shrink-0" />
                            )}
                          </React.Fragment>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Historical Proposals */}
      {reviewedProposals.length > 0 && (
        <div className="space-y-3 pt-4 border-t border-border">
          <h3 className="text-sm font-semibold text-text-muted uppercase tracking-wider">
            Proposal Audit History
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
