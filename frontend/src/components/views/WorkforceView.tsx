"use client";

import React, { useState } from "react";
import {
  Bot,
  Play,
  CheckCircle2,
  Clock,
  Shield,
  Layers,
  ArrowRight,
  Sparkles,
  Compass,
  Activity,
  Database,
  Cpu,
  RefreshCw,
  Terminal,
  Brain,
  ExternalLink,
} from "lucide-react";
import { AgentDefinition, AgentExecutionRecord, ProjectAgent, WorkspaceAgent } from "@/lib/types";

interface WorkforceViewProps {
  agents: AgentDefinition[];
  projectAgent?: ProjectAgent | null;
  workspaceAgent?: WorkspaceAgent | null;
  activeProjectName?: string;
  activeProjectId?: string;
  onSelectProject?: (projectId: string) => void;
  onTriggerAgent: (agentId: string, taskDesc?: string) => Promise<void>;
  onInspectAgentRuns: (agentId: string) => Promise<AgentExecutionRecord[]>;
  onSyncExcalidraw?: () => Promise<void>;
  onUpdateMemory?: (key: string, value: any) => Promise<void>;
}

export function WorkforceView({
  agents,
  projectAgent,
  workspaceAgent,
  activeProjectName,
  activeProjectId,
  onSelectProject,
  onTriggerAgent,
  onInspectAgentRuns,
  onSyncExcalidraw,
  onUpdateMemory,
}: WorkforceViewProps) {
  const [runningAgentId, setRunningAgentId] = useState<string | null>(null);
  const [isSyncingWorkspace, setIsSyncingWorkspace] = useState(false);
  const [selectedAgentRuns, setSelectedAgentRuns] = useState<{
    agentId: string;
    runs: AgentExecutionRecord[];
  } | null>(null);
  const [showMemory, setShowMemory] = useState(false);

  // Central Workspace Agent overseeing all projects
  const centralAgentName = workspaceAgent?.name || "Synesis Central Workspace Agent";
  const centralAgentDesc =
    "Single central intelligence entity handling and overseeing all projects across the workspace. Maintains portfolio coherence, cross-project dependencies, and orchestrates specialist capabilities while maintaining isolated state and living Excalidraw whiteboards for each project.";
  const managedProjects = workspaceAgent?.managed_projects || [];
  const stateVersion = projectAgent?.current_project_state_version || 1;
  const syncStatus = projectAgent?.workspace_sync_status || "synchronized";
  const memoryContext = workspaceAgent?.memory_context || projectAgent?.memory_context || {
    portfolio_priorities: [
      "Maintain cross-project coherence and governance",
      "Ensure individual Project States stay synchronized with evidence",
      "Maintain living visual Excalidraw workspaces for each project",
    ],
    domain_glossary: { "Evidence": "Immutable ingested fact", "Candidate": "Extracted proposition awaiting review" },
  };

  const specialistAgents = agents.filter((ag) => ag.agent_id !== "project_agent");

  const handleRun = async (agentId: string) => {
    try {
      setRunningAgentId(agentId);
      await onTriggerAgent(agentId);
      const runs = await onInspectAgentRuns(agentId);
      setSelectedAgentRuns({ agentId, runs });
    } finally {
      setRunningAgentId(null);
    }
  };

  const handleSyncWorkspace = async () => {
    if (!onSyncExcalidraw) return;
    try {
      setIsSyncingWorkspace(true);
      await onSyncExcalidraw();
    } finally {
      setIsSyncingWorkspace(false);
    }
  };

  const handleViewRuns = async (agentId: string) => {
    const runs = await onInspectAgentRuns(agentId);
    setSelectedAgentRuns({ agentId, runs });
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      <div>
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-primary text-white tracking-wide uppercase">
            One Central Agent Handling All Projects
          </span>
          <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
            Portfolio Oversight & Specialist Coordination
          </span>
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-text-main flex items-center gap-2.5 mt-2">
          <Brain className="w-6 h-6 text-primary" />
          <span>Central Workspace Agent Control Center</span>
        </h1>
        <p className="text-sm text-text-muted mt-1 max-w-3xl">
          One centralized <strong>Synesis Agent</strong> manages and coordinates all projects across your organization. It aligns portfolio context, directs five subordinated specialist capabilities, and continuously maintains living visual Excalidraw whiteboards for each project.
        </p>
      </div>

      {/* TOP: Dedicated Central Workspace Agent Card */}
      <div className="p-6 rounded-2xl bg-gradient-to-br from-primary-soft/40 via-surface to-surface border-2 border-primary/40 shadow-sm space-y-6">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 rounded-2xl bg-primary text-white flex items-center justify-center font-bold shadow-md shrink-0">
              <Compass className="w-7 h-7" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-bold text-text-main">{centralAgentName}</h2>
                <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-bold bg-primary text-white">
                  Central Intelligence
                </span>
                <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                  Overseeing {managedProjects.length || 1} Projects
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-canvas border border-border text-text-muted">
                  ID: {workspaceAgent?.id || "wagent_default"}
                </span>
              </div>
              <p className="text-xs text-text-muted mt-1 leading-relaxed max-w-2xl">
                {centralAgentDesc}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={handleSyncWorkspace}
              disabled={isSyncingWorkspace}
              className="px-3.5 py-2 rounded-lg bg-surface hover:bg-surface-soft border border-primary/30 text-primary text-xs font-semibold shadow-xs flex items-center gap-1.5 transition-colors disabled:opacity-50"
              title="Synchronize active project state and decisions to its living Excalidraw workspace"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isSyncingWorkspace ? "animate-spin" : ""}`} />
              <span>{isSyncingWorkspace ? "Syncing..." : "Sync Active Whiteboard"}</span>
            </button>

            <button
              onClick={() => handleRun("project_agent")}
              disabled={runningAgentId === "project_agent"}
              className="px-4 py-2 rounded-lg bg-primary hover:bg-primary-hover text-white text-xs font-semibold shadow-xs flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              <Play className={`w-3.5 h-3.5 ${runningAgentId === "project_agent" ? "animate-spin" : ""}`} />
              <span>{runningAgentId === "project_agent" ? "Coordinating..." : "Trigger Portfolio Coordination"}</span>
            </button>
          </div>
        </div>

        {/* Portfolio Projects Scope Pill Selector */}
        {managedProjects.length > 0 && (
          <div className="pt-3 border-t border-border/60 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-[11px] font-bold uppercase tracking-wider text-text-muted">
                Managed Projects Portfolio (Click to switch focus)
              </span>
              <span className="text-[11px] font-mono text-primary font-semibold">
                Focused: {activeProjectId || "none"}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {managedProjects.map((p) => {
                const isFocused = p.id === activeProjectId;
                return (
                  <button
                    key={p.id}
                    onClick={() => onSelectProject && onSelectProject(p.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border flex items-center gap-2 transition-all ${
                      isFocused
                        ? "bg-primary text-white border-primary shadow-xs font-semibold"
                        : "bg-surface text-text-main border-border hover:bg-canvas"
                    }`}
                  >
                    <span className={`w-2 h-2 rounded-full ${isFocused ? "bg-white" : "bg-primary"}`} />
                    <span>{p.name}</span>
                    <span
                      className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                        isFocused ? "bg-white/20 text-white" : "bg-canvas text-text-muted"
                      }`}
                    >
                      v{p.current_state_version}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* 4 Architectural Isolation Metrics */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-4 border-t border-border/60 text-xs">
          {/* 1. Context Boundary */}
          <div className="p-3 rounded-xl bg-surface border border-border space-y-1">
            <div className="flex items-center justify-between text-text-muted">
              <span className="text-[10px] font-bold uppercase tracking-wider">Active Project Focus</span>
              <Shield className="w-3.5 h-3.5 text-primary" />
            </div>
            <p className="text-text-main font-semibold text-xs truncate">{activeProjectName || activeProjectId || "No project selected"}</p>
            <span className="text-[11px] text-text-muted font-mono block">
              id: {activeProjectId || "—"}
            </span>
          </div>

          {/* 2. Isolated Memory */}
          <div className="p-3 rounded-xl bg-surface border border-border space-y-1">
            <div className="flex items-center justify-between text-text-muted">
              <span className="text-[10px] font-bold uppercase tracking-wider">Portfolio Memory</span>
              <Brain className="w-3.5 h-3.5 text-primary" />
            </div>
            <div className="flex items-center justify-between">
              <p className="text-text-main font-semibold text-xs">
                {Object.keys(memoryContext).length} Knowledge Blocks
              </p>
              <button
                onClick={() => setShowMemory(!showMemory)}
                className="text-[10px] text-primary hover:underline font-semibold"
              >
                {showMemory ? "Hide" : "Inspect"}
              </button>
            </div>
            <span className="text-[11px] text-text-muted block">
              Cross-project insights & priorities
            </span>
          </div>

          {/* 3. Living Excalidraw Workspace */}
          <div className="p-3 rounded-xl bg-surface border border-border space-y-1">
            <div className="flex items-center justify-between text-text-muted">
              <span className="text-[10px] font-bold uppercase tracking-wider">Living Whiteboard</span>
              <Sparkles className="w-3.5 h-3.5 text-emerald-500" />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <p className="text-text-main font-semibold text-xs capitalize">{syncStatus}</p>
            </div>
            <span className="text-[11px] text-text-muted font-mono truncate block">
              artifact: {projectAgent?.living_workspace_artifact_id || "art_excal_default"}
            </span>
          </div>

          {/* 4. Connected Sources & Tools */}
          <div className="p-3 rounded-xl bg-surface border border-border space-y-1">
            <div className="flex items-center justify-between text-text-muted">
              <span className="text-[10px] font-bold uppercase tracking-wider">Connected Tools</span>
              <Database className="w-3.5 h-3.5 text-primary" />
            </div>
            <div className="flex items-center gap-1.5 flex-wrap">
              {(workspaceAgent?.connected_tools || ["google_meet", "whatsapp", "excalidraw"]).map((tool) => (
                <span key={tool} className="px-1.5 py-0.5 rounded bg-surface-soft border border-border text-[10px] font-mono text-text-main">
                  {tool.replace("_", " ")}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Collapsible Memory Context Drawer */}
        {showMemory && (
          <div className="p-4 rounded-xl bg-canvas border border-border space-y-2 animate-in fade-in duration-150">
            <div className="flex items-center justify-between text-xs pb-1 border-b border-border">
              <span className="font-semibold text-text-main flex items-center gap-1.5">
                <Brain className="w-3.5 h-3.5 text-primary" />
                <span>Isolated Project Agent Memory Context (`memory_context` JSON)</span>
              </span>
              <span className="text-[10px] font-mono text-text-muted">PostgreSQL Stored</span>
            </div>
            <pre className="font-mono text-[11px] text-text-main overflow-x-auto p-3 rounded-lg bg-surface border border-border leading-relaxed">
              {JSON.stringify(memoryContext, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* SPECIALIST CAPABILITIES HIERARCHY */}
      <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h3 className="text-base font-bold text-text-main flex items-center gap-2">
              <Layers className="w-4 h-4 text-primary" />
              <span>Subordinated Specialist Capabilities & Execution Modules</span>
            </h3>
            <p className="text-xs text-text-muted mt-0.5">
              These specialists are capabilities coordinated by the Project Agent. They consume authoritative Project State and generate proposals without direct mutation privileges.
            </p>
          </div>
          <span className="text-xs text-text-muted font-mono shrink-0">
            Consuming Project State v{stateVersion}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {specialistAgents.map((ag) => {
            const isRunning = runningAgentId === ag.agent_id;

            return (
              <div
                key={ag.agent_id}
                className="p-5 rounded-xl bg-surface border border-border shadow-xs flex flex-col justify-between space-y-4 hover:border-primary/40 transition-all group"
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-lg bg-primary-soft text-primary flex items-center justify-center font-bold text-xs border border-primary/20 group-hover:scale-105 transition-transform">
                        <Bot className="w-4 h-4" />
                      </div>
                      <div>
                        <h4 className="text-sm font-semibold text-text-main">{ag.name}</h4>
                        <span className="text-[11px] text-text-muted font-medium">{ag.role}</span>
                      </div>
                    </div>

                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase font-semibold border ${
                        ag.status === "ready"
                          ? "bg-success/10 text-success border-success/20"
                          : "bg-canvas text-text-muted border-border"
                      }`}
                    >
                      {ag.status}
                    </span>
                  </div>

                  <p className="text-xs text-text-muted leading-relaxed line-clamp-2">
                    {ag.description}
                  </p>

                  {/* Consumed State Version */}
                  <div className="flex items-center justify-between text-xs pt-2 border-t border-border">
                    <span className="text-text-muted">Consumed Version:</span>
                    <span className="font-mono font-semibold px-2 py-0.5 rounded bg-primary-soft text-primary border border-primary/20 text-[11px]">
                      v{ag.current_project_state_version || stateVersion}
                    </span>
                  </div>

                  {/* Capabilities Tags */}
                  <div className="p-2.5 rounded-lg bg-canvas text-[11px] space-y-1">
                    <span className="text-[10px] uppercase font-bold text-text-muted block">
                      Specialist Capabilities
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {ag.capabilities.slice(0, 3).map((cap, i) => (
                        <span
                          key={i}
                          className="px-1.5 py-0.5 rounded bg-surface border border-border text-[10px] text-text-main"
                        >
                          {cap}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Recent Task Output */}
                  {ag.current_task && (
                    <div className="text-[11px] text-text-muted bg-surface-soft p-2 rounded-lg border border-border/60">
                      <strong className="text-text-main">Recent Task:</strong> {ag.current_task}
                    </div>
                  )}
                </div>

                {/* Actions */}
                <div className="pt-3 border-t border-border flex items-center justify-between gap-2">
                  <button
                    onClick={() => handleViewRuns(ag.agent_id)}
                    className="text-xs font-medium text-text-muted hover:text-text-main transition-colors"
                  >
                    Audit Runs
                  </button>

                  <button
                    onClick={() => handleRun(ag.agent_id)}
                    disabled={isRunning}
                    className="px-3 py-1.5 rounded-md bg-primary hover:bg-primary-hover text-white text-xs font-semibold shadow-xs flex items-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    <Play className={`w-3.5 h-3.5 ${isRunning ? "animate-spin" : ""}`} />
                    <span>{isRunning ? "Dispatching..." : "Dispatch Capability"}</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Execution Audit Trail Modal / Drawer */}
      {selectedAgentRuns && (
        <div className="p-6 rounded-xl bg-surface border border-border shadow-xs space-y-4 animate-in fade-in duration-150">
          <div className="flex items-center justify-between pb-3 border-b border-border">
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-primary" />
              <h3 className="text-sm font-semibold text-text-main uppercase tracking-wider">
                Execution Audit Trail: {selectedAgentRuns.agentId}
              </h3>
            </div>
            <button
              onClick={() => setSelectedAgentRuns(null)}
              className="text-xs text-text-muted hover:text-text-main font-medium"
            >
              Close Trail
            </button>
          </div>

          <div className="space-y-4">
            {selectedAgentRuns.runs.length === 0 ? (
              <div className="py-6 text-center text-xs text-text-muted">
                No runs recorded yet for this capability.
              </div>
            ) : (
              selectedAgentRuns.runs.map((run) => (
                <div
                  key={run.id}
                  className="p-4 rounded-lg border border-border bg-canvas/40 space-y-3 text-xs"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 font-mono text-[11px]">
                      <span className="font-semibold text-text-main">{run.id}</span>
                      <span className="px-1.5 py-0.5 rounded bg-surface border border-border">
                        State v{run.project_state_version}
                      </span>
                      <span className="px-1.5 py-0.5 rounded bg-primary-soft text-primary font-semibold">
                        {run.output_type}
                      </span>
                    </div>

                    <div className="flex items-center gap-3 text-text-muted">
                      <span>{run.duration_ms} ms</span>
                      <span suppressHydrationWarning>{new Date(run.created_at).toLocaleTimeString()}</span>
                    </div>
                  </div>

                  {/* Input / Output Provenance */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px] font-mono">
                    <div className="p-2 rounded bg-surface border border-border">
                      <span className="text-text-muted uppercase text-[9px] font-bold block mb-1">
                        Input References
                      </span>
                      <div className="space-y-0.5">
                        {run.input_references.map((ir, i) => (
                          <div key={i} className="text-text-main truncate">
                            • {ir}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="p-2 rounded bg-surface border border-border">
                      <span className="text-text-muted uppercase text-[9px] font-bold block mb-1">
                        Output References
                      </span>
                      <div className="space-y-0.5">
                        {run.output_references.map((or, i) => (
                          <div key={i} className="text-primary truncate">
                            • {or}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Structured Payload Preview */}
                  <div className="p-3 rounded bg-surface border border-border/80 text-xs">
                    <span className="text-[10px] uppercase font-mono font-bold text-text-muted block mb-1">
                      Structured Output Payload
                    </span>
                    <pre className="font-mono text-[11px] text-text-main overflow-x-auto whitespace-pre-wrap leading-relaxed">
                      {JSON.stringify(run.output_payload, null, 2)}
                    </pre>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
