"use client";

import React from "react";

/* ============================================================
   Synora design primitives — one place for buttons, sections,
   status language, empty states and overlays. Views compose
   these instead of re-declaring radii, borders and type scale.
   Light theme: paper surfaces, ink text, single emerald accent.
   ============================================================ */

type ButtonTone = "primary" | "quiet" | "danger" | "ghost";

const BUTTON_TONES: Record<ButtonTone, string> = {
  primary:
    "bg-primary hover:bg-primary-hover text-white shadow-sm",
  quiet:
    "bg-surface border border-border text-text-main hover:border-[var(--border-active)] hover:bg-[var(--surface-soft)]",
  danger:
    "bg-danger/10 text-danger border border-danger/25 hover:bg-danger/15",
  ghost: "text-text-muted hover:text-text-main hover:bg-[var(--surface-soft)]",
};

export function Button({
  tone = "quiet",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: ButtonTone }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed ${BUTTON_TONES[tone]} ${className}`}
      {...props}
    />
  );
}

export function Section({
  title,
  hint,
  action,
  children,
  className = "",
  delay = 0,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <section
      className={`reveal rounded-2xl border border-border bg-surface p-5 sm:p-6 shadow-xs space-y-4 ${className}`}
      style={{ "--reveal-delay": `${delay}ms` } as React.CSSProperties}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-text-main">{title}</h2>
          {hint && <p className="mt-0.5 text-xs text-text-muted">{hint}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export type AgentState =
  | "watching"
  | "processing"
  | "synthesizing"
  | "detected"
  | "updated"
  | "attention"
  | "idle";

const AGENT_COPY: Record<AgentState, string> = {
  watching: "Synora is watching",
  processing: "Synora is processing",
  synthesizing: "Synora is synthesizing",
  detected: "Synora detected a change",
  updated: "Memory updated",
  attention: "Needs attention",
  idle: "Synora idle",
};

/** Compact agent presence: a live dot plus honest state copy. */
export function AgentPresence({
  state = "watching",
  onInspect,
  compact = false,
}: {
  state?: AgentState;
  onInspect?: () => void;
  compact?: boolean;
}) {
  const alert = state === "attention" || state === "detected";
  return (
    <button
      onClick={onInspect}
      disabled={!onInspect}
      title={AGENT_COPY[state]}
      className={`state-fade inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs transition-all ${
        onInspect ? "cursor-pointer hover:border-primary/40" : "cursor-default"
      } ${
        alert
          ? "border-warning/40 bg-warning/10 text-text-main"
          : "border-primary/25 bg-primary/10 text-text-main"
      }`}
    >
      <span className="relative flex h-2 w-2">
        {state !== "idle" && (
          <span
            className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-60 ${
              alert ? "bg-warning" : "bg-primary"
            }`}
          />
        )}
        <span
          className={`relative inline-flex rounded-full h-2 w-2 ${
            alert ? "bg-warning" : state === "idle" ? "bg-text-dim" : "bg-primary"
          } ${state !== "idle" && !alert ? "animate-pulse-live" : ""}`}
        />
      </span>
      {!compact && (
        <span className="font-semibold text-[11px]">{AGENT_COPY[state]}</span>
      )}
    </button>
  );
}

/** Thin flowing line signalling a live backend process. */
export function ProgressLine({ className = "" }: { className?: string }) {
  return (
    <div className={`progress-line h-0.5 rounded-full bg-border-subtle ${className}`} aria-hidden />
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="py-10 px-6 text-center space-y-2">
      <p className="text-sm font-medium text-text-main">{title}</p>
      {hint && <p className="text-xs text-text-muted max-w-sm mx-auto leading-relaxed">{hint}</p>}
      {action && <div className="pt-2">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-lg ${className}`} aria-hidden />;
}

export function Modal({
  onClose,
  children,
  wide = false,
  danger = false,
  label = "Close dialog",
}: {
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
  danger?: boolean;
  label?: string;
}) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[var(--scrim)] backdrop-blur-sm animate-in fade-in duration-200"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={label}
    >
      <div
        className={`w-full ${
          wide ? "max-w-2xl" : "max-w-md"
        } rounded-2xl bg-surface border ${
          danger ? "border-danger/30" : "border-border"
        } shadow-xl overflow-hidden animate-in slide-in-from-bottom duration-200`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

export function Field({
  label,
  children,
  htmlFor,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  htmlFor?: string;
  hint?: string;
}) {
  return (
    <label htmlFor={htmlFor} className="block space-y-1.5">
      <span className="text-xs font-semibold text-text-main">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full px-3 py-2 text-xs rounded-lg bg-surface border border-border focus:border-primary text-text-main placeholder:text-text-dim focus:outline-none transition-colors";
