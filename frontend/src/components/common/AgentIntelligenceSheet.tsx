"use client";

import React, { useState } from "react";
import {
  BrainCircuit,
  CheckCircle2,
  Clock,
  Compass,
  Layers,
  Play,
  RotateCcw,
  Shield,
  Sparkles,
  Terminal,
  X,
  Zap,
} from "lucide-react";
import { Project, ProjectState } from "@/lib/types";
import { api } from "@/lib/api";

interface AgentIntelligenceSheetProps {
  isOpen: boolean;
  onClose: () => void;
  // Preferred orchestration contract (page.tsx): ids plus a dispatch hook.
  projectId?: string | null;
  projectVersion?: number;
  onDispatchCapability?: (
    capabilityId: string,
    taskDesc?: string
  ) => Promise<{ message?: string } | any>;
  // Direct data contract (also accepted): resolved objects plus refresh.
  project?: Project | null;
  state?: ProjectState | null;
  onRefreshProject?: () => void;
}

export function AgentIntelligenceSheet({
  isOpen,
  onClose,
  projectId,
  projectVersion,
  onDispatchCapability,
  project,
  state,
  onRefreshProject,
}: AgentIntelligenceSheetProps) {
  const [isDispatching, setIsDispatching] = useState<string | null>(null);
  const [dispatchResult, setDispatchResult] = useState<{
    capability: string;
    message: string;
    time: string;
  } | null>(null);

  if (!isOpen) return null;

  const resolvedProjectId = projectId ?? project?.id ?? null;
  const version = projectVersion ?? state?.current_version ?? 1;
  const projectName = project?.name || "workspace";

  const handleDispatch = async (capabilityId: string, label: string) => {
    if (!resolvedProjectId && !project?.id) return;
    setIsDispatching(capabilityId);
    setDispatchResult(null);
    try {
      const res = onDispatchCapability
        ? await onDispatchCapability(
            capabilityId,
            `Triggered from Synora Intelligence Surface: ${label}`
          )
        : await api.dispatchProjectAgentCapability(
            (resolvedProjectId || project?.id) as string,
            capabilityId,
            `Triggered from Synora Intelligence Surface: ${label}`
          );
      setDispatchResult({
        capability: label,
        message: (res as any)?.message || `Capability ${label} executed successfully.`,
        time: new Date().toLocaleTimeString(),
      });
      onRefreshProject?.();
    } catch (err: any) {
      setDispatchResult({
        capability: label,
        message: err?.message || "Execution encountered an error.",
        time: new Date().toLocaleTimeString(),
      });
    } finally {
      setIsDispatching(null);
    }
  };

  const capabilities = [
    {
      id: "visual_architecture",
      name: "Visual Topology Synchronization",
      desc: "Aligns Living Project Atlas Excalidraw canvas with current requirements and decisions.",
      icon: Layers,
    },
    {
      id: "conflict_detector",
      name: "Semantic Conflict Scan",
      desc: "Cross-checks recent meeting decisions against architectural boundaries and requirements.",
      icon: Shield,
    },
    {
      id: "knowledge_extractor",
      name: "Candidate Knowledge Synthesis",
      desc: "Analyzes unprocessed speech and chat evidence to propose new project facts.",
      icon: Sparkles,
    },
    {
      id: "state_refiner",
      name: "State Model Refinement",
      desc: "Updates authoritative project vision, constraints, and open ambiguities.",
      icon: Compass,
    },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-[var(--scrim)] backdrop-blur-sm animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl h-full border-l border-border bg-surface shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right duration-250"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border p-6 bg-surface-soft/80">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-soft text-primary border border-primary/25">
              <BrainCircuit className="h-5 w-5 animate-pulse-live" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold tracking-tight text-text-main">
                  Synora Intelligence Layer
                </h2>
                <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 font-mono text-[10px] font-semibold text-primary border border-primary/20">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" /> ACTIVE
                </span>
              </div>
              <p className="text-[11px] text-text-muted">
                Observing {projectName} • State v{version}
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-text-muted hover:bg-surface-muted hover:text-text-main transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Autonomous Status Synopsis */}
          <div className="rounded-xl border border-primary/20 bg-primary-soft/30 p-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-primary">
              <Zap className="h-3.5 w-3.5" />
              Continuous Cognitive Observation
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-text-main font-sans">
              Synora continuously maps Google Meet transcripts and WhatsApp communications into this
              project&apos;s memory boundary. Changes are deterministically versioned into State v{version} and
              mirrored in the Living Atlas.
            </p>
          </div>

          {/* Cognitive Focus & Memory Matrix */}
          <div className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
              Cognitive Focus & Memory Metrics
            </h3>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl border border-border bg-surface-soft p-3">
                <div className="text-[10px] text-text-muted">Requirements</div>
                <div className="mt-1 text-lg font-semibold text-text-main">
                  {state?.requirements?.length ?? 0}
                </div>
              </div>
              <div className="rounded-xl border border-border bg-surface-soft p-3">
                <div className="text-[10px] text-text-muted">Decisions</div>
                <div className="mt-1 text-lg font-semibold text-text-main">
                  {state?.decisions?.length ?? 0}
                </div>
              </div>
              <div className="rounded-xl border border-border bg-surface-soft p-3">
                <div className="text-[10px] text-text-muted">Components</div>
                <div className="mt-1 text-lg font-semibold text-text-main">
                  {state?.architecture?.length ?? 0}
                </div>
              </div>
              <div className="rounded-xl border border-border bg-surface-soft p-3">
                <div className="text-[10px] text-text-muted">Ambiguities</div>
                <div className="mt-1 text-lg font-semibold text-text-main">
                  {state?.open_questions?.length ?? 0}
                </div>
              </div>
            </div>
          </div>

          {/* Specialist Capabilities Dispatch */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                Specialist Capabilities
              </h3>
              <span className="text-[10px] text-text-dim">Deterministic Execution</span>
            </div>

            <div className="space-y-2.5">
              {capabilities.map((cap) => {
                const Icon = cap.icon;
                const isRunning = isDispatching === cap.id;
                return (
                  <div
                    key={cap.id}
                    className="flex items-center justify-between gap-4 rounded-xl border border-border bg-surface-soft/60 p-3.5 transition-colors hover:border-border-active"
                  >
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-primary mt-0.5">
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-xs font-semibold text-text-main">{cap.name}</div>
                        <p className="mt-0.5 text-[11px] text-text-muted leading-relaxed line-clamp-2">
                          {cap.desc}
                        </p>
                      </div>
                    </div>

                    <button
                      onClick={() => handleDispatch(cap.id, cap.name)}
                      disabled={Boolean(isDispatching)}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs font-semibold text-text-main hover:bg-surface-muted hover:border-primary/40 disabled:opacity-40 transition-colors"
                    >
                      {isRunning ? (
                        <>
                          <RotateCcw className="h-3 w-3 animate-spin text-primary" />
                          <span>Dispatching…</span>
                        </>
                      ) : (
                        <>
                          <Play className="h-3 w-3 text-primary" />
                          <span>Run</span>
                        </>
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Dispatch Outcome Terminal */}
          {dispatchResult && (
            <div className="rounded-xl border border-primary/30 bg-surface-muted p-4 space-y-2 animate-in fade-in duration-200">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5 font-semibold text-primary">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {dispatchResult.capability}
                </span>
                <span className="font-mono text-[10px] text-text-dim">{dispatchResult.time}</span>
              </div>
              <p className="text-xs text-text-muted font-mono leading-relaxed bg-surface/60 p-2.5 rounded border border-border">
                {dispatchResult.message}
              </p>
            </div>
          )}

          {/* Vision Anchor */}
          <div className="rounded-xl border border-border bg-surface-soft p-4 space-y-1.5">
            <div className="text-[10px] font-bold uppercase tracking-wider text-text-dim">
              Current Project Anchor
            </div>
            <p className="text-xs text-text-main leading-relaxed italic">
              &quot;{state?.vision || "No vision anchor initialized yet."}&quot;
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-border bg-surface-soft/80 px-6 py-3 text-[11px] text-text-dim flex items-center justify-between">
          <span className="flex items-center gap-1.5">
            <Terminal className="h-3.5 w-3.5 text-primary" /> Synora Agent Subsystem
          </span>
          <span className="font-mono text-[10px] text-text-muted">v2.0 • Active</span>
        </div>
      </div>
    </div>
  );
}
