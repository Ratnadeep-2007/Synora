"use client";

import React from "react";
import { Clock } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

interface SourceCardProps {
  name: string;
  subtitle: string;
  initials: string;
  connectionLabel: string;
  connected: boolean;
  rows: Array<{ label: string; value: React.ReactNode }>;
  footer?: React.ReactNode;
  actions?: React.ReactNode;
}

export function SourceCard({
  name,
  subtitle,
  initials,
  connectionLabel,
  connected,
  rows,
  footer,
  actions,
}: SourceCardProps) {
  return (
    <div className="p-5 rounded-lg bg-surface border border-border shadow-xs flex flex-col justify-between space-y-4">
      <div className="space-y-3.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-md bg-primary-soft flex items-center justify-center font-bold text-primary border border-primary/20 text-xs">
              {initials}
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text-main">{name}</h3>
              <span className="text-[11px] text-text-muted">{subtitle}</span>
            </div>
          </div>
          <StatusBadge kind={connected ? "connected" : "waiting"} label={connectionLabel} />
        </div>
        <div className="space-y-1.5 text-xs text-text-muted pt-2 border-t border-border">
          {rows.map((row, idx) => (
            <div key={idx} className="flex items-center justify-between gap-2">
              <span>{row.label}:</span>
              <span className="text-text-main text-right truncate max-w-[160px]">{row.value}</span>
            </div>
          ))}
        </div>
        {footer}
      </div>
      {actions && <div className="pt-3 border-t border-border flex justify-end gap-2">{actions}</div>}
    </div>
  );
}

export function SourceLastSync({ value }: { value?: string }) {
  if (!value) return <span className="text-text-muted">Never</span>;
  return (
    <span className="flex items-center gap-1 text-text-muted">
      <Clock className="w-3 h-3" />
      <span suppressHydrationWarning>{new Date(value).toLocaleString()}</span>
    </span>
  );
}
