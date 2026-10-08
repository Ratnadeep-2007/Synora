"use client";

import React, { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Database,
  FileText,
  Layers,
  MessageCircle,
  PenTool,
  ShieldAlert,
  Sparkles,
  Video,
  X,
  Zap,
} from "lucide-react";

interface PipelineStorytellingModalProps {
  isOpen: boolean;
  onClose: () => void;
  onExploreAtlas?: () => void;
}

const PIPELINE_STEPS = [
  {
    step: 1,
    title: "Raw Information Streams",
    category: "Sources Ingestion",
    icon: Video,
    subtitle: "Google Meet audio & WhatsApp Baileys group sockets feed Synora continuously.",
    description:
      "Instead of forcing engineers and managers to manually log notes in Jira or Notion, Synora connects directly to the conversation streams where decisions actually happen.",
    signals: [
      { label: "Google Meet", val: "Continuous recording & speech-to-text", icon: Video },
      { label: "WhatsApp", val: "Live Baileys socket & group chats", icon: MessageCircle },
    ],
    sampleSnippet:
      '"For the multi-tenant database, let\'s isolate every tenant into a separate schema rather than a shared database for SOC2 compliance."',
  },
  {
    step: 2,
    title: "Verbatim Evidence Extraction",
    category: "Deterministic Provenance",
    icon: FileText,
    subtitle: "Speech and chat fragments are converted into immutable evidence citations.",
    description:
      "Every project claim in Synora traces back to verbatim evidence. When a decision is recorded, you can always ask 'Why does Synora think this?' and view the exact sentence spoken.",
    signals: [
      { label: "Actor Attribution", val: "Verified speaker & timestamp", icon: CheckCircle2 },
      { label: "Confidence Rating", val: "High confidence extracted fact", icon: Sparkles },
    ],
    sampleSnippet:
      "Evidence #ev_8f3a • Speaker: Lead Architect • Google Meet 'Architecture Sync' • 10:42 AM",
  },
  {
    step: 3,
    title: "Knowledge & Conflict Synthesis",
    category: "Intelligence Engine",
    icon: ShieldAlert,
    subtitle: "Synora cross-checks proposed changes against existing architecture boundaries.",
    description:
      "If someone in a meeting proposes an offline-first mobile sync model that contradicts the cloud serverless schema, Synora surfaces a semantic conflict before code is written.",
    signals: [
      { label: "Conflict Detector", val: "Cross-checks constraints & assumptions", icon: ShieldAlert },
      { label: "Candidate Clustering", val: "Identifies requirements & decisions", icon: Zap },
    ],
    sampleSnippet:
      "Conflict Detected: Proposed mobile SQLite cache contradicts centralized tenant isolation rule.",
  },
  {
    step: 4,
    title: "Project State Versioning",
    category: "Authoritative Brain",
    icon: Database,
    subtitle: "The project's vision, decisions, requirements, and topology advance to vN.",
    description:
      "Synora updates the authoritative Project State. Every version is an immutable snapshot that can be scrubbed or rolled back at any time with complete historical provenance.",
    signals: [
      { label: "Version Increment", val: "State v16 snapshot committed", icon: Layers },
      { label: "Memory Isolation", val: "Strict project boundaries enforced", icon: Database },
    ],
    sampleSnippet:
      "State v16 committed: Added Requirement #req_tenant_schema and Decision #dec_soc2_isolation.",
  },
  {
    step: 5,
    title: "Living Project Atlas",
    category: "Visual Architecture",
    icon: PenTool,
    subtitle: "The infinite Excalidraw workspace evolves with zero manual drawing required.",
    description:
      "Synora automatically paints the architecture topology, component connections, and project memory directly onto the database-backed Excalidraw canvas.",
    signals: [
      { label: "Excalidraw Engine", val: "AI-maintained vector diagram", icon: PenTool },
      { label: "Autonomous Sync", val: "Mirrors State v16 automatically", icon: BrainCircuit },
    ],
    sampleSnippet:
      "Atlas updated: Created PostgreSQL tenant isolation cluster with 3 connected service nodes.",
  },
];

export function PipelineStorytellingModal({
  isOpen,
  onClose,
  onExploreAtlas,
}: PipelineStorytellingModalProps) {
  const [currentStepIndex, setCurrentStepIndex] = useState(0);

  if (!isOpen) return null;

  const currentStep = PIPELINE_STEPS[currentStepIndex];
  const Icon = currentStep.icon;

  const handleNext = () => {
    if (currentStepIndex < PIPELINE_STEPS.length - 1) {
      setCurrentStepIndex(currentStepIndex + 1);
    } else {
      onClose();
      onExploreAtlas?.();
    }
  };

  const handlePrev = () => {
    if (currentStepIndex > 0) {
      setCurrentStepIndex(currentStepIndex - 1);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[var(--scrim)] backdrop-blur-md animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl animate-in slide-in-from-bottom duration-250 flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4 bg-surface-soft/80">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-soft text-primary">
              <Zap className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold tracking-tight text-text-main">
                How Synora Works
              </h2>
              <p className="text-[11px] text-text-muted">
                The Project Intelligence Pipeline from conversation to living canvas
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-text-muted hover:bg-surface-muted hover:text-text-main transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Pipeline Stepper Indicators */}
        <div className="grid grid-cols-5 border-b border-border bg-surface-muted/40">
          {PIPELINE_STEPS.map((s, idx) => {
            const isActive = idx === currentStepIndex;
            const isCompleted = idx < currentStepIndex;
            return (
              <button
                key={s.step}
                onClick={() => setCurrentStepIndex(idx)}
                className={`py-3 px-2 text-center text-xs font-medium border-b-2 transition-all ${
                  isActive
                    ? "border-primary text-text-main bg-primary-soft/40 font-semibold"
                    : isCompleted
                    ? "border-border-active text-text-muted hover:text-text-main"
                    : "border-transparent text-text-dim hover:text-text-muted"
                }`}
              >
                <div className="text-[10px] font-mono uppercase tracking-wider">
                  0{s.step}
                </div>
                <div className="truncate text-[11px] mt-0.5 hidden sm:block">
                  {s.category}
                </div>
              </button>
            );
          })}
        </div>

        {/* Step Content */}
        <div className="p-8 space-y-6">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-surface-muted border border-border text-primary shadow-xs">
              <Icon className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-0.5 text-[10px] font-mono font-semibold text-primary border border-primary/20">
                STEP {currentStep.step} OF 5 • {currentStep.category.toUpperCase()}
              </span>
              <h3 className="mt-1.5 text-xl font-semibold tracking-tight text-text-main">
                {currentStep.title}
              </h3>
              <p className="mt-1 text-xs text-text-muted leading-relaxed">
                {currentStep.subtitle}
              </p>
            </div>
          </div>

          <p className="text-sm leading-relaxed text-text-main/90 font-sans">
            {currentStep.description}
          </p>

          {/* Signals Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {currentStep.signals.map((sig) => {
              const SigIcon = sig.icon;
              return (
                <div
                  key={sig.label}
                  className="flex items-center gap-3 rounded-xl border border-border bg-surface-soft p-3.5"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-primary">
                    <SigIcon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-text-main">{sig.label}</div>
                    <div className="text-[11px] text-text-muted truncate">{sig.val}</div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Sample Snippet Terminal */}
          <div className="rounded-xl border border-border bg-surface-muted/90 p-4 space-y-1 font-mono">
            <div className="text-[10px] uppercase tracking-wider text-text-dim">
              Live Pipeline Stream
            </div>
            <div className="text-xs text-primary leading-relaxed">
              {currentStep.sampleSnippet}
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between border-t border-border bg-surface-soft/80 px-6 py-4">
          <button
            onClick={handlePrev}
            disabled={currentStepIndex === 0}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-2 text-xs font-semibold text-text-main hover:bg-surface-muted disabled:opacity-30 transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Previous
          </button>

          <button
            onClick={handleNext}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-white hover:bg-primary-hover shadow-sm transition-colors"
          >
            {currentStepIndex === PIPELINE_STEPS.length - 1 ? (
              <>
                <span>Enter Project Atlas</span>
                <PenTool className="h-3.5 w-3.5" />
              </>
            ) : (
              <>
                <span>Next Step</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
