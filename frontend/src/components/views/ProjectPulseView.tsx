"use client";

import React from "react";
import {
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  Layers3,
  MessageSquareText,
  Radio,
  Settings2,
  ShieldCheck,
  Sparkles,
  Video,
  Zap,
} from "lucide-react";
import { CandidateKnowledgeItem, Conflict, EvidenceItem, Project, ProjectState } from "@/lib/types";
import type { NavTab } from "@/components/layout/Shell";

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
  projects?: Project[];
  currentProjectId?: string;
  onSelectProject?: (projectId: string) => void;
  onNavigateToTab: (tab: NavTab) => void;
  onOpenEvidence: (title: string, contextType: string, evidenceIds: string[]) => void;
  onSyncAtlas?: () => Promise<void> | void;
  onOpenAgentSheet?: () => void;
  onOpenStoryModal?: () => void;
  onReviewConflict?: (conflict: Conflict) => void;
}

const FEATURES: Array<{
  tab: NavTab;
  title: string;
  detail: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { tab: "state", title: "Authoritative State", detail: "Every decision approved into versioned memory. Nothing speculative survives.", icon: BrainCircuit },
  { tab: "excalidraw", title: "Living Atlas", detail: "Memory draws itself — diagrams, notes and canvases that stay in sync.", icon: Layers3 },
  { tab: "meetings", title: "Meeting Memory", detail: "Vexa captures, Sarvam transcribes, Hindi becomes English, canvases compile.", icon: Video },
  { tab: "sources", title: "Connected Sources", detail: "WhatsApp and Meet streams file evidence on their own.", icon: MessageSquareText },
];

const STEPS = [
  { n: "01", title: "Capture", detail: "The bot joins, records, and diarizes every voice." },
  { n: "02", title: "Ground", detail: "Each claim is pinned to verbatim evidence." },
  { n: "03", title: "Approve", detail: "You confirm what enters permanent memory." },
  { n: "04", title: "Draw", detail: "Memory renders itself as living canvases." },
];

export function ProjectPulseView({
  state,
  conflicts,
  evidence,
  activeProjectName,
  projectVersion,
  projects = [],
  currentProjectId,
  onSelectProject,
  onNavigateToTab,
}: ProjectPulseViewProps) {
  const openConflicts = conflicts.filter(
    (c) => c.status === "open" || c.status === "unresolved" || c.status === "under_review"
  ).length;
  const version = projectVersion || state?.current_version || 1;

  return (
    <div className="mx-auto w-full max-w-6xl px-6 pb-16 pt-8">
      <style>{`
        @keyframes synora-rise { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes synora-drift { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(30px,-18px) scale(1.08); } }
        @keyframes synora-ping { 0% { transform: scale(1); opacity: .7; } 80%,100% { transform: scale(2.1); opacity: 0; } }
        @keyframes synora-flow { to { stroke-dashoffset: -28; } }
        @keyframes synora-node { 0%,100% { opacity: 1; } 50% { opacity: .4; } }
        @keyframes synora-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-9px); } }
        @keyframes synora-float2 { 0%,100% { transform: translateY(0) rotate(-1deg); } 50% { transform: translateY(-6px) rotate(1deg); } }
        .synora-rise { animation: synora-rise .6s cubic-bezier(.22,.8,.3,1) both; }
        .synora-d1 { animation-delay: .07s; } .synora-d2 { animation-delay: .15s; }
        .synora-d3 { animation-delay: .23s; } .synora-d4 { animation-delay: .31s; }
        .synora-d5 { animation-delay: .39s; } .synora-d6 { animation-delay: .47s; }
        .synora-orb { animation: synora-drift 10s ease-in-out infinite; }
        .synora-ping { animation: synora-ping 2s cubic-bezier(0,0,.2,1) infinite; }
        .synora-flow { stroke-dasharray: 7 7; animation: synora-flow 1.4s linear infinite; }
        .synora-node { animation: synora-node 2.6s ease-in-out infinite; }
        .synora-float { animation: synora-float 5.5s ease-in-out infinite; }
        .synora-float2 { animation: synora-float2 7s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .synora-rise, .synora-orb, .synora-ping, .synora-flow, .synora-node, .synora-float, .synora-float2 { animation: none; }
        }
      `}</style>

      {/* Mini nav */}
      <div className="synora-rise mb-8 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl border border-primary/20 bg-primary-soft text-sm font-black text-primary">S</span>
          <span className="text-sm font-semibold tracking-tight">Synora</span>
        </div>
        <div className="hidden items-center gap-1 text-xs sm:flex">
          {(["state", "excalidraw", "meetings", "sources"] as NavTab[]).map((t) => (
            <button key={t} onClick={() => onNavigateToTab(t)}
              className="rounded-lg px-3 py-1.5 font-medium capitalize text-text-muted transition-colors hover:bg-surface-soft hover:text-text-main">
              {t === "excalidraw" ? "Atlas" : t}
            </button>
          ))}
          <button onClick={() => onNavigateToTab("meetings")}
            className="ml-2 rounded-xl bg-primary px-4 py-2 font-medium text-white shadow-xs transition-transform hover:-translate-y-px">
            Start capturing
          </button>
        </div>
      </div>

      {/* Hero */}
      <section className="relative overflow-hidden rounded-[2rem] border border-border bg-gradient-to-b from-white to-canvas px-8 py-14 sm:px-14">
        <div aria-hidden className="pointer-events-none absolute -top-24 -right-20 h-80 w-80 rounded-full bg-primary/10 blur-3xl synora-orb" />
        <div aria-hidden className="pointer-events-none absolute -bottom-28 -left-12 h-64 w-64 rounded-full bg-primary/5 blur-3xl synora-orb" />

        <div className="relative grid items-center gap-12 lg:grid-cols-[1fr_.95fr]">
          <div>
            <div className="synora-rise inline-flex items-center gap-1.5 rounded-full border border-primary/25 bg-primary-soft px-3 py-1 text-[11px] font-semibold text-primary">
              <Sparkles className="h-3 w-3" />
              Meeting memory that keeps moving
            </div>
            <h1 className="synora-rise synora-d1 mt-5 text-4xl sm:text-6xl font-semibold leading-[1.04] tracking-tight text-text-main">
              Every meeting becomes <span className="text-primary">memory.</span>
            </h1>
            <p className="synora-rise synora-d2 mt-4 max-w-lg text-[15px] leading-relaxed text-text-muted">
              Synora joins your calls, transcribes every voice — Hindi included —
              pins each claim to evidence, and draws living canvases from what it
              learned. Nothing invented. Everything traceable.
            </p>
            <div className="synora-rise synora-d3 mt-7 flex flex-wrap gap-3">
              <button onClick={() => onNavigateToTab("meetings")}
                className="group inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-medium text-white shadow-sm transition-transform hover:-translate-y-px">
                Open meetings
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </button>
              <button onClick={() => onNavigateToTab("excalidraw")}
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-white px-5 py-3 text-sm font-medium text-text-main transition-all hover:-translate-y-px hover:border-primary/40">
                <Layers3 className="h-4 w-4 text-primary" />
                See the Atlas
              </button>
            </div>
            <div className="synora-rise synora-d4 mt-7 flex flex-wrap gap-x-6 gap-y-2 text-xs text-text-muted">
              <span><strong className="text-text-main">{evidence.length}</strong> evidence items</span>
              <span><strong className="text-text-main">v{version}</strong> memory</span>
              <span className="inline-flex items-center gap-1.5">
                <span className="relative flex h-2 w-2">
                  <span className="synora-ping absolute inline-flex h-full w-full rounded-full bg-primary" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                </span>
                Watching {activeProjectName || "Synora Core"}
              </span>
            </div>
            {projects.length > 0 && (
              <label className="synora-rise synora-d4 mt-4 inline-flex items-center gap-2 rounded-xl border border-border bg-white px-3 py-2 text-xs shadow-xs">
                <span className="text-text-dim">Project</span>
                <span className="relative inline-flex items-center">
                  <select value={currentProjectId || ""} onChange={(e) => onSelectProject?.(e.target.value)}
                    className="appearance-none bg-transparent pr-5 font-medium text-text-main outline-none" aria-label="Select project">
                    {projects.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-0 h-3.5 w-3.5 text-text-dim" />
                </span>
              </label>
            )}
          </div>

          {/* Product visual: floating memory cards + pipeline */}
          <div className="synora-rise synora-d2 relative" aria-hidden>
            <div className="synora-float rounded-2xl border border-border bg-white/90 p-5 shadow-lg backdrop-blur">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-primary">
                <ShieldCheck className="h-3.5 w-3.5" /> DECISION · v{version}
              </div>
              <p className="mt-2 text-sm font-medium leading-snug">Kitchen display reaches the screen in realtime during rush.</p>
              <p className="mt-1 text-[11px] text-text-dim">Pinned to verbatim evidence · 2 citations</p>
            </div>
            <div className="synora-float2 ml-10 mt-3 rounded-2xl border border-border bg-white/90 p-5 shadow-md backdrop-blur">
              <div className="flex items-center gap-2 text-[11px] font-semibold text-primary">
                <Zap className="h-3.5 w-3.5" /> TRANSLATED · hi → en
              </div>
              <p className="mt-2 text-sm font-medium leading-snug">Retention policy draft by Wednesday.</p>
              <p className="mt-1 text-[11px] text-text-dim">Original Hindi preserved alongside</p>
            </div>
            <svg viewBox="0 0 400 96" className="mt-4 h-auto w-full text-primary" role="presentation">
              <line x1="40" y1="34" x2="130" y2="34" stroke="currentColor" strokeOpacity=".5" strokeWidth="2.5" className="synora-flow" />
              <line x1="155" y1="34" x2="245" y2="34" stroke="currentColor" strokeOpacity=".5" strokeWidth="2.5" className="synora-flow" />
              <line x1="270" y1="34" x2="360" y2="34" stroke="currentColor" strokeOpacity=".5" strokeWidth="2.5" className="synora-flow" />
              {[25, 142, 258, 372].map((cx, i) => (
                <g key={cx} className="synora-node" style={{ animationDelay: `${i * 0.4}s` }}>
                  <circle cx={cx} cy="34" r="11" fill="currentColor" fillOpacity=".12" stroke="currentColor" strokeWidth="2" />
                  <circle cx={cx} cy="34" r="3.5" fill="currentColor" />
                </g>
              ))}
              {["Capture", "Ground", "Approve", "Draw"].map((s, i) => (
                <text key={s} x={[25, 142, 258, 372][i]} y="62" textAnchor="middle" fontSize="10" fill="currentColor" opacity=".7">{s}</text>
              ))}
            </svg>
          </div>
        </div>
      </section>

      {/* Integrations strip */}
      <div className="synora-rise synora-d3 mt-6 flex flex-wrap items-center justify-center gap-2 text-[11px] font-medium text-text-muted">
        <span className="mr-1 uppercase tracking-[0.16em] text-text-dim">Works with</span>
        {["Google Meet", "WhatsApp", "Excalidraw", "Hindi + English", "Neon Postgres", "Render"].map((s) => (
          <span key={s} className="rounded-full border border-border bg-canvas px-3 py-1.5">{s}</span>
        ))}
      </div>

      {/* Features */}
      <section className="mt-10 grid gap-3 sm:grid-cols-2">
        {FEATURES.map((f, i) => (
          <button key={f.tab} onClick={() => onNavigateToTab(f.tab)}
            className={`synora-rise group rounded-2xl border border-border bg-canvas p-6 text-left transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md synora-d${Math.min(i + 2, 6)}`}>
            <f.icon className="h-6 w-6 text-primary" />
            <div className="mt-3 flex items-center gap-1.5 text-base font-semibold text-text-main">
              {f.title}
              <ArrowRight className="h-4 w-4 text-text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
            </div>
            <p className="mt-1.5 text-[13px] leading-relaxed text-text-muted">{f.detail}</p>
          </button>
        ))}
      </section>

      {/* How it works */}
      <section className="synora-rise synora-d5 mt-10 rounded-[2rem] border border-border bg-canvas p-8 sm:p-10">
        <h2 className="text-xl font-semibold tracking-tight">From call to canvas in four steps</h2>
        <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s) => (
            <div key={s.n}>
              <div className="font-mono text-xs font-bold text-primary">{s.n}</div>
              <div className="mt-1.5 font-semibold">{s.title}</div>
              <p className="mt-1 text-xs leading-relaxed text-text-muted">{s.detail}</p>
            </div>
          ))}
        </div>
        <div className="mt-8 flex flex-wrap items-center gap-3">
          <button onClick={() => onNavigateToTab("settings")}
            className="inline-flex items-center gap-2 rounded-xl border border-border bg-white px-4 py-2.5 text-sm font-medium transition-all hover:-translate-y-px hover:border-primary/40">
            <Settings2 className="h-4 w-4 text-primary" /> Workspace settings
          </button>
          <span className="inline-flex items-center gap-1.5 text-xs text-text-muted">
            <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
            {openConflicts === 0 ? "No open conflicts" : `${openConflicts} items need review in State`}
          </span>
        </div>
      </section>
    </div>
  );
}
