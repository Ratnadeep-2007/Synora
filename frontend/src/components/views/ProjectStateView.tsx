"use client";

import React, { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Node,
  Edge,
  MarkerType,
} from "@xyflow/react";
import {
  Layers,
  History,
  HelpCircle,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  RotateCcw,
} from "lucide-react";
import { ProjectState, ProjectStateVersion } from "@/lib/types";

interface ProjectStateViewProps {
  state: ProjectState | null;
  history: ProjectStateVersion[];
  onRollback: (version: number) => void;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
}

export function ProjectStateView({
  state,
  history,
  onRollback,
  onOpenEvidence,
}: ProjectStateViewProps) {
  const capabilities = state?.capabilities || [
    "Business Analysis",
    "Project Planning",
    "Functional Analysis",
    "Technical Architecture",
    "Frappe / ERP Analysis",
  ];

  // Generate React Flow nodes & edges for "How this state is formed"
  const { nodes, edges } = useMemo(() => {
    const versionNum = state?.current_version || 1;

    const stages = [
      {
        id: "evidence",
        step: "Stage 01",
        title: "Ingested Evidence",
        subtitle: "Meet • WhatsApp • Uploads",
        bg: "#FFFFFF",
        border: "1px solid #E7EAE5",
        badgeColor: "text-text-muted",
      },
      {
        id: "agent",
        step: "Stage 02",
        title: "Synora Agent",
        subtitle: "Unified Intelligence Layer",
        bg: "#ECFDF5",
        border: "2px solid #059669",
        badgeColor: "text-primary font-semibold",
      },
      {
        id: "guardrails",
        step: "Stage 03",
        title: "Deterministic Guardrails",
        subtitle: "Schema & Conflict Gates",
        bg: "#EFF6FF",
        border: "1px solid #93C5FD",
        badgeColor: "text-blue-600 font-semibold",
      },
      {
        id: "state",
        step: "Stage 04",
        title: "Authoritative State",
        subtitle: `PostgreSQL Record (v${versionNum})`,
        bg: "#FEF3C7",
        border: "2px solid #D97706",
        badgeColor: "text-amber-700 font-semibold",
      },
    ];

    const nodeItems: Node[] = stages.map((s, index) => ({
      id: `node-${s.id}`,
      position: { x: index * 200 + 20, y: 50 },
      data: {
        label: (
          <div className="text-center p-1.5">
            <div className={`text-[10px] uppercase font-mono tracking-wider ${s.badgeColor}`}>
              {s.step}
            </div>
            <div className="font-semibold text-xs text-text-main mt-0.5">
              {s.title}
            </div>
            <div className="text-[10px] text-text-muted mt-0.5 truncate">
              {s.subtitle}
            </div>
          </div>
        ),
      },
      style: {
        background: s.bg,
        border: s.border,
        borderRadius: "8px",
        width: 165,
        boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
      },
    }));

    const edgeItems: Edge[] = [];
    for (let i = 0; i < stages.length - 1; i++) {
      const from = stages[i].id;
      const to = stages[i + 1].id;
      edgeItems.push({
        id: `edge-${from}-${to}`,
        source: `node-${from}`,
        target: `node-${to}`,
        animated: true,
        style: { stroke: "#059669", strokeWidth: 1.5 },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: "#059669",
          width: 14,
          height: 14,
        },
      });
    }

    return { nodes: nodeItems, edges: edgeItems };
  }, [state?.current_version]);

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-text-main">
              Authoritative Project State
            </h1>
            <span className="text-xs font-mono font-semibold px-2.5 py-1 rounded bg-primary-soft text-primary border border-primary/20">
              v{state?.current_version || 1}
            </span>
          </div>
          <p className="text-sm text-text-muted mt-1">
            Single authoritative source of truth. Every transition is versioned and evidence-backed.
          </p>
        </div>

        <div className="text-xs font-mono text-text-muted bg-surface px-3 py-1.5 rounded-md border border-border">
          Last Updated:{" "}
          <strong className="text-text-main" suppressHydrationWarning>
            {state?.updated_at ? new Date(state.updated_at).toLocaleString() : "Initial"}
          </strong>
        </div>
      </div>

      {/* Vision */}
      <div className="p-6 rounded-xl bg-surface border border-border shadow-xs">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
          Project Vision & Direction
        </h3>
        <p className="text-base text-text-main font-serif italic leading-relaxed">
          "{state?.vision || "Build an evidence-backed software intelligence platform."}"
        </p>
      </div>

      {/* State Formation Flow Visualization */}
      <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-primary" />
            <div>
              <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
                How this state is formed
              </h3>
              <p className="text-[11px] text-text-muted mt-0.5">
                Evidence is reasoned by Synora Agent, verified through deterministic guardrails, and committed to PostgreSQL.
              </p>
            </div>
          </div>
          <span className="text-xs text-text-muted font-mono">
            4 Verified Stages
          </span>
        </div>

        {/* React Flow Canvas */}
        <div className="h-44 w-full bg-canvas/60 rounded-lg border border-border overflow-hidden relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            proOptions={{ hideAttribution: true }}
            nodesDraggable={false}
          >
            <Background gap={16} size={1} color="#E7EAE5" />
            <Controls showInteractive={false} position="bottom-right" />
          </ReactFlow>
        </div>
      </div>

      {/* Two Column: Requirements & Decisions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Authoritative Requirements */}
        <div className="p-6 rounded-xl bg-surface border border-border shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-border">
              <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
                Confirmed Requirements ({state?.requirements?.length || 0})
              </h3>
              <span className="text-xs text-text-muted">Evidence Provenance</span>
            </div>

            <div className="divide-y divide-border/60 mt-3 space-y-1">
              {!state?.requirements || state.requirements.length === 0 ? (
                <div className="py-6 text-center text-xs text-text-muted">
                  No explicit requirements persisted yet.
                </div>
              ) : (
                state.requirements.map((req, idx) => (
                  <div key={req.id || idx} className="py-3 flex items-start justify-between gap-4">
                    <div>
                      <div className="text-xs font-semibold text-text-main">{req.title}</div>
                      <div className="text-xs text-text-muted mt-0.5 leading-relaxed">{req.content}</div>
                    </div>
                    <button
                      onClick={() =>
                        onOpenEvidence(req.title, "Requirement", req.evidence_ids || [])
                      }
                      className="px-2 py-1 rounded text-[11px] font-semibold text-primary bg-primary-soft hover:bg-primary/20 border border-primary/20 shrink-0 transition-colors"
                    >
                      Why?
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Authoritative Decisions */}
        <div className="p-6 rounded-xl bg-surface border border-border shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-border">
              <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
                Authoritative Decisions ({state?.decisions?.length || 0})
              </h3>
              <span className="text-xs text-text-muted">Audit Records</span>
            </div>

            <div className="divide-y divide-border/60 mt-3 space-y-1">
              {!state?.decisions || state.decisions.length === 0 ? (
                <div className="py-6 text-center text-xs text-text-muted">
                  No confirmed decisions recorded yet.
                </div>
              ) : (
                state.decisions.map((dec, idx) => (
                  <div key={dec.id || idx} className="py-3 flex items-start justify-between gap-4">
                    <div>
                      <div className="text-xs font-semibold text-text-main">{dec.text}</div>
                      <div className="text-[11px] text-text-muted mt-0.5">
                        Approved by: <strong>{dec.approved_by || "Human Reviewer"}</strong> • {dec.date}
                      </div>
                    </div>
                    <button
                      onClick={() =>
                        onOpenEvidence(dec.text, "Decision", dec.evidence_ids || [])
                      }
                      className="px-2 py-1 rounded text-[11px] font-semibold text-primary bg-primary-soft hover:bg-primary/20 border border-primary/20 shrink-0 transition-colors"
                    >
                      Why?
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* State Version History & Rollback */}
      <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
              Immutable Version History & Rollback
            </h3>
          </div>
          <span className="text-xs text-text-muted">Tamper-Evident Audit Trail</span>
        </div>

        <div className="space-y-3">
          {history.length === 0 ? (
            <div className="py-4 text-center text-xs text-text-muted">
              Only initial version recorded.
            </div>
          ) : (
            history.map((ver) => {
              const isCurrent = ver.version_number === state?.current_version;
              return (
                <div
                  key={ver.id}
                  className="flex items-center justify-between p-3 rounded-lg border border-border bg-canvas/50 text-xs"
                >
                  <div className="flex items-center gap-3">
                    <span className="font-mono font-bold text-primary px-2 py-0.5 rounded bg-primary-soft border border-primary/20">
                      v{ver.version_number}
                    </span>
                    <div>
                      <div className="font-semibold text-text-main">{ver.reason}</div>
                      <div className="text-[11px] text-text-muted" suppressHydrationWarning>
                        Created by {ver.actor_id} • {new Date(ver.created_at).toLocaleString()}
                      </div>
                    </div>
                  </div>

                  <div>
                    {isCurrent ? (
                      <span className="text-[11px] font-semibold text-success px-2 py-1 rounded bg-success/10 border border-success/20">
                        Current Active
                      </span>
                    ) : (
                      <button
                        onClick={() => onRollback(ver.version_number)}
                        className="flex items-center gap-1 px-2.5 py-1 text-xs text-text-muted hover:text-text-main border border-border rounded bg-surface hover:bg-canvas transition-colors"
                      >
                        <RotateCcw className="w-3 h-3" />
                        <span>Rollback to v{ver.version_number}</span>
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
