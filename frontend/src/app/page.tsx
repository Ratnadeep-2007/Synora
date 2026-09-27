"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import { Shell, NavTab, NotificationItem } from "@/components/layout/Shell";
import { OverviewView } from "@/components/views/OverviewView";
import { ProjectStateView } from "@/components/views/ProjectStateView";
import { ArchitectureView } from "@/components/views/ArchitectureView";
import { MeetingsView } from "@/components/views/MeetingsView";
import { MeetingDetailView } from "@/components/views/MeetingDetailView";
import { EvidenceView } from "@/components/views/EvidenceView";
import { ConflictCenterView } from "@/components/views/ConflictCenterView";
import { DecisionsView } from "@/components/views/DecisionsView";
import { AgentView } from "@/components/views/AgentView";
import { SourcesView } from "@/components/views/SourcesView";
import { SettingsView } from "@/components/views/SettingsView";
import { EvidenceDrawer } from "@/components/common/EvidenceDrawer";
import { CommandPalette, CommandAction } from "@/components/common/CommandPalette";
import { api, getFrontendUserId } from "@/lib/api";
import {
  AgentDefinition,
  AgentExecutionRecord,
  CandidateKnowledgeItem,
  Conflict,
  EvidenceItem,
  ExcalidrawArtifact,
  ExcalidrawProposal,
  MeetingItem,
  Project,
  ProjectAgent,
  ProjectState,
  ProjectStateVersion,
  SourceConnection,
  WorkspaceAgent,
} from "@/lib/types";

export default function Home() {
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaceName, setWorkspaceName] = useState<string>("Workspace");
  const [currentTab, setCurrentTab] = useState<NavTab>("overview");
  const [selectedMeetingId, setSelectedMeetingId] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Core Data State
  const [state, setState] = useState<ProjectState | null>(null);
  const [history, setHistory] = useState<ProjectStateVersion[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [meetings, setMeetings] = useState<MeetingItem[]>([]);
  const [candidates, setCandidates] = useState<CandidateKnowledgeItem[]>([]);
  const [allEvidence, setAllEvidence] = useState<EvidenceItem[]>([]);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [connections, setConnections] = useState<SourceConnection[]>([]);
  const [meetingDetail, setMeetingDetail] = useState<any>(null);
  const [excalArtifact, setExcalArtifact] = useState<ExcalidrawArtifact | null>(null);
  const [excalProposals, setExcalProposals] = useState<ExcalidrawProposal[]>([]);
  const [projectAgent, setProjectAgent] = useState<ProjectAgent | null>(null);
  const [workspaceAgent, setWorkspaceAgent] = useState<WorkspaceAgent | null>(null);

  // Event-driven pipeline state
  const [meetSubscriptions, setMeetSubscriptions] = useState<any[]>([]);
  const [meetEvents, setMeetEvents] = useState<any[]>([]);
  const [unassignedMeetings, setUnassignedMeetings] = useState<MeetingItem[]>([]);

  // Evidence Drawer State
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerData, setDrawerData] = useState<{
    title: string;
    contextType: string;
    evidenceItems: EvidenceItem[];
    status?: string;
    relatedChangeRef?: string;
  }>({
    title: "",
    contextType: "",
    evidenceItems: [],
  });

  // Reload everything for the active project
  const refreshAll = useCallback(async () => {
    try {
      const projListData = await api.getProjects().catch(() => [] as Project[]);
      setProjects(projListData);

      const activeId = currentProjectId || projListData[0]?.id || null;
      if (!activeId) {
        setState(null);
        setHistory([]);
        setConflicts([]);
        setCandidates([]);
        setAllEvidence([]);
        setAgents([]);
        setExcalArtifact(null);
        setExcalProposals([]);
        setProjectAgent(null);
        return;
      }
      if (!currentProjectId) setCurrentProjectId(activeId);

      const [
        stateData,
        histData,
        confData,
        meetsData,
        candsData,
        evData,
        agData,
        connsData,
        excalData,
        propsData,
        paData,
        wsAgentData,
        subsData,
        eventsData,
        unassignedData,
      ] = await Promise.allSettled([
        api.getProjectState(activeId),
        api.getProjectHistory(activeId),
        api.getConflicts(activeId),
        api.getMeetings(),
        api.getCandidates(activeId),
        api.getEvidence(activeId),
        api.getWorkforceAgents(activeId),
        api.getSourceConnections(),
        api.getExcalidrawArtifact(activeId),
        api.getExcalidrawProposals(activeId),
        api.getProjectAgent(activeId),
        api.getWorkspaceAgent(),
        api.listMeetSubscriptions().catch(() => []),
        api.listMeetEvents(undefined, 20).catch(() => []),
        api.listUnassignedMeetings(20).catch(() => []),
      ]);

      if (stateData.status === "fulfilled") setState(stateData.value);
      if (histData.status === "fulfilled") setHistory(histData.value);
      if (confData.status === "fulfilled") setConflicts(confData.value);
      if (meetsData.status === "fulfilled") setMeetings(meetsData.value);
      if (candsData.status === "fulfilled") setCandidates(candsData.value);
      if (evData.status === "fulfilled") setAllEvidence(evData.value);
      if (agData.status === "fulfilled") setAgents(agData.value);
      if (connsData.status === "fulfilled") setConnections(connsData.value);
      if (excalData.status === "fulfilled") setExcalArtifact(excalData.value);
      if (propsData.status === "fulfilled") setExcalProposals(propsData.value);
      if (paData.status === "fulfilled") setProjectAgent(paData.value);
      if (wsAgentData.status === "fulfilled") setWorkspaceAgent(wsAgentData.value);
      if (subsData.status === "fulfilled") setMeetSubscriptions(subsData.value);
      if (eventsData.status === "fulfilled") setMeetEvents(eventsData.value);
      if (unassignedData.status === "fulfilled") setUnassignedMeetings(unassignedData.value);
    } catch (err) {
      console.error("Failed to load project context:", err);
    }
  }, [currentProjectId]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  // Load meeting detail when selected
  useEffect(() => {
    if (!selectedMeetingId) {
      setMeetingDetail(null);
      return;
    }
    api
      .getMeetingDetail(selectedMeetingId)
      .then((data) => setMeetingDetail(data))
      .catch((err) => console.error("Failed to fetch meeting detail:", err));
  }, [selectedMeetingId]);

  // Handlers
  const handleOpenEvidence = (
    title: string,
    contextType: string,
    evidenceIds: string[],
    status = "Authoritative"
  ) => {
    const items = allEvidence.filter((e) => evidenceIds.includes(e.id));

    setDrawerData({
      title,
      contextType,
      evidenceItems: items,
      status,
      relatedChangeRef: evidenceIds.join(", ") || undefined,
    });
    setDrawerOpen(true);
  };

  const handleCreateProject = async (name: string, description?: string) => {
    try {
      const newProj = await api.createProject(name, description);
      setCurrentProjectId(newProj.id);
      setCurrentTab("excalidraw");
      await refreshAll();
    } catch (err: any) {
      alert(`Project creation failed: ${err.message}`);
    }
  };

  const requireProject = (): string | null => {
    if (!currentProjectId) {
      alert("Create or select a project first.");
      return null;
    }
    return currentProjectId;
  };

  const handleProcessPipeline = async (meetingId: string) => {
    const projectId = requireProject();
    if (!projectId) return;
    await api.processMeetingPipeline(projectId, meetingId);
    try {
      await api.syncProjectAgentExcalidraw(projectId);
    } catch {
      // workspace sync can proceed non-blockingly
    }
    await refreshAll();
  };

  const handleReviewConflict = async (
    conflictId: string,
    action: "approve" | "reject" | "mark_unresolved",
    reason?: string,
    note?: string
  ) => {
    const projectId = requireProject();
    if (!projectId) return;
    await api.reviewConflict(projectId, conflictId, action, reason, note);
    try {
      await api.syncProjectAgentExcalidraw(projectId);
    } catch {
      // workspace sync can proceed non-blockingly
    }
    await refreshAll();
  };

  const handleRollback = async (version: number) => {
    const projectId = requireProject();
    if (!projectId) return;
    await api.rollbackState(projectId, version, `Rollback requested via Project State UI`);
    try {
      await api.syncProjectAgentExcalidraw(projectId);
    } catch {
      // workspace sync can proceed non-blockingly
    }
    await refreshAll();
  };

  const handleTriggerAgent = async (agentId: string, taskDesc?: string) => {
    const projectId = requireProject();
    if (!projectId) return;
    await api.triggerAgentRun(projectId, agentId, taskDesc);
    try {
      await api.syncProjectAgentExcalidraw(projectId);
    } catch {
      // workspace sync can proceed non-blockingly
    }
    await refreshAll();
  };

  const handleInspectAgentRuns = async (agentId: string): Promise<AgentExecutionRecord[]> => {
    const projectId = requireProject();
    if (!projectId) return [];
    return api.getAgentRuns(projectId, agentId);
  };

  const handleGenerateExcalProposal = async (stateVersion?: number) => {
    const projectId = requireProject();
    if (!projectId) return;
    try {
      await api.generateExcalidrawProposal(projectId, stateVersion, "Manual diagram alignment request");
      await refreshAll();
    } catch (err: any) {
      alert(`Failed to generate diagram proposal: ${err.message}`);
    }
  };

  const handleAiGenerateVisuals = async (focusPrompt?: string, directApply: boolean = false) => {
    const projectId = requireProject();
    if (!projectId) return;
    try {
      await api.generateAiExcalidrawDiagram(projectId, focusPrompt, directApply);
      await refreshAll();
    } catch (err: any) {
      alert(`AI Visual Generation failed: ${err.message}`);
    }
  };


  const handleReviewExcalProposal = async (proposalId: string, action: "approve" | "reject", reason?: string) => {
    const projectId = requireProject();
    if (!projectId) return;
    try {
      await api.reviewExcalidrawProposal(projectId, proposalId, action, reason);
      try {
        await api.syncProjectAgentExcalidraw(projectId);
      } catch {
        // non-blocking
      }
      await refreshAll();
    } catch (err: any) {
      alert(`Review failed: ${err.message}`);
    }
  };

  const handleIngestScene = async (scene: { name: string; elements: any[]; app_state?: any }) => {
    const projectId = requireProject();
    if (!projectId) return;
    try {
      await api.ingestExcalidrawDiagram(projectId, scene);
      await refreshAll();
    } catch (err: any) {
      alert(`Ingest failed: ${err.message}`);
    }
  };

  const handleSyncGoogleMeet = async () => {
    // Manual reconciliation: recovers events missed during outages or failed
    // processing. Automatic sync runs via Workspace Events + Pub/Sub.
    try {
      const res = await api.reconcileMeet({
        max_conferences: 10,
        project_id: currentProjectId || undefined,
      });
      const summary = `Reconciliation complete: ${res.total_events_processed || 0} recorded events processed, ` +
        `${res.total_conferences_synced || 0} conferences reconciled.`;
      alert(summary);
      await refreshAll();
    } catch (err: any) {
      const msg = err.message || "";
      if (
        msg.includes("403") ||
        msg.includes("permission") ||
        msg.includes("scope") ||
        msg.includes("re-authorize") ||
        msg.includes("authorize") ||
        msg.includes("connection_not_found") ||
        msg.includes("No active Google connection")
      ) {
        const confirmAuth = window.confirm(
          `Google Meet Authorization Notice:\n\n${msg}\n\nWould you like to authorize Google with Meet permissions now?`
        );
        if (confirmAuth) {
          const uid = getFrontendUserId();
          window.location.href = `http://localhost:8000/auth/google?user_id=${encodeURIComponent(uid)}&return_to=http://localhost:3000`;
        }
      } else {
        alert(`Google Meet reconciliation: ${msg}`);
      }
    }
  };

  const handleIngestTranscript = async (payload: {
    title: string;
    raw_transcript: string;
    provider?: string;
  }) => {
    const projectId = requireProject();
    if (!projectId) return;
    try {
      const res = await api.ingestTranscript({
        project_id: projectId,
        title: payload.title,
        provider: payload.provider || "manual_transcript",
        raw_transcript: payload.raw_transcript,
        auto_process: true,
      });
      alert(res.message || "Transcript ingested and processed successfully!");
      await refreshAll();
    } catch (err: any) {
      alert(`Transcript ingestion failed: ${err.message}`);
    }
  };

  const handleSyncLivingWorkspace = async () => {
    const projectId = requireProject();
    if (!projectId) return;
    try {
      const res = await api.syncProjectAgentExcalidraw(projectId);
      alert(res.message || "Living visual workspace synchronized!");
      await refreshAll();
    } catch (err: any) {
      alert(`Living workspace sync failed: ${err.message}`);
    }
  };

  const handleSyncSlack = async (channel: string) => {
    const projectId = requireProject();
    if (!projectId) return;
    try {
      const res = await api.syncSlackChannel(channel, projectId);
      alert(`Synced ${res.messages_fetched || 0} messages from Slack #${channel}.`);
      await refreshAll();
    } catch (err: any) {
      alert(`Slack channel sync failed: ${err.message}`);
    }
  };

  const handleOpenMeetingFromEvidence = (meetingId: string) => {
    setSelectedMeetingId(meetingId);
    setCurrentTab("meetings");
  };

  const handleAssignMeetingProject = async (meetingId: string, projectId: string) => {
    try {
      await api.assignMeetingProject(meetingId, projectId);
      await refreshAll();
    } catch (err: any) {
      alert(`Project mapping failed: ${err.message}`);
    }
  };

  const openConflictsCount = conflicts.filter(
    (c) => c.status === "open" || c.status === "under_review"
  ).length;

  const pendingExcalProposals = excalProposals.filter((p) => p.status === "pending").length;

  const googleConn = connections.find((c) => c.provider === "google");

  const activeSubscriptions = meetSubscriptions.filter(
    (s) => s.status === "active" || s.status === "expiring"
  );
  const pendingMeetEvents = meetEvents.filter(
    (e) => !["processed", "duplicate"].includes(e.status)
  );
  const lastMeetEventAt = meetEvents.length > 0 ? meetEvents[0].received_at || null : null;

  const autoSyncStatus = {
    connected: Boolean(googleConn && googleConn.status === "active"),
    active: activeSubscriptions.length > 0,
    lastEventAt: lastMeetEventAt,
    pendingCount: pendingMeetEvents.length,
    subscriptionsCount: activeSubscriptions.length,
  };

  const notifications: NotificationItem[] = useMemo(() => {
    const items: NotificationItem[] = [];
    if (openConflictsCount > 0) {
      items.push({
        title: `${openConflictsCount} conflict${openConflictsCount === 1 ? "" : "s"} require${openConflictsCount === 1 ? "s" : ""} review`,
        detail: "Open the Conflict Center to approve or reject proposed changes.",
      });
    }
    if (pendingExcalProposals > 0) {
      items.push({
        title: `${pendingExcalProposals} Excalidraw proposal${pendingExcalProposals === 1 ? "" : "s"} pending review`,
        detail: "Visual workspace updates are awaiting human approval.",
      });
    }
    if (!googleConn || googleConn.status !== "active") {
      items.push({
        title: "Google Meet source not connected",
        detail: "Connect Google Meet from Sources to enable transcript sync.",
      });
    }
    return items;
  }, [openConflictsCount, pendingExcalProposals, googleConn]);

  const agentActivity = useMemo(() => {
    const items: Array<{ time: string; text: string }> = [];
    history.slice(0, 4).forEach((v) => {
      items.push({
        time: v.created_at ? new Date(v.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—",
        text: `Project State changed to v${v.version_number} — ${v.reason}`,
      });
    });
    conflicts.slice(0, 4).forEach((c) => {
      items.push({
        time: c.created_at ? new Date(c.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—",
        text: `Conflict detected: ${c.title} — awaiting approval`,
      });
    });
    return items.slice(0, 8);
  }, [history, conflicts]);

  const paletteActions: CommandAction[] = useMemo(
    () => [
      { id: "go-overview", label: "Open Overview", run: () => setCurrentTab("overview") },
      { id: "go-state", label: "View current state", hint: "Project State", run: () => setCurrentTab("state") },
      { id: "go-excalidraw", label: "Open Excalidraw", run: () => setCurrentTab("excalidraw") },
      { id: "go-meetings", label: "Open recent meeting", hint: meetings[0]?.title || "Meetings", run: () => {
        if (meetings[0]) {
          setSelectedMeetingId(meetings[0].id);
          setCurrentTab("meetings");
        } else {
          setCurrentTab("meetings");
        }
      } },
      { id: "go-evidence", label: "Search project evidence", hint: "Evidence", run: () => setCurrentTab("evidence") },
      { id: "go-decisions", label: "Open decisions", run: () => setCurrentTab("decisions") },
      { id: "go-conflicts", label: "Review conflicts", hint: `${openConflictsCount} open`, run: () => setCurrentTab("conflicts") },
      { id: "go-agent", label: "Open agent", run: () => setCurrentTab("agent") },
      { id: "go-sources", label: "Connect source", hint: "Sources", run: () => setCurrentTab("sources") },
      { id: "sync-meet", label: "Sync Google Meet now", run: () => { handleSyncGoogleMeet(); } },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [meetings, openConflictsCount, currentProjectId]
  );

  const activeProject = projects.find((p) => p.id === currentProjectId) || null;

  const excalSyncStatus = pendingExcalProposals > 0 ? "pending" : "synchronized";

  return (
    <Shell
      currentTab={currentTab}
      onTabChange={(tab) => {
        setSelectedMeetingId(null);
        setCurrentTab(tab);
      }}
      projectVersion={state?.current_version || 1}
      openConflictsCount={openConflictsCount}
      projects={projects}
      currentProjectId={currentProjectId || undefined}
      activeProject={activeProject}
      workspaceName={workspaceName}
      workspaceAgent={workspaceAgent}
      notifications={notifications}
      onSelectProject={(pId) => {
        setSelectedMeetingId(null);
        setCurrentProjectId(pId);
      }}
      onCreateProject={handleCreateProject}
      onOpenCommandPalette={() => setPaletteOpen(true)}
    >
      {/* Overview Screen */}
      {currentTab === "overview" && (
        <OverviewView
          state={state}
          conflicts={conflicts}
          excalidraw={
            excalArtifact
              ? {
                  name: excalArtifact.name,
                  version: excalArtifact.version,
                  updatedAt: excalArtifact.updated_at,
                  decisionsCount: state?.decisions?.length || 0,
                  requirementsCount: state?.requirements?.length || 0,
                  pendingCount: pendingExcalProposals,
                }
              : null
          }
          activityItems={agentActivity}
          onNavigateToTab={(tab: NavTab) => setCurrentTab(tab)}
          onSelectConflict={() => setCurrentTab("conflicts")}
        />
      )}

      {/* Project State Screen */}
      {currentTab === "state" && (
        <ProjectStateView
          state={state}
          history={history}
          onRollback={handleRollback}
          onOpenEvidence={handleOpenEvidence}
        />
      )}

      {/* Excalidraw Screen */}
      {currentTab === "excalidraw" && (
        <ArchitectureView
          artifact={excalArtifact}
          proposals={excalProposals}
          currentStateVersion={state?.current_version || 1}
          decisions={state?.decisions || []}
          syncStatus={excalSyncStatus}
          lastSyncAt={excalArtifact?.updated_at || null}
          onRetrySync={handleSyncLivingWorkspace}
          onGenerateProposal={handleGenerateExcalProposal}
          onReviewProposal={handleReviewExcalProposal}
          onIngestScene={handleIngestScene}
          onSyncLivingWorkspace={handleSyncLivingWorkspace}
          onAiGenerateVisuals={handleAiGenerateVisuals}
        />
      )}

      {/* Meetings Screen & Detail View */}
      {currentTab === "meetings" &&
        (!selectedMeetingId ? (
          <MeetingsView
            meetings={meetings}
            autoSyncStatus={autoSyncStatus}
            onSelectMeeting={(mId) => setSelectedMeetingId(mId)}
            onProcessPipeline={handleProcessPipeline}
            onSyncGoogleMeet={handleSyncGoogleMeet}
            onIngestTranscript={handleIngestTranscript}
          />
        ) : (
          <MeetingDetailView
            meetingId={selectedMeetingId}
            meetingData={meetingDetail}
            candidates={candidates.filter(
              (c) => !c.meeting_id || c.meeting_id === selectedMeetingId
            )}
            onBack={() => setSelectedMeetingId(null)}
            onOpenEvidence={handleOpenEvidence}
            onNavigateToTab={(tab: NavTab) => setCurrentTab(tab)}
          />
        ))}

      {/* Evidence Screen */}
      {currentTab === "evidence" && (
        <EvidenceView
          evidence={allEvidence}
          onOpenEvidenceDetail={(item) =>
            handleOpenEvidence(item.content.slice(0, 80), "Evidence", [item.id])
          }
          onOpenMeeting={handleOpenMeetingFromEvidence}
          onNavigateToState={() => setCurrentTab("state")}
        />
      )}

      {/* Decisions Screen */}
      {currentTab === "decisions" && (
        <DecisionsView
          state={state}
          conflicts={conflicts}
          onOpenEvidence={handleOpenEvidence}
          onReviewConflict={handleReviewConflict}
        />
      )}

      {/* Conflict Center Screen */}
      {currentTab === "conflicts" && (
        <ConflictCenterView
          conflicts={conflicts}
          onReviewConflict={handleReviewConflict}
          onOpenEvidence={handleOpenEvidence}
        />
      )}

      {/* Agent Screen */}
      {currentTab === "agent" && (
        <AgentView
          agents={agents}
          projectAgent={projectAgent}
          stateVersion={state?.current_version || 1}
          excalidrawSyncLabel={excalSyncStatus === "pending" ? "Pending review" : "Synchronized"}
          activity={agentActivity}
          onTriggerAgent={handleTriggerAgent}
          onInspectAgentRuns={handleInspectAgentRuns}
        />
      )}

      {/* Sources Screen */}
      {currentTab === "sources" && (
        <SourcesView
          connections={connections}
          subscriptionsActive={activeSubscriptions.length > 0}
          lastMeetEventAt={lastMeetEventAt}
          pendingMeetEvents={pendingMeetEvents.length}
          onConnectGoogle={() => {
            const uid = getFrontendUserId();
            window.location.href = `http://localhost:8000/auth/google?user_id=${encodeURIComponent(uid)}&return_to=http://localhost:3000`;
          }}
          onSyncGoogleMeet={handleSyncGoogleMeet}
          onReconcileMeet={handleSyncGoogleMeet}
          onSyncSlack={handleSyncSlack}
          onNavigateToArchitecture={() => setCurrentTab("excalidraw")}
          onRefreshData={refreshAll}
        />
      )}

      {/* Settings Screen */}
      {currentTab === "settings" && (
        <SettingsView
          workspaceName={workspaceName}
          onSaveWorkspace={async (name) => setWorkspaceName(name)}
        />
      )}

      {/* Command Palette (⌘K) */}
      <CommandPalette
        isOpen={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        actions={paletteActions}
      />

      {/* Slide-over Evidence Drawer ("Why?") */}
      <EvidenceDrawer
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={drawerData.title}
        contextType={drawerData.contextType}
        status={drawerData.status}
        evidenceItems={drawerData.evidenceItems}
        relatedChangeRef={drawerData.relatedChangeRef}
      />
    </Shell>
  );
}
