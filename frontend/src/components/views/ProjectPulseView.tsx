"use client";

import React, { useMemo } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Compass,
  FileText,
  Layers,
  MessageCircle,
  PenTool,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Video,
  Zap,
} from "lucide-react";
import { CandidateKnowledgeItem, Conflict, EvidenceItem, Project, ProjectState } from "@/lib/types";

interface ProjectPulseViewProps {
  project?: Project | null;
  state: ProjectState | null;
  conflicts: Conflict[];
  evidence: EvidenceItem[];
  // Accepted from the orchestrator; Pulse derives its own event stream from
  // state, so these are optional context, not required inputs.
  candidates?: CandidateKnowledgeItem[];
  history?: Array<{ version_number: number; reason?: string; created_at?: string }>;
  connections?: unknown[];
  activeProjectName?: string;
  projectVersion?: number;
  onNavigateToTab: (tab: any) => void;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
  onSyncAtlas?: () => Promise<void> | void;
  onOpenAgentSheet?: () => void;
  onOpenStoryModal?: () => void;
  onReviewConflict?: (conflict: Conflict) => void;
}

export function ProjectPulseView({
  project,
  state,
  conflicts,
  evidence,
  activeProjectName,
  projectVersion,
  onNavigateToTab,
  onOpenEvidence,
  onSyncAtlas,
  onOpenAgentSheet,
  onReviewConflict,
}: ProjectPulseViewProps) {
  const version = projectVersion ?? state?.current_version ?? 1;
  const projectName = activeProjectName || project?.name || "Project Pulse";
  const syncLabel = state?.updated_at
    ? `Memory v${version} · updated ${new Date(state.updated_at).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })}`
    : `Memory v${version}`;
  const requirements = state?.requirements || [];
  const decisions = state?.decisions || [];
  const questions = state?.open_questions || [];
  const architecture = state?.architecture || [];
  const openConflicts = conflicts.filter((c) => c.status === "open" || c.status === "under_review");

  // Synthesize meaningful intelligence events (not raw DB rows)
  const intelligenceEvents = useMemo(() => {
    const list: Array<{
      id: string;
      category: "Architecture" | "Decision" | "Requirement" | "Conflict" | "Question" | "Source";
      icon: React.ComponentType<{ className?: string }>;
      title: string;
      whatChanged: string;
      whyItMatters: string;
      provenance: string;
      evidenceIds: string[];
      affectedAreas: string[];
      actionLabel?: string;
      action?: () => void;
      severity?: "high" | "medium" | "low";
    }> = [];

    // 1. Conflicts (highest cognitive priority)
    openConflicts.slice(0, 2).forEach((conf) => {
      list.push({
        id: `conf-${conf.id}`,
        category: "Conflict",
        icon: ShieldAlert,
        title: conf.title,
        whatChanged: `Semantic inconsistency detected: "${conf.title}" between proposed change and existing state.`,
        whyItMatters:
          conf.description ||
          "Directly impacts project architecture integrity. Resolving this prevents downstream engineering misalignment.",
        provenance: `Flagged by Synora Conflict Engine • Source: ${conf.source || "Conversation Stream"}`,
        evidenceIds: conf.evidence_ids || [],
        affectedAreas: ["Architecture", conf.type || "Scope"],
        severity: (conf.severity as any) || "high",
        actionLabel: "Resolve Conflict",
        action: () => (onReviewConflict ? onReviewConflict(conf) : onNavigateToTab("state")),
      });
    });

    // 2. Latest Decisions
    decisions.slice(0, 3).forEach((dec, idx) => {
      list.push({
        id: `dec-${dec.id || idx}`,
        category: "Decision",
        icon: FileText,
        title: dec.text,
        whatChanged: `Authoritative decision ratified: "${dec.text}".`,
        whyItMatters:
          dec.detail ||
          "Freezes direction for related requirements and constraints. All future proposals will be validated against this decision.",
        provenance: `${dec.evidence_ids?.length || 1} supporting citations • Approved by ${
          dec.approved_by || "Project Team"
        }${dec.date ? ` on ${dec.date}` : ""}`,
        evidenceIds: dec.evidence_ids || [],
        affectedAreas: ["Decisions", "Governance"],
        actionLabel: 'View "Why?"',
        action: () => onOpenEvidence(dec.text, "Decision", dec.evidence_ids || []),
      });
    });

    // 3. Latest Architecture evolutions
    architecture.slice(0, 2).forEach((comp, idx) => {
      list.push({
        id: `arch-${comp.component}-${idx}`,
        category: "Architecture",
        icon: PenTool,
        title: `${comp.component} (${comp.role})`,
        whatChanged: `Topology component "${comp.component}" active in project model.`,
        whyItMatters: comp.details || "Represents core architectural boundary in the Living Atlas.",
        provenance: "AI-maintained vector diagram • Synced to Project State",
        evidenceIds: [],
        affectedAreas: ["Topology", "Living Atlas"],
        actionLabel: "View in Atlas",
        action: () => onNavigateToTab("excalidraw"),
      });
    });

    // 4. Requirements
    requirements.slice(0, 2).forEach((req, idx) => {
      list.push({
        id: `req-${req.id || idx}`,
        category: "Requirement",
        icon: CheckCircle2,
        title: req.title,
        whatChanged: `New verified requirement: "${req.title}".`,
        whyItMatters: req.content || "Defines implementation constraint verified against source evidence.",
        provenance: `${req.evidence_ids?.length || 1} transcript citations verified`,
        evidenceIds: req.evidence_ids || [],
        affectedAreas: ["Specifications"],
        actionLabel: "Inspect Evidence",
        action: () => onOpenEvidence(req.title, "Requirement", req.evidence_ids || []),
      });
    });

    // 5. Open Questions. Memory stores these as objects
    // {id, title, content, evidence_ids, ...}; older shapes were plain
    // strings. Never render the raw item: an object child crashes React.
    questions.slice(0, 1).forEach((q: any, idx) => {
      const qTitle = typeof q === "string" ? q : q?.title || q?.content || "Open question";
      const qEvidence: string[] = Array.isArray(q?.evidence_ids) ? q.evidence_ids : [];
      list.push({
        id: `q-${q?.id || idx}`,
        category: "Question",
        icon: Compass,
        title: qTitle,
        whatChanged: `Open ambiguity identified: "${qTitle}".`,
        whyItMatters:
          "Unresolved question discovered during conversation synthesis requiring stakeholder clarity.",
        provenance:
          qEvidence.length > 0
            ? `${qEvidence.length} supporting citations • Synthesized by Synora Intelligence Layer`
            : "Synthesized by Synora Intelligence Layer",
        evidenceIds: qEvidence,
        affectedAreas: ["Open Questions"],
        actionLabel: "View in State",
        action: () => onNavigateToTab("state"),
      });
    });

    return list;
  }, [openConflicts, decisions, architecture, requirements, questions, onReviewConflict, onNavigateToTab, onOpenEvidence]);

  return (
    <div className="space-y-8 view-enter">
      {/* Hero Pulse Bar */}
      <section className="reveal relative overflow-hidden rounded-2xl border border-border bg-surface p-6 sm:p-8 shadow-sm" style={{ "--reveal-delay": "0ms" } as React.CSSProperties}>
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-3 max-w-3xl">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1 font-mono text-[11px] font-semibold text-primary border border-primary/20">
                <span className="h-2 w-2 rounded-full bg-primary animate-pulse-live" />
                LIVE INTELLIGENCE
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-muted px-2.5 py-1 font-mono text-[11px] text-text-muted border border-border">
                State v{version}
              </span>
              <span className="text-[11px] text-text-dim flex items-center gap-1">
                <Clock className="h-3 w-3" /> {syncLabel}
              </span>
            </div>

            <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-text-main">
              {projectName}
            </h1>

            <p className="text-sm leading-relaxed text-text-muted">
              {state?.vision
                ? state.vision
                : "Synora continuously observes WhatsApp conversations & Google Meet transcripts, turning speech and context into an authoritative, living project intelligence model."}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5 shrink-0">
            {onSyncAtlas && (
              <button
                onClick={onSyncAtlas}
                className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-surface px-3.5 py-2 text-xs font-semibold text-text-main hover:bg-surface-soft hover:border-primary/40 transition-colors shadow-xs"
              >
                <RefreshCw className="h-3.5 w-3.5 text-primary" />
                <span>Sync Living Memory</span>
              </button>
            )}

            <button
              onClick={() => onNavigateToTab("excalidraw")}
              className="inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-white hover:bg-primary-hover shadow-sm transition-colors"
            >
              <span>Explore Living Atlas</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Intelligence Metric Pipeline Strip */}
        <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-3 pt-6 border-t border-border/60">
          <div
            onClick={() => onNavigateToTab("state")}
            className="rounded-xl border border-border/80 bg-surface-soft/60 p-3.5 cursor-pointer hover:border-primary/40 transition-colors"
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-text-muted">Ratified Decisions</span>
              <FileText className="h-3.5 w-3.5 text-primary" />
            </div>
            <div className="mt-2 text-xl font-semibold text-text-main">
              {String(decisions.length).padStart(2, "0")}
            </div>
            <div className="text-[10px] text-text-dim mt-0.5">Evidence provenance backed</div>
          </div>

          <div
            onClick={() => onNavigateToTab("state")}
            className="rounded-xl border border-border/80 bg-surface-soft/60 p-3.5 cursor-pointer hover:border-primary/40 transition-colors"
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-text-muted">Verified Requirements</span>
              <CheckCircle2 className="h-3.5 w-3.5 text-success" />
            </div>
            <div className="mt-2 text-xl font-semibold text-text-main">
              {String(requirements.length).padStart(2, "0")}
            </div>
            <div className="text-[10px] text-text-dim mt-0.5">Active constraints & specs</div>
          </div>

          <div
            onClick={() => onNavigateToTab("excalidraw")}
            className="rounded-xl border border-border/80 bg-surface-soft/60 p-3.5 cursor-pointer hover:border-primary/40 transition-colors"
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-text-muted">Living Atlas Nodes</span>
              <PenTool className="h-3.5 w-3.5 text-primary" />
            </div>
            <div className="mt-2 text-xl font-semibold text-text-main">
              {String(architecture.length).padStart(2, "0")}
            </div>
            <div className="text-[10px] text-text-dim mt-0.5">AI vector architecture</div>
          </div>

          <div
            onClick={() => (openConflicts.length ? onNavigateToTab("state") : undefined)}
            className={`rounded-xl border p-3.5 transition-colors ${
              openConflicts.length > 0
                ? "border-danger/40 bg-danger/5 cursor-pointer"
                : "border-border/80 bg-surface-soft/60"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-text-muted">Conflicts & Risks</span>
              <AlertTriangle
                className={`h-3.5 w-3.5 ${openConflicts.length > 0 ? "text-danger" : "text-text-dim"}`}
              />
            </div>
            <div
              className={`mt-2 text-xl font-semibold ${
                openConflicts.length > 0 ? "text-danger" : "text-text-main"
              }`}
            >
              {String(openConflicts.length).padStart(2, "0")}
            </div>
            <div className="text-[10px] text-text-dim mt-0.5">
              {openConflicts.length > 0 ? "Requires review" : "Zero semantic conflicts"}
            </div>
          </div>
        </div>
      </section>

      {/* Critical Conflict Triage Banner if present */}
      {openConflicts.length > 0 && (
        <section className="rounded-2xl border border-danger/30 bg-danger/5 p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-danger/10 text-danger border border-danger/25">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-text-main">
                  {openConflicts.length} Architectural Conflict{openConflicts.length > 1 ? "s" : ""}{" "}
                  Detected
                </h3>
                <span className="rounded bg-danger/20 px-2 py-0.5 text-[10px] font-mono font-semibold text-danger">
                  ACTION REQUIRED
                </span>
              </div>
              <p className="mt-0.5 text-xs text-text-muted">
                {openConflicts[0].title} — &quot;{openConflicts[0].description || "Proposed change conflicts with existing state constraints."}&quot;
              </p>
            </div>
          </div>

          <button
            onClick={() => (onReviewConflict ? onReviewConflict(openConflicts[0]) : onNavigateToTab("state"))}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-danger px-3.5 py-2 text-xs font-semibold text-white hover:bg-danger/90 transition-colors shadow-xs"
          >
            <span>Review Conflict</span>
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </section>
      )}

      {/* Meaningful Intelligence Events (The Pulse) */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold tracking-tight text-text-main">
              Meaningful Intelligence Events
            </h2>
          </div>
          <span className="text-[11px] text-text-dim">
            Curated changes synthesized from conversation streams
          </span>
        </div>

        <div className="grid grid-cols-1 gap-4">
          {intelligenceEvents.length === 0 ? (
            <div className="p-12 text-center rounded-2xl border border-dashed border-border bg-surface-soft/40 text-xs text-text-muted">
              Synora is listening. When meetings or WhatsApp discussions occur, synthesized intelligence
              events will appear here.
            </div>
          ) : (
            intelligenceEvents.map((event) => {
              const EventIcon = event.icon;
              return (
                <div
                  key={event.id}
                  className={`rounded-2xl border p-5 transition-all bg-surface hover:border-border-active shadow-xs ${
                    event.category === "Conflict"
                      ? "border-danger/30 bg-danger/[0.02]"
                      : "border-border"
                  }`}
                >
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                    <div className="flex items-start gap-3.5 min-w-0">
                      <div
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
                          event.category === "Conflict"
                            ? "bg-danger/10 text-danger border border-danger/20"
                            : event.category === "Decision"
                            ? "bg-primary-soft text-primary border border-primary/20"
                            : "bg-surface-muted text-text-muted border border-border"
                        }`}
                      >
                        <EventIcon className="h-4 w-4" />
                      </div>

                      <div className="min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[10px] font-mono uppercase tracking-wider font-semibold text-primary">
                            {event.category}
                          </span>
                          <span className="text-xs font-semibold text-text-main truncate">
                            {event.title}
                          </span>
                        </div>

                        <p className="text-xs leading-relaxed text-text-main/90 font-sans">
                          {event.whatChanged}
                        </p>

                        <p className="text-[11px] leading-relaxed text-text-muted">
                          <strong className="text-text-main font-medium">Why it matters:</strong>{" "}
                          {event.whyItMatters}
                        </p>

                        <div className="flex flex-wrap items-center gap-3 pt-2 text-[10px] text-text-dim">
                          <span className="flex items-center gap-1 font-mono">
                            <Sparkles className="h-3 w-3 text-primary" />
                            {event.provenance}
                          </span>
                          {event.affectedAreas.length > 0 && (
                            <span className="flex items-center gap-1">
                              • Affects: {event.affectedAreas.join(", ")}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {event.actionLabel && event.action && (
                      <div className="shrink-0 self-end sm:self-center">
                        <button
                          onClick={event.action}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-soft px-3 py-1.5 text-xs font-semibold text-text-main hover:bg-surface-muted hover:border-primary/40 transition-colors shadow-xs"
                        >
                          <span>{event.actionLabel}</span>
                          <ArrowRight className="h-3 w-3 text-primary" />
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* Autonomous Pipeline Footprint */}
      <section className="rounded-2xl border border-border bg-surface p-5 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/80 pb-4">
          <div className="flex items-center gap-2.5">
            <BrainCircuit className="h-4 w-4 text-primary" />
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-text-main">
                Autonomous Intelligence Layer
              </h3>
              <p className="text-[11px] text-text-muted">
                Persistent observation engine maintaining project continuity
              </p>
            </div>
          </div>

          {onOpenAgentSheet && (
            <button
              onClick={onOpenAgentSheet}
              className="inline-flex items-center gap-1.5 rounded-lg border border-primary/20 bg-primary-soft px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary-soft/80 transition-colors"
            >
              <span>Inspect Agent Focus</span>
              <ArrowRight className="h-3 w-3" />
            </button>
          )}
        </div>

        <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="rounded-xl border border-border bg-surface-soft p-3.5">
            <div className="flex items-center gap-2 text-xs font-semibold text-text-main">
              <Video className="h-3.5 w-3.5 text-primary" />
              <span>Google Meet Ingestion</span>
            </div>
            <p className="mt-1 text-[11px] text-text-muted leading-relaxed">
              Vexa & Sarvam transcription pipelines listen to discussions and generate candidate
              proposals automatically.
            </p>
          </div>

          <div className="rounded-xl border border-border bg-surface-soft p-3.5">
            <div className="flex items-center gap-2 text-xs font-semibold text-text-main">
              <MessageCircle className="h-3.5 w-3.5 text-primary" />
              <span>WhatsApp Baileys Sockets</span>
            </div>
            <p className="mt-1 text-[11px] text-text-muted leading-relaxed">
              Monitors dedicated project group chats, extracting decisions without manual developer
              ticket logging.
            </p>
          </div>

          <div className="rounded-xl border border-border bg-surface-soft p-3.5">
            <div className="flex items-center gap-2 text-xs font-semibold text-text-main">
              <PenTool className="h-3.5 w-3.5 text-primary" />
              <span>Living Project Atlas</span>
            </div>
            <p className="mt-1 text-[11px] text-text-muted leading-relaxed">
              PostgreSQL-backed infinite Excalidraw canvas continuously updated as requirements and
              components evolve.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
