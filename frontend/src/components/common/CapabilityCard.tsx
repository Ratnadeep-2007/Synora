"use client";

import React from "react";
import { Play } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

interface CapabilityCardProps {
  capabilityId: string;
  name: string;
  role: string;
  description: string;
  capabilities: string[];
  status: string;
  currentTask?: string | null;
  running?: boolean;
  onDispatch?: () => void;
  onAuditRuns?: () => void;
}

export function CapabilityCard({
  capabilityId: _capabilityId,
  name,
  role,
  description,
  capabilities,
  status,
  currentTask,
  running = false,
  onDispatch,
  onAuditRuns,
}: CapabilityCardProps) {
  return (
    <article className="p-4 rounded-xl bg-surface border border-border flex flex-col justify-between gap-4">
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-text-main">{name}</h3>
            <p className="text-[11px] text-text-muted mt-0.5">{role}</p>
          </div>
          <StatusBadge kind={status === "ready" ? "success" : "neutral"} label={status} />
        </div>
        <p className="text-xs text-text-muted leading-relaxed">{description}</p>
        {capabilities.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {capabilities.slice(0, 4).map((item) => (
              <span key={item} className="px-1.5 py-0.5 rounded bg-canvas border border-border text-[10px] text-text-main">{item}</span>
            ))}
          </div>
        )}
        {currentTask && <p className="text-[11px] text-text-muted pt-2 border-t border-border">Recent: <span className="text-text-main">{currentTask}</span></p>}
      </div>
      <div className="flex items-center justify-between gap-2 pt-3 border-t border-border">
        <button onClick={onAuditRuns} className="text-xs font-medium text-text-muted hover:text-text-main">History</button>
        <button onClick={onDispatch} disabled={running} className="px-3 py-1.5 rounded-md bg-primary hover:bg-primary-hover text-white text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50">
          <Play className={`w-3.5 h-3.5 ${running ? "animate-spin" : ""}`} />
          {running ? "Working…" : "Run"}
        </button>
      </div>
    </article>
  );
}
