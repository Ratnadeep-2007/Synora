"use client";

import React, { useState } from "react";
import { Bot, CheckCircle2 } from "lucide-react";
import { AgentDefinition, AgentExecutionRecord } from "@/lib/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { CapabilityCard } from "@/components/common/CapabilityCard";
import { AgentActivityFeed, AgentActivityItem } from "@/components/common/AgentActivityFeed";

interface AgentViewProps {
  capabilities: AgentDefinition[];
  stateVersion: number;
  excalidrawSyncLabel?: string;
  activity?: AgentActivityItem[];
  runsByAgent?: Record<string, AgentExecutionRecord[]>;
  onTriggerAgent: (agentId: string, taskDesc?: string) => Promise<void>;
  onInspectAgentRuns: (agentId: string) => Promise<AgentExecutionRecord[]>;
  onOpenRunDetail?: (run: AgentExecutionRecord) => void;
}

export function AgentView({
  capabilities,
  stateVersion,
  excalidrawSyncLabel = "Synchronized",
  activity = [],
  runsByAgent = {},
  onTriggerAgent,
  onInspectAgentRuns,
  onOpenRunDetail,
}: AgentViewProps) {
  const [runningCapabilityId, setRunningCapabilityId] = useState<string | null>(null);
  const [selectedCapabilityId, setSelectedCapabilityId] = useState<string | null>(null);
  const [runs, setRuns] = useState<AgentExecutionRecord[]>([]);

  const handleRun = async (capabilityId: string) => {
    try {
      setRunningCapabilityId(capabilityId);
      await onTriggerAgent(capabilityId);
      const fresh = await onInspectAgentRuns(capabilityId);
      setSelectedCapabilityId(capabilityId);
      setRuns(fresh);
    } finally {
      setRunningCapabilityId(null);
    }
  };

  const handleViewRuns = async (capabilityId: string) => {
    const cached = runsByAgent[capabilityId];
    if (cached) {
      setSelectedCapabilityId(capabilityId);
      setRuns(cached);
      return;
    }
    const fresh = await onInspectAgentRuns(capabilityId);
    setSelectedCapabilityId(capabilityId);
    setRuns(fresh);
  };

  return (
    <div className="space-y-6">
      <section className="p-5 rounded-xl bg-surface border border-border shadow-xs">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-primary text-white flex items-center justify-center">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold text-text-main">Synora Agent</h1>
                <StatusBadge kind="connected" label="Active" />
              </div>
              <p className="text-xs text-text-muted mt-1">
                One shared intelligence layer working inside this project context.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="px-2.5 py-1 rounded-md bg-canvas border border-border text-text-muted">
              State <strong className="text-primary">v{stateVersion}</strong>
            </span>
            <StatusBadge kind="synchronized" label={`Workspace: ${excalidrawSyncLabel}`} />
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-text-main">Capabilities</h2>
          <p className="text-xs text-text-muted mt-1">
            Synora uses these specialist capabilities when a task needs them.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {capabilities.length === 0 ? (
            <div className="col-span-full p-8 text-center bg-surface rounded-xl border border-border text-xs text-text-muted">
              No capabilities are available yet.
            </div>
          ) : (
            capabilities.map((capability) => (
              <CapabilityCard
                key={capability.agent_id}
                capabilityId={capability.agent_id}
                name={capability.name}
                role={capability.role}
                description={capability.description}
                capabilities={capability.capabilities}
                status={capability.status}
                currentTask={capability.current_task}
                running={runningCapabilityId === capability.agent_id}
                onDispatch={() => handleRun(capability.agent_id)}
                onAuditRuns={() => handleViewRuns(capability.agent_id)}
              />
            ))
          )}
        </div>
      </section>

      <AgentActivityFeed items={activity} title="Recent activity" />

      {selectedCapabilityId && (
        <section className="p-5 rounded-xl bg-surface border border-border shadow-xs">
          <div className="flex items-center justify-between pb-3 border-b border-border">
            <div>
              <h3 className="text-sm font-semibold text-text-main">Capability history</h3>
              <p className="text-[11px] text-text-muted mt-0.5">{selectedCapabilityId}</p>
            </div>
            <button onClick={() => { setSelectedCapabilityId(null); setRuns([]); }} className="text-xs text-text-muted hover:text-text-main">Close</button>
          </div>
          {runs.length === 0 ? (
            <div className="py-8 text-center text-xs text-text-muted flex flex-col items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-success" />
              No recorded runs for this capability.
            </div>
          ) : (
            <div className="divide-y divide-border">
              {runs.map((run) => (
                <button key={run.id} onClick={() => onOpenRunDetail?.(run)} className="w-full text-left py-3 hover:bg-canvas/60 transition-colors">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="font-mono font-semibold text-text-main">{run.id}</span>
                    <div className="flex items-center gap-2">
                      <StatusBadge kind={run.status === "completed" ? "success" : run.status === "failed" ? "failed" : "waiting"} label={run.status} />
                      <span className="text-text-muted">State v{run.project_state_version}</span>
                    </div>
                  </div>
                  <div className="mt-1 text-[11px] text-text-muted">
                    {run.output_references?.slice(0, 3).join(" · ") || "No recorded output"}
                  </div>
                  {run.error && <div className="mt-1 text-[11px] text-danger">{run.error}</div>}
                </button>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
