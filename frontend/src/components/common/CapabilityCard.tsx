"use client";

import React from "react";
import { Bot, Play } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

interface CapabilityCardProps {
  agentId: string;
  name: string;
  role: string;
  description: string;
  capabilities: string[];
  status: string;
  consumedVersion?: number;
  currentTask?: string | null;
  running?: boolean;
  onDispatch?: () => void;
  onAuditRuns?: () => void;
}

export function CapabilityCard({
  agentId,
  name,
  role,
  description,
  capabilities,
  status,
  consumedVersion,
  currentTask,
  running = false,
  onDispatch,
  onAuditRuns,
}: CapabilityCardProps) {
  return (
    <div className="p-5 rounded-lg bg-surface border border-border shadow-xs flex flex-col justify-between space-y-4 hover:border-primary/40 transition-all">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-md bg-primary-soft text-primary flex items-center justify-center border border-primary/20">
              <Bot className="w-4 h-4" />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-text-main">{name}</h4>
              <span className="text-[11px] text-text-muted font-medium">{role}</span>
            </div>
          </div>
          <StatusBadge kind={status === "ready" ? "success" : "neutral"} label={status} />
        </div>
        <p className="text-xs text-text-muted leading-relaxed line-clamp-2">{description}</p>
        {typeof consumedVersion === "number" && (
          <div className="flex items-center justify-between text-xs pt-2 border-t border-border">
            <span className="text-text-muted">Consumed Version:</span>
            <span className="font-mono font-semibold px-2 py-0.5 rounded bg-primary-soft text-primary border border-primary/20 text-[11px]">
              v{consumedVersion}
            </span>
          </div>
        )}
        <div className="flex flex-wrap gap-1">
          {capabilities.slice(0, 3).map((cap, i) => (
            <span key={i} className="px-1.5 py-0.5 rounded bg-canvas border border-border text-[10px] text-text-main">
              {cap}
            </span>
          ))}
        </div>
        {currentTask && (
          <div className="text-[11px] text-text-muted bg-surface-soft p-2 rounded-md border border-border/60">
            <strong className="text-text-main">Recent Task:</strong> {currentTask}
          </div>
        )}
      </div>
      <div className="pt-3 border-t border-border flex items-center justify-between gap-2">
        {onAuditRuns && (
          <button onClick={onAuditRuns} className="text-xs font-medium text-text-muted hover:text-text-main transition-colors">
            Audit Runs
          </button>
        )}
        {onDispatch && (
          <button
            onClick={onDispatch}
            disabled={running}
            className="px-3 py-1.5 rounded-md bg-primary hover:bg-primary-hover text-white text-xs font-semibold shadow-xs flex items-center gap-1.5 transition-colors disabled:opacity-50"
          >
            <Play className={`w-3.5 h-3.5 ${running ? "animate-spin" : ""}`} />
            <span>{running ? "Dispatching..." : "Dispatch Capability"}</span>
          </button>
        )}
      </div>
    </div>
  );
}
