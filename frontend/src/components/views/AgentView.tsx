"use client";

import React, { useState } from "react";
import { Bot } from "lucide-react";
import { AgentDefinition, AgentExecutionRecord, ProjectAgent } from "@/lib/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { CapabilityCard } from "@/components/common/CapabilityCard";
import { AgentActivityFeed, AgentActivityItem } from "@/components/common/AgentActivityFeed";

interface AgentViewProps {
  agents: AgentDefinition[];
  projectAgent?: ProjectAgent | null;
  stateVersion: number;
  excalidrawSyncLabel?: string;
  activity?: AgentActivityItem[];
  runsByAgent?: Record<string, AgentExecutionRecord[]>;
  onTriggerAgent: (agentId: string, taskDesc?: string) => Promise<void>;
  onInspectAgentRuns: (agentId: string) => Promise<AgentExecutionRecord[]>;
  onOpenRunDetail?: (run: AgentExecutionRecord) => void;
}

export function AgentView({
  agents,
  projectAgent,
  stateVersion,
  excalidrawSyncLabel = "Synchronized",
  activity = [],
  runsByAgent = {},
  onTriggerAgent,
  onInspectAgentRuns,
  onOpenRunDetail,
}: AgentViewProps) {
  const [runningAgentId, setRunningAgentId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [runs, setRuns] = useState<AgentExecutionRecord[]>([]);

  const specialistAgents = agents.filter((ag) => ag.agent_id !== "project_agent");

  const handleRun = async (agentId: string) => {
    try {
      setRunningAgentId(agentId);
      await onTriggerAgent(agentId);
      const fresh = await onInspectAgentRuns(agentId);
      setSelectedAgentId(agentId);
      setRuns(fresh);
    } finally {
      setRunningAgentId(null);
    }
  };

  const handleViewRuns = async (agentId: string) => {
    const cached = runsByAgent[agentId];
    if (cached) {
      setSelectedAgentId(agentId);
      setRuns(cached);
      return;
    }
    const fresh = await onInspectAgentRuns(agentId);
    setSelectedAgentId(agentId);
    setRuns(fresh);
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header: ONE shared Synesis Agent for the active project */}
      <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-primary text-white flex items-center justify-center">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-text-main">SYNESIS AGENT</h1>
                <StatusBadge kind="connected" label="Active" pulse />
              </div>
              <p className="text-xs text-text-muted mt-0.5">
                Project: <strong className="text-text-main">{projectAgent?.name || "Active project"}</strong>
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="px-2 py-1 rounded-md bg-canvas border border-border font-mono text-text-muted">
              Project State: <strong className="text-primary">v{stateVersion}</strong>
            </span>
            <StatusBadge kind="synchronized" label="Context: Synchronized" />
            <StatusBadge kind="synchronized" label={`Excalidraw: ${excalidrawSyncLabel}`} />
          </div>
        </div>
      </div>

      {/* Capabilities */}
      <div className="space-y-4">
        <h2 className="text-sm font-semibold text-text-main uppercase tracking-wider">
          Capabilities
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {specialistAgents.length === 0 ? (
            <div className="col-span-full p-8 text-center text-xs text-text-muted bg-surface rounded-xl border border-border">
              No specialist capabilities registered for this project yet.
            </div>
          ) : (
            specialistAgents.map((ag) => (
              <CapabilityCard
                key={ag.agent_id}
                agentId={ag.agent_id}
                name={ag.name}
                role={ag.role}
                description={ag.description}
                capabilities={ag.capabilities}
                status={ag.status}
                consumedVersion={ag.current_project_state_version || stateVersion}
                currentTask={ag.current_task}
                running={runningAgentId === ag.agent_id}
                onDispatch={() => handleRun(ag.agent_id)}
                onAuditRuns={() => handleViewRuns(ag.agent_id)}
              />
            ))
          )}
        </div>
      </div>

      {/* Activity */}
      <AgentActivityFeed items={activity} title="Agent Activity" />

      {/* Run detail */}
      {selectedAgentId && (
        <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-border">
            <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
              Run detail: {selectedAgentId}
            </h3>
            <button
              onClick={() => {
                setSelectedAgentId(null);
                setRuns([]);
              }}
              className="text-xs text-text-muted hover:text-text-main font-medium"
            >
              Close
            </button>
          </div>
          {runs.length === 0 ? (
            <p className="text-xs text-text-muted py-4 text-center">No runs recorded for this capability.</p>
          ) : (
            <div className="space-y-3">
              {runs.map((run) => (
                <button
                  key={run.id}
                  onClick={() => onOpenRunDetail?.(run)}
                  className="w-full text-left p-4 rounded-lg border border-border bg-canvas/40 hover:bg-canvas transition-colors space-y-2"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="font-mono font-semibold text-text-main">{run.id}</span>
                    <div className="flex items-center gap-2">
                      <StatusBadge kind={run.status === "completed" ? "success" : run.status === "failed" ? "failed" : "waiting"} label={run.status} />
                      <span className="font-mono text-text-muted">State v{run.project_state_version}</span>
                      <span className="font-mono text-text-muted">{run.duration_ms} ms</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px] font-mono">
                    <div className="p-2 rounded bg-surface border border-border">
                      <span className="text-text-muted uppercase text-[9px] font-bold block mb-1">Inputs</span>
                      {run.input_references.slice(0, 4).map((ir, i) => (
                        <div key={i} className="text-text-main truncate">• {ir}</div>
                      ))}
                    </div>
                    <div className="p-2 rounded bg-surface border border-border">
                      <span className="text-text-muted uppercase text-[9px] font-bold block mb-1">Outputs</span>
                      {run.output_references.slice(0, 4).map((o, i) => (
                        <div key={i} className="text-primary truncate">• {o}</div>
                      ))}
                    </div>
                  </div>
                  <div className="text-[11px] text-text-muted">
                    Model: <span className="font-mono text-text-main">{run.model}</span> · Prompt:{" "}
                    <span className="font-mono text-text-main">{run.prompt_version}</span>
                    {run.error && <span className="text-danger block mt-1">Error: {run.error}</span>}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
