"use client";

import React from "react";
import { ArrowRight, BrainCircuit, CircleCheck, HelpCircle, PenTool } from "lucide-react";
import { ProjectState } from "@/lib/types";

interface OverviewViewProps {
  state: ProjectState | null;
  conflicts?: unknown[];
  excalidraw?: {
    name: string;
    version: number;
    updatedAt?: string | null;
    decisionsCount: number;
    requirementsCount: number;
    pendingCount: number;
  } | null;
  activityItems?: Array<{ time: string; text: string }>;
  onNavigateToTab: (tab: any) => void;
}

export function OverviewView({ state, excalidraw = null, activityItems = [], onNavigateToTab }: OverviewViewProps) {
  const requirements = state?.requirements?.length ?? 0;
  const decisions = state?.decisions?.length ?? 0;
  const questions = state?.open_questions?.length ?? 0;
  const version = state?.current_version ?? 1;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-2">
        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-primary/15 bg-primary-soft px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
          <BrainCircuit className="h-3.5 w-3.5" />
          AI Autopilot
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-text-main">Project at a glance</h1>
        <p className="max-w-2xl text-sm text-text-muted">
          Synora continuously turns connected project information into current state, knowledge, and architecture.
        </p>
      </header>

      <section className="grid grid-cols-3 gap-3">
        {[
          { label: "Requirements", value: requirements },
          { label: "Decisions", value: decisions },
          { label: "Open questions", value: questions },
        ].map((item) => (
          <div key={item.label} className="rounded-xl border border-border bg-surface p-4 shadow-xs">
            <div className="text-2xl font-semibold tracking-tight text-text-main">{String(item.value).padStart(2, "0")}</div>
            <div className="mt-1 text-xs text-text-muted">{item.label}</div>
          </div>
        ))}
      </section>

      <section className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-text-main">Current state</h2>
            <p className="mt-0.5 text-[11px] text-text-muted">Authoritative snapshot • v{version}</p>
          </div>
          <button onClick={() => onNavigateToTab("state")} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-primary hover:bg-primary-soft">
            View state <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="grid gap-5 p-5 lg:grid-cols-[1.3fr_0.7fr]">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-text-muted">Vision</div>
            <p className="mt-2 text-sm leading-6 text-text-main">{state?.vision || "No project vision has been recorded yet."}</p>
          </div>
          <div className="rounded-xl border border-border bg-canvas p-4">
            <div className="flex items-center gap-2 text-[11px] font-semibold text-success">
              <CircleCheck className="h-3.5 w-3.5" />
              AI-synchronized
            </div>
            <div className="mt-2 text-[11px] leading-5 text-text-muted">
              Routine project understanding and state maintenance happen automatically.
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <PenTool className="h-4 w-4 text-primary" />
            <div>
              <h2 className="text-sm font-semibold text-text-main">Architecture workspace</h2>
              <p className="mt-0.5 text-[11px] text-text-muted">AI-maintained, database-backed Excalidraw workspace.</p>
            </div>
          </div>
          <button onClick={() => onNavigateToTab("excalidraw")} className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-semibold text-text-main hover:bg-canvas">
            Open <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-5 px-5 py-4 text-xs">
          <span className="inline-flex items-center gap-2 text-text-main"><span className="h-2 w-2 rounded-full bg-success" />{excalidraw ? "Synchronized" : "Initializing"}</span>
          <span className="text-text-muted">Diagram v{excalidraw?.version || 1}</span>
          <span className="text-text-muted">{excalidraw?.requirementsCount || requirements} requirements</span>
          <span className="text-text-muted">{excalidraw?.decisionsCount || decisions} decisions</span>
          <span className="text-text-muted">PostgreSQL-backed</span>
        </div>
      </section>

      <section className="rounded-2xl border border-border bg-surface shadow-xs overflow-hidden">
        <div className="flex items-center gap-2 border-b border-border px-5 py-4">
          <HelpCircle className="h-4 w-4 text-primary" />
          <div>
            <h2 className="text-sm font-semibold text-text-main">Recent AI activity</h2>
            <p className="mt-0.5 text-[11px] text-text-muted">Latest automated project activity.</p>
          </div>
        </div>
        <div className="divide-y divide-border">
          {(activityItems.length ? activityItems.slice(0, 6) : [{ time: "—", text: "No recent activity yet." }]).map((item, index) => (
            <div key={index} className="flex items-center gap-4 px-5 py-3 text-xs">
              <span className="w-16 shrink-0 font-mono text-[10px] text-text-muted">{item.time}</span>
              <span className="text-text-main">{item.text}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}