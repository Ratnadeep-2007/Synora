"use client";

import React from "react";

type StatusKind =
  | "connected"
  | "working"
  | "waiting"
  | "review"
  | "failed"
  | "synchronized"
  | "pending"
  | "success"
  | "info"
  | "neutral";

const KIND_STYLES: Record<StatusKind, { dot: string; pill: string }> = {
  connected: { dot: "bg-success", pill: "bg-success/10 text-success border-success/20" },
  working: { dot: "bg-info", pill: "bg-info/10 text-info border-info/20" },
  waiting: { dot: "bg-text-muted", pill: "bg-canvas text-text-muted border-border" },
  review: { dot: "bg-warning", pill: "bg-warning/10 text-warning border-warning/20" },
  failed: { dot: "bg-danger", pill: "bg-danger/10 text-danger border-danger/20" },
  synchronized: { dot: "bg-success", pill: "bg-success/10 text-success border-success/20" },
  pending: { dot: "bg-warning", pill: "bg-warning/10 text-warning border-warning/20" },
  success: { dot: "bg-success", pill: "bg-success/10 text-success border-success/20" },
  info: { dot: "bg-info", pill: "bg-info/10 text-info border-info/20" },
  neutral: { dot: "bg-text-muted", pill: "bg-canvas text-text-muted border-border" },
};

interface StatusBadgeProps {
  kind: StatusKind;
  label: string;
  pulse?: boolean;
  className?: string;
}

export function StatusBadge({ kind, label, pulse = false, className = "" }: StatusBadgeProps) {
  const styles = KIND_STYLES[kind];
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium border ${styles.pill} ${className}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${styles.dot} ${pulse ? "animate-pulse" : ""}`} />
      <span>{label}</span>
    </span>
  );
}
