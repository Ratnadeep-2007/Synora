
"use client";

import React, { useMemo } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Compass,
  FileText,
  Layers3,
  MessageSquareText,
  PenTool,
  RefreshCw,
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

type PulseEvent = {
  id: string;
  kind: "conflict" | "decision" | "requirement" | "question" | "architecture" | "source";
  label: string;
  title: string;
  detail: string;
  meta: string;
  evidenceIds: string[];
  action?: () => void;
  actionLabel?: string;
};

const ICONS: Record<PulseEvent["kind"], React.ComponentType<{ className?: string }>> = {
  conflict: AlertTriangle,
  decision: FileText,
  requirement: CheckCircle2,
  question: Compass,
  architecture: PenTool,
  source: MessageSquareText,
};

function itemText(item: any): string {
  if (typeof item === "string") return item;
  return item?.title || item?.content || item?.text || item?.question || "Project signal";
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
  onOpenStoryModal,
  onReviewConflict,
}: ProjectPulseViewProps) {
  const version = projectVersion || state?.current_version || 1;
  const projectName = activeProjectName || project?.name || "Your project";
  const requirements = state?.requirements || [];
  const decisions = state?.decisions || [];
  const architecture = state?.architecture || [];
  const questions = state?.open_questions || [];
  const openConflicts = conflicts.filter(
    (item) => item.status === "open" || item.status === "under_review"
  );
  const updatedLabel = state?.updated_at
    ? new Date(state.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "waiting for memory";

  const events = useMemo<PulseEvent[]>(() => {
    const list: PulseEvent[] = [];

    openConflicts.slice(0, 2).forEach((item) => {
      list.push({
        id: "conflict-" + item.id,
        kind: "conflict",
        label: "Attention",
        title: item.title,
        detail: item.description || "A newer signal conflicts with the current project state.",
        meta: "Needs review",
        evidenceIds: item.evidence_ids || [],
        action: () =>
          onReviewConflict ? onReviewConflict(item) : onNavigateToTab("state"),
        actionLabel: "Review",
      });
    });

    decisions.slice(0, 2).forEach((item, index) => {
      list.push({
        id: "decision-" + (item.id || index),
        kind: "decision",
        label: "Decision",
        title: item.text,
        detail: item.detail || "An authoritative direction was added to the project model.",
        meta: (item.evidence_ids?.length || 0) + " evidence links",
        evidenceIds: item.evidence_ids || [],
        action: () => onOpenEvidence(item.text, "Decision", item.evidence_ids || []),
        actionLabel: "Why?",
      });
    });

    requirements.slice(0, 2).forEach((item, index) => {
      list.push({
        id: "requirement-" + (item.id || index),
        kind: "requirement",
        label: "Requirement",
        title: item.title,
        detail: item.content || "A verified requirement entered the project model.",
        meta: (item.evidence_ids?.length || 0) + " evidence links",
        evidenceIds: item.evidence_ids || [],
        action: () => onOpenEvidence(item.title, "Requirement", item.evidence_ids || []),
        actionLabel: "Inspect",
      });
    });

    architecture.slice(0, 2).forEach((item, index) => {
      list.push({
        id: "architecture-" + item.component + "-" + index,
        kind: "architecture",
        label: "Atlas",
        title: item.component,
        detail: item.details || item.role || "Architecture boundary maintained in the Living Atlas.",
        meta: "Synced to state",
        evidenceIds: [],
        action: () => onNavigateToTab("excalidraw"),
        actionLabel: "Open Atlas",
      });
    });

    questions.slice(0, 2).forEach((item: any, index) => {
      const title = itemText(item);
      const evidenceIds = Array.isArray(item?.evidence_ids) ? item.evidence_ids : [];
      list.push({
        id: "question-" + (item?.id || index),
        kind: "question",
        label: "Open question",
        title,
        detail: item?.content || "Synora has surfaced an ambiguity that may affect the next decision.",
        meta: item?.urgency || "Needs clarity",
        evidenceIds,
        action: () => onNavigateToTab("state"),
        actionLabel: "Open state",
      });
    });

    if (!list.length && evidence.length) {
      evidence.slice(0, 3).forEach((item) => {
        list.push({
          id: "source-" + item.id,
          kind: "source",
          label: "Evidence",
          title: item.content.slice(0, 96),
          detail: "New source material is available for Synora to contextualize.",
          meta: item.source || "Connected source",
          evidenceIds: [item.id],
          action: () => onOpenEvidence("Evidence", item.source || "Source", [item.id]),
          actionLabel: "Open",
        });
      });
    }

    return list.slice(0, 7);
  }, [
    openConflicts,
    decisions,
    requirements,
    architecture,
    questions,
    evidence,
    onNavigateToTab,
    onOpenEvidence,
    onReviewConflict,
  ]);

  const headline = events[0];

  return (
    <div className="view-enter space-y-8">
      <section className="pulse-hero relative overflow-hidden rounded-[28px] border border-border bg-white shadow-sm">
        <div className="pulse-grid absolute inset-0" aria-hidden />
        <div className="relative grid gap-8 p-6 sm:p-8 lg:grid-cols-[1.15fr_.85fr] lg:p-10">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary-soft px-3 py-1.5 font-mono text-[9px] font-semibold uppercase tracking-[0.18em] text-primary">
                <span className="relative h-1.5 w-1.5 rounded-full bg-primary">
                  <span className="absolute inset-0 rounded-full bg-primary pulse-ring" />
                </span>
                Synora is watching
              </span>
              <span className="rounded-full border border-border bg-canvas px-3 py-1.5 font-mono text-[9px] font-semibold text-text-muted">
                State v{version}
              </span>
              <span className="inline-flex items-center gap-1.5 text-[10px] text-text-dim">
                <Clock3 className="h-3 w-3" />
                updated {updatedLabel}
              </span>
            </div>

            <div className="mt-7">
              <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-text-dim">
                Project pulse
              </div>
              <h1 className="mt-2 text-3xl font-semibold tracking-[-0.035em] text-text-main sm:text-4xl">
                {projectName}
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-7 text-text-muted sm:text-[15px]">
                {state?.vision ||
                  "Synora turns conversations and source material into a continuously maintained project memory."}
              </p>
            </div>

            <div className="mt-7 flex flex-wrap gap-2">
              {onOpenAgentSheet && (
                <button
                  type="button"
                  onClick={onOpenAgentSheet}
                  className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-xs font-semibold text-white shadow-sm transition-all hover:-translate-y-px hover:bg-primary-hover"
                >
                  <BrainCircuit className="h-3.5 w-3.5" />
                  Inspect Synora
                </button>
              )}

              <button
                type="button"
                onClick={() => onNavigateToTab("excalidraw")}
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-white px-4 py-2.5 text-xs font-semibold text-text-main shadow-xs transition-all hover:-translate-y-px hover:border-border-active hover:shadow-sm"
              >
                <PenTool className="h-3.5 w-3.5 text-primary" />
                Open Atlas
                <ArrowRight className="h-3.5 w-3.5 text-text-dim" />
              </button>

              {onSyncAtlas && (
                <button
                  type="button"
                  onClick={onSyncAtlas}
                  className="inline-flex items-center gap-2 rounded-xl px-3 py-2.5 text-xs font-semibold text-text-muted transition-all hover:bg-surface-soft hover:text-text-main"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Sync now
                </button>
              )}
            </div>
          </div>

          <div className="relative flex min-h-[240px] items-end justify-end">
            <div className="pulse-orbit absolute right-8 top-3 h-56 w-56 rounded-full border border-primary/10" aria-hidden />
            <div className="pulse-orbit pulse-orbit-delay absolute right-0 top-12 h-44 w-44 rounded-full border border-primary/10" aria-hidden />

            <div className="relative w-full max-w-sm rounded-2xl border border-border bg-white/90 p-4 shadow-md backdrop-blur">
              <div className="flex items-center justify-between border-b border-border-subtle pb-3">
                <div>
                  <div className="text-[9px] font-semibold uppercase tracking-[0.18em] text-text-dim">
                    What matters now
                  </div>
                  <div className="mt-1 text-xs font-semibold text-text-main">
                    {headline ? headline.label : "Listening"}
                  </div>
                </div>
                <Sparkles className="h-4 w-4 text-primary" />
              </div>

              {headline ? (
                <div className="pt-4">
                  <div className="flex items-start gap-3">
                    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary">
                      {React.createElement(ICONS[headline.kind], { className: "h-4 w-4" })}
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold leading-5 text-text-main">{headline.title}</div>
                      <p className="mt-2 text-[11px] leading-5 text-text-muted">{headline.detail}</p>
                    </div>
                  </div>
                  <div className="mt-4 flex items-center justify-between text-[9px] text-text-dim">
                    <span>{headline.meta}</span>
                    {headline.action && (
                      <button type="button" onClick={headline.action} className="font-semibold text-primary hover:underline">
                        {headline.actionLabel}
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="pt-7 text-center">
                  <div className="mx-auto grid h-11 w-11 place-items-center rounded-2xl bg-primary-soft text-primary">
                    <Activity className="h-5 w-5" />
                  </div>
                  <div className="mt-3 text-sm font-semibold">Synora is listening</div>
                  <p className="mx-auto mt-1 max-w-[240px] text-[11px] leading-5 text-text-muted">
                    New evidence will appear here as the project changes.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="relative border-t border-border-subtle bg-surface-soft/50 px-6 py-4 sm:px-8">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-[10px] font-semibold text-text-muted">
              <span className="grid h-6 w-6 place-items-center rounded-lg bg-white text-primary shadow-xs">
                <Layers3 className="h-3.5 w-3.5" />
              </span>
              Conversations become evidence, state and visual memory.
            </div>
            {onOpenStoryModal && (
              <button type="button" onClick={onOpenStoryModal} className="hidden items-center gap-1.5 text-[10px] font-semibold text-primary sm:flex">
                How Synora works
                <ArrowRight className="h-3 w-3" />
              </button>
            )}
          </div>

          <div className="pipeline-line mt-4 grid grid-cols-4 gap-2">
            {(
              [
                ["Sources", Video],
                ["Evidence", MessageSquareText],
                ["State", Layers3],
                ["Atlas", PenTool],
              ] as Array<[string, React.ComponentType<{ className?: string }>]>
            ).map(([label, Icon], index) => (
              <div key={String(label)} className="relative">
                <div className="flex items-center gap-2">
                  {React.createElement(Icon as React.ComponentType<{ className?: string }>, {
                    className: "h-3.5 w-3.5 text-primary",
                  })}
                  <span className="text-[10px] font-medium text-text-main">{label}</span>
                </div>
                {index < 3 && <span className="pipeline-arrow hidden sm:block">→</span>}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="scroll-story grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Decisions", decisions.length, "Authoritative direction", FileText, "state"],
            ["Requirements", requirements.length, "Verified specifications", CheckCircle2, "state"],
            ["Architecture", architecture.length, "Mapped in the Atlas", PenTool, "excalidraw"],
            ["Attention", openConflicts.length, openConflicts.length ? "Needs review" : "No conflicts open", AlertTriangle, "state"],
          ] as Array<[string, number, string, React.ComponentType<{ className?: string }>, any]>
        ).map(([label, value, hint, Icon, target]) => (
          <button
            key={String(label)}
            type="button"
            onClick={() => onNavigateToTab(target)}
            className="group rounded-2xl border border-border bg-white p-4 text-left shadow-xs transition-all hover:-translate-y-0.5 hover:border-border-active hover:shadow-sm"
          >
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-text-dim">{label}</span>
              {React.createElement(Icon as React.ComponentType<{ className?: string }>, {
                className: "h-4 w-4 " + (label === "Attention" && openConflicts.length ? "text-danger" : "text-primary"),
              })}
            </div>
            <div className="mt-3 text-2xl font-semibold tracking-tight text-text-main">{String(value).padStart(2, "0")}</div>
            <p className="mt-1 text-[10px] leading-4 text-text-muted">{hint}</p>
          </button>
        ))}
      </section>

      {openConflicts.length > 0 && (
        <section className="overflow-hidden rounded-2xl border border-danger/15 bg-white shadow-xs">
          <div className="flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-danger/5 text-danger">
                <AlertTriangle className="h-4 w-4" />
              </div>
              <div>
                <div className="text-xs font-semibold text-text-main">
                  {openConflicts.length} item{openConflicts.length > 1 ? "s" : ""} need attention
                </div>
                <p className="mt-1 text-[11px] text-text-muted">{openConflicts[0].title}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => (onReviewConflict ? onReviewConflict(openConflicts[0]) : onNavigateToTab("state"))}
              className="inline-flex items-center gap-1.5 rounded-xl border border-danger/15 bg-danger/5 px-3 py-2 text-[10px] font-semibold text-danger hover:bg-danger/10"
            >
              Review
              <ArrowRight className="h-3 w-3" />
            </button>
          </div>
        </section>
      )}

      <section className="scroll-story space-y-4">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" />
              <h2 className="text-sm font-semibold tracking-tight text-text-main">Intelligence stream</h2>
            </div>
            <p className="mt-1 text-[11px] text-text-muted">Only the project changes worth your attention.</p>
          </div>
          <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-text-dim">
            {events.length ? events.length + " signals" : "waiting for signals"}
          </span>
        </div>

        {events.length ? (
          <div className="overflow-hidden rounded-2xl border border-border bg-white shadow-xs">
            {events.map((event, index) => {
              const Icon = ICONS[event.kind];
              return (
                <div
                  key={event.id}
                  className={
                    "group grid gap-4 px-5 py-4 transition-colors hover:bg-surface-soft/60 sm:grid-cols-[38px_minmax(0,1fr)_auto] " +
                    (index ? "border-t border-border-subtle" : "")
                  }
                >
                  <div className="grid h-9 w-9 place-items-center rounded-xl bg-canvas text-text-muted">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[9px] font-semibold uppercase tracking-[0.16em] text-primary">{event.label}</span>
                      <span className="truncate text-xs font-semibold text-text-main">{event.title}</span>
                    </div>
                    <p className="mt-1 text-[11px] leading-5 text-text-muted">{event.detail}</p>
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-text-dim">
                      <span>{event.meta}</span>
                      {event.evidenceIds.length > 0 && <span>{event.evidenceIds.length} citations</span>}
                    </div>
                  </div>
                  <div className="flex items-center sm:self-center">
                    {event.action && (
                      <button
                        type="button"
                        onClick={event.action}
                        className="rounded-lg border border-transparent px-2.5 py-1.5 text-[10px] font-semibold text-text-muted transition-all group-hover:border-border group-hover:bg-white group-hover:text-text-main"
                      >
                        {event.actionLabel}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-white p-10 text-center">
            <div className="mx-auto grid h-11 w-11 place-items-center rounded-2xl bg-primary-soft text-primary">
              <Zap className="h-5 w-5" />
            </div>
            <h3 className="mt-3 text-sm font-semibold text-text-main">Nothing needs your attention yet</h3>
            <p className="mx-auto mt-1 max-w-md text-[11px] leading-5 text-text-muted">
              When a meeting, message or source changes the project, Synora will surface the meaningful part here.
            </p>
          </div>
        )}
      </section>

      <section className="scroll-story rounded-2xl border border-border bg-white p-5 shadow-xs sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-primary-soft text-primary">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-xs font-semibold text-text-main">The project stays in motion.</h2>
              <p className="mt-1 max-w-2xl text-[11px] leading-5 text-text-muted">
                Synora keeps evidence, authoritative state and the visual Atlas aligned so the team can work from one current project memory.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {(
              [
                ["conversations", Video],
                ["evidence", MessageSquareText],
                ["state", Layers3],
                ["atlas", PenTool],
              ] as Array<[string, React.ComponentType<{ className?: string }>]>
            ).map(([label, Icon]) => (
              <span key={String(label)} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-canvas px-2.5 py-1.5 text-[9px] font-medium text-text-muted">
                {React.createElement(Icon as React.ComponentType<{ className?: string }>, { className: "h-3 w-3" })}
                {label}
              </span>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
