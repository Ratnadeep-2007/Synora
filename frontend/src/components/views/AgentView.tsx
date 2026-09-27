"use client";

import React from "react";
import {
  Bot,
  FileText,
  CheckCircle2,
  AlertTriangle,
  Compass,
  Layers,
  Link2,
  GitCommit,
  PenTool,
  HelpCircle,
  ArrowRight,
  ShieldAlert,
} from "lucide-react";
import { ExcalidrawProposal } from "@/lib/types";

export interface AgentActivityItem {
  time: string;
  text: string;
}

interface CapabilityItem {
  id: string;
  name: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}

const CANONICAL_CAPABILITIES: CapabilityItem[] = [
  {
    id: "requirements",
    name: "Understand requirements",
    description: "Extract, normalize, and synthesize requirements from team discussions and transcripts.",
    icon: FileText,
  },
  {
    id: "decisions",
    name: "Analyze decisions",
    description: "Identify confirmed architectural choices and track decisions with evidence lineage.",
    icon: CheckCircle2,
  },
  {
    id: "conflicts",
    name: "Detect conflicts",
    description: "Continuously check for contradictions between new inputs and established architectural state.",
    icon: AlertTriangle,
  },
  {
    id: "context",
    name: "Analyze project context",
    description: "Maintain a unified model of the project vision, domain constraints, and assumptions.",
    icon: Compass,
  },
  {
    id: "architecture",
    name: "Reason about architecture",
    description: "Structure multi-tier topologies across client apps, gateways, services, and datastores.",
    icon: Layers,
  },
  {
    id: "evidence_lineage",
    name: "Link evidence to project state",
    description: "Trace every state mutation and diagram element directly to its original conversation source.",
    icon: Link2,
  },
  {
    id: "state_changes",
    name: "Suggest project-state changes",
    description: "Formulate candidate state modifications with structured rationale before applying them.",
    icon: GitCommit,
  },
  {
    id: "visual_workspace",
    name: "Propose visual workspace updates",
    description: "Compose living Excalidraw whiteboards with visual diffs for human review and approval.",
    icon: PenTool,
  },
  {
    id: "explainability",
    name: "Explain why a change was proposed",
    description: "Provide comprehensive rationale, context citations, and risk assessments for each change.",
    icon: HelpCircle,
  },
];

interface AgentViewProps {
  projectName?: string;
  stateVersion?: number;
  workspaceStatus?: string;
  activity?: AgentActivityItem[];
  pendingProposal?: ExcalidrawProposal | null;
  onReviewProposal?: () => void;
  onViewEvidence?: () => void;
  // Legacy optional props for backwards compatibility
  excalidrawSyncLabel?: string;
  capabilities?: any[];
  onTriggerAgent?: (agentId: string, taskDesc?: string) => Promise<void>;
  onInspectAgentRuns?: (agentId: string) => Promise<any[]>;
  onOpenRunDetail?: (run: any) => void;
}

export function AgentView({
  projectName = "Synora",
  stateVersion = 1,
  workspaceStatus,
  activity = [],
  pendingProposal = null,
  onReviewProposal,
  onViewEvidence,
  excalidrawSyncLabel,
}: AgentViewProps) {
  const currentWorkspaceStatus =
    workspaceStatus || excalidrawSyncLabel || (pendingProposal ? "Pending review" : "Synchronized");
  const isPendingReview =
    currentWorkspaceStatus.toLowerCase().includes("pending") || Boolean(pendingProposal);

  return (
    <div className="space-y-6">
      {/* 1. TOP SECTION: Single Shared Synora Agent */}
      <section className="p-6 rounded-xl bg-surface border border-border shadow-xs">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-lg bg-primary text-white flex items-center justify-center shrink-0">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold tracking-tight text-text-main">Synora Agent</h1>
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-700 border border-emerald-500/20 font-mono">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Active
                </span>
              </div>
              <p className="text-xs text-text-muted mt-1">
                One shared intelligence layer working inside this project context.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <div className="px-3 py-1.5 rounded-lg bg-canvas border border-border flex items-center gap-1.5">
              <span className="text-text-muted">Project:</span>
              <strong className="text-text-main font-semibold">{projectName}</strong>
            </div>
            <div className="px-3 py-1.5 rounded-lg bg-canvas border border-border flex items-center gap-1.5">
              <span className="text-text-muted">State:</span>
              <strong className="text-primary font-mono font-semibold">v{stateVersion}</strong>
            </div>
            <div className="px-3 py-1.5 rounded-lg bg-canvas border border-border flex items-center gap-1.5">
              <span className="text-text-muted">Workspace:</span>
              <strong
                className={`font-semibold ${
                  isPendingReview ? "text-amber-600" : "text-emerald-700"
                }`}
              >
                {currentWorkspaceStatus}
              </strong>
            </div>
          </div>
        </div>
      </section>

      {/* 2. WHAT SYNORA CAN DO: Human-facing Capabilities */}
      <section className="space-y-3">
        <div>
          <p className="text-[11px] uppercase tracking-wider font-semibold text-primary">Capabilities</p>
          <h2 className="text-sm font-semibold text-text-main mt-0.5">What Synora can do</h2>
          <p className="text-xs text-text-muted mt-0.5">
            Core capabilities of the shared Synora Agent operating within this project.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {CANONICAL_CAPABILITIES.map((cap) => {
            const Icon = cap.icon;
            return (
              <div
                key={cap.id}
                className="p-4 rounded-xl bg-surface border border-border/80 flex flex-col justify-between gap-2.5 transition-colors hover:border-border"
              >
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-lg bg-canvas border border-border flex items-center justify-center shrink-0 mt-0.5 text-primary">
                    <Icon className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-xs font-semibold text-text-main">{cap.name}</h3>
                    <p className="text-[11px] text-text-muted mt-1 leading-relaxed">
                      {cap.description}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 3. RECENT ACTIVITY: Clear human explanation of what Synora did */}
      <section className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-border/80">
          <div>
            <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
              Recent activity
            </h3>
            <p className="text-xs text-text-muted mt-0.5">
              Actions performed by Synora inside this project context.
            </p>
          </div>
          <span className="text-[11px] text-text-muted font-mono">
            {activity.length} event{activity.length === 1 ? "" : "s"}
          </span>
        </div>

        {activity.length === 0 ? (
          <div className="py-6 text-center text-xs text-text-muted">
            No recent activity recorded yet in this project.
          </div>
        ) : (
          <div className="divide-y divide-border/60">
            {activity.map((item, idx) => (
              <div key={idx} className="py-2.5 first:pt-0 last:pb-0 flex items-start gap-4 text-xs">
                <span className="font-mono text-text-muted shrink-0 mt-0.5 text-[11px]">
                  {item.time}
                </span>
                <p className="text-text-main flex-1 leading-relaxed">{item.text}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 4. PROPOSALS / HUMAN CONTROL: Trust surface for consequential work */}
      {isPendingReview ? (
        <section className="p-6 rounded-xl bg-surface border border-amber-500/30 shadow-xs space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-700 border border-amber-500/20 uppercase tracking-wide inline-flex items-center gap-1 font-mono">
                  <ShieldAlert className="w-3 h-3 text-amber-600" />
                  Needs review
                </span>
                <h3 className="text-sm font-semibold text-text-main">
                  Architecture change proposed
                </h3>
              </div>
              <p className="text-xs text-text-muted leading-relaxed">
                Synora proposed an architecture change based on recent project evidence. Consequential
                workspace updates require human review and approval before being applied.
              </p>
              {pendingProposal?.reason && (
                <div className="mt-2 p-2.5 rounded-lg bg-canvas border border-border text-xs text-text-main">
                  <span className="text-text-muted text-[11px] block font-semibold mb-0.5">
                    Proposal Rationale:
                  </span>
                  {pendingProposal.reason}
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {onReviewProposal && (
                <button
                  onClick={onReviewProposal}
                  className="px-3.5 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-md shadow-xs transition-colors flex items-center gap-1.5"
                >
                  <span>Review proposal</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              )}
              {onViewEvidence && (
                <button
                  onClick={onViewEvidence}
                  className="px-3 py-1.5 text-xs font-medium text-text-main bg-canvas hover:bg-surface border border-border rounded-md transition-colors"
                >
                  View evidence
                </button>
              )}
            </div>
          </div>
        </section>
      ) : (
        <section className="p-5 rounded-xl bg-surface border border-border shadow-xs flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-600 flex items-center justify-center shrink-0">
              <CheckCircle2 className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text-main">All changes up to date</h3>
              <p className="text-xs text-text-muted mt-0.5">
                No pending architecture proposals require human review at this time.
              </p>
            </div>
          </div>
          {onViewEvidence && (
            <button
              onClick={onViewEvidence}
              className="px-3 py-1.5 text-xs font-medium text-text-main bg-canvas hover:bg-surface border border-border rounded-md transition-colors self-start sm:self-auto"
            >
              View evidence
            </button>
          )}
        </section>
      )}
    </div>
  );
}
