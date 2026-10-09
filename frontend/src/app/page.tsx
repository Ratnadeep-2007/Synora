"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import { Shell, NavTab, NotificationItem } from "@/components/layout/Shell";
import { ProjectPulseView } from "@/components/views/ProjectPulseView";
import { ProjectStateView } from "@/components/views/ProjectStateView";
import { MeetingsView } from "@/components/views/MeetingsView";
import { MeetingDetailView } from "@/components/views/MeetingDetailView";
import { SourcesView } from "@/components/views/SourcesView";
import { SettingsView } from "@/components/views/SettingsView";
import { WorkspaceAtlasView } from "@/components/views/WorkspaceAtlasView";
import { EvidenceDrawer } from "@/components/common/EvidenceDrawer";
import { CommandPalette } from "@/components/common/CommandPalette";
import { AgentIntelligenceSheet } from "@/components/common/AgentIntelligenceSheet";
import { PipelineStorytellingModal } from "@/components/common/PipelineStorytellingModal";
import { api, getFrontendUserId, getBackendBaseUrl, getFrontendBaseUrl } from "@/lib/api";
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
  ProjectState,
  ProjectStateVersion,
  SourceConnection,
  WorkspaceAtlasData,
} from "@/lib/types";

export default function Home() {
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaceName, setWorkspaceName] = useState<string>("Workspace");
  const [currentTab, setCurrentTab] = useState<NavTab>("overview");
  const [selectedMeetingId, setSelectedMeetingId] = useState<string | null>(null);

  // Surface and Modal States
  const [isAgentSheetOpen, setIsAgentSheetOpen] = useState(false);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const [isStoryModalOpen, setIsStoryModalOpen] = useState(false);

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
  const [meetingCanvas, setMeetingCanvas] = useState<any>(null);
  const [excalArtifact, setExcalArtifact] = useState<ExcalidrawArtifact | null>(null);
  const [excalProposals, setExcalProposals] = useState<ExcalidrawProposal[]>([]);
  const [atlasData, setAtlasData] = useState<WorkspaceAtlasData | null>(null);

  // Event-driven pipeline state
  const [meetSubscriptions, setMeetSubscriptions] = useState<any[]>([]);
  const [meetEvents, setMeetEvents] = useState<any[]>([]);
  const [unknownPendingCount, setUnknownPendingCount] = useState<number>(0);

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
  const refreshAll = useCallback(async (preferredProjectId?: string | null) => {
    try {
      const projListData = await api.getProjects().catch(() => [] as Project[]);
      setProjects((prev) => {
        if (
          prev.length === projListData.length &&
          prev.every(
            (p, idx) =>
              p.id === projListData[idx]?.id &&
              p.updated_at === projListData[idx]?.updated_at &&
              p.name === projListData[idx]?.name
          )
        ) {
          return prev;
        }
        return projListData;
      });

      // The Atlas is the workspace-wide view. Do not refresh unrelated
      // project/meeting/agent endpoints while the user is watching the canvas.
      if (currentTab === "excalidraw") {
        const [atlasResult, unknownResult] = await Promise.allSettled([
          api.getWorkspaceAtlas(),
          api.getUnknownContextSummary().catch(() => ({ pending: 0 })),
        ]);
        if (atlasResult.status === "fulfilled") {
          setAtlasData((prev) => {
            if (!prev) return atlasResult.value;
            if (
              prev.artifact?.version === atlasResult.value?.artifact?.version &&
              prev.artifact?.elements?.length === atlasResult.value?.artifact?.elements?.length &&
              prev.artifact?.updated_at === atlasResult.value?.artifact?.updated_at &&
              prev.unknown_context?.pending === atlasResult.value?.unknown_context?.pending
            ) {
              return prev;
            }
            return atlasResult.value;
          });
        }
        if (unknownResult.status === "fulfilled") {
          setUnknownPendingCount((prev) => {
            const next = unknownResult.value?.pending || 0;
            return prev === next ? prev : next;
          });
        }
        return;
      }

      if (currentTab === "settings") {
        return;
      }

      const activeId =
        preferredProjectId !== undefined
          ? preferredProjectId
          : currentProjectId || projListData[0]?.id || null;
      if (!activeId) {
        setState(null);
        setHistory([]);
        setConflicts([]);
        setCandidates([]);
        setAllEvidence([]);
        setAgents([]);
        setExcalArtifact(null);
        setExcalProposals([]);
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
        subsData,
        eventsData,
        unknownSummaryData,
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
        api.listMeetSubscriptions().catch(() => []),
        api.listMeetEvents(undefined, 20).catch(() => []),
        api.getUnknownContextSummary().catch(() => ({ pending: 0 })),
      ]);

      if (stateData.status === "fulfilled") {
        setState((prev) => (prev?.current_version === stateData.value?.current_version ? prev : stateData.value));
      }
      if (histData.status === "fulfilled") setHistory(histData.value);
      if (confData.status === "fulfilled") setConflicts(confData.value);
      if (meetsData.status === "fulfilled") setMeetings(meetsData.value);
      if (candsData.status === "fulfilled") setCandidates(candsData.value);
      if (evData.status === "fulfilled") setAllEvidence(evData.value);
      if (agData.status === "fulfilled") setAgents(agData.value);
      if (connsData.status === "fulfilled") setConnections(connsData.value);
      if (excalData.status === "fulfilled") {
        setExcalArtifact((prev) => {
          if (!prev) return excalData.value;
          if (
            prev.version === excalData.value?.version &&
            prev.elements?.length === excalData.value?.elements?.length &&
            prev.updated_at === excalData.value?.updated_at
          ) {
            return prev;
          }
          return excalData.value;
        });
      }
      if (propsData.status === "fulfilled") setExcalProposals(propsData.value);
      if (subsData.status === "fulfilled") setMeetSubscriptions(subsData.value);
      if (eventsData.status === "fulfilled") setMeetEvents(eventsData.value);
      if (unknownSummaryData.status === "fulfilled") {
        setUnknownPendingCount((prev) => {
          const next = unknownSummaryData.value?.pending || 0;
          return prev === next ? prev : next;
        });
      }
    } catch (err) {
      console.error("Failed to load project context:", err);
    }
  }, [currentProjectId, currentTab]);

  useEffect(() => {
    refreshAll();
    const interval = setInterval(() => {
      refreshAll();
    }, 5000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  // Load meeting detail when selected
  useEffect(() => {
    if (!selectedMeetingId) {
      setMeetingDetail(null);
      setMeetingCanvas(null);
      return;
    }
    let cancelled = false;
    const loadMeeting = async () => {
      const [detailResult, canvasResult] = await Promise.allSettled([
        api.getMeetingDetail(selectedMeetingId),
        api.getMeetingCanvas(selectedMeetingId),
      ]);
      if (cancelled) return;
      if (detailResult.status === "fulfilled") setMeetingDetail(detailResult.value);
      else console.error("Failed to fetch meeting detail:", detailResult.reason);
      if (canvasResult.status === "fulfilled") setMeetingCanvas(canvasResult.value);
      else console.error("Failed to fetch meeting canvas:", canvasResult.reason);
    };
    loadMeeting();
    const interval = window.setInterval(loadMeeting, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
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

  // Global hotkeys: Cmd+K (Command Palette), Cmd+P (Story Walkthrough), 1-5 (Nav Tabs)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const isInput =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
        return;
      }

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "p") {
        e.preventDefault();
        setIsStoryModalOpen((prev) => !prev);
        return;
      }

      if (!isInput && !e.metaKey && !e.ctrlKey && !e.altKey) {
        if (e.key === "1") {
          setSelectedMeetingId(null);
          setCurrentTab("overview");
        } else if (e.key === "2") {
          setSelectedMeetingId(null);
          setCurrentTab("state");
        } else if (e.key === "3") {
          setSelectedMeetingId(null);
          setCurrentTab("excalidraw");
        } else if (e.key === "4") {
          setSelectedMeetingId(null);
          setCurrentTab("meetings");
        } else if (e.key === "5") {
          setSelectedMeetingId(null);
          setCurrentTab("sources");
        }
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const handleDispatchAgentCapability = async (capabilityId: string, taskDesc?: string) => {
    if (!currentProjectId) throw new Error("No active project");
    const result = await api.dispatchProjectAgentCapability(currentProjectId, capabilityId, taskDesc);
    await refreshAll();
    return result;
  };

  const handleAtlasChanged = useCallback(async () => {
    await api.syncWorkspaceAtlas().catch(() => null);
    await refreshAll();
  }, [refreshAll]);

  const handleCreateProject = async (name: string, description?: string, sources?: string[]) => {
    try {
      const newProj = await api.createProject(name, description, undefined, sources);
      setCurrentProjectId(newProj.id);
      setCurrentTab("excalidraw");
      await api.syncWorkspaceAtlas().catch(() => null);
      await refreshAll(newProj.id);
    } catch (err: any) {
      alert(`Project creation failed: ${err.message}`);
    }
  };

  const handleDeleteProject = async (projectId: string) => {
    try {
      await api.deleteProject(projectId);

      const remaining = projects.filter((p) => p.id !== projectId);
      const nextProjectId = remaining[0]?.id || null;

      setProjects(remaining);
      setCurrentProjectId(nextProjectId);
      setCurrentTab("overview");
      setSelectedMeetingId(null);

      setState(null);
      setHistory([]);
      setConflicts([]);
      setMeetings([]);
      setCandidates([]);
      setAllEvidence([]);
      setAgents([]);
      setExcalArtifact(null);
      setExcalProposals([]);
      setAtlasData(null);
      setMeetSubscriptions([]);
      setMeetEvents([]);
      setUnknownPendingCount(0);
      setAtlasData(null);

      await api.syncWorkspaceAtlas().catch(() => null);
      await refreshAll(nextProjectId);
    } catch (err: any) {
      throw new Error(err.message || "Project deletion failed");
    }
  };

  const requireProject = (): string | null => {
    if (!currentProjectId) {
      alert("Create or select a project first.");
      return null;
    }
    return currentProjectId;
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

  const handleAiGenerateVisuals = async (focusPrompt?: string, directApply: boolean = true) => {
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
          window.location.href = `${getBackendBaseUrl()}/auth/google?user_id=${encodeURIComponent(uid)}&return_to=${encodeURIComponent(getFrontendBaseUrl())}`;
        }
      } else {
        alert(`Google Meet reconciliation: ${msg}`);
      }
    }
  };

  const [vexaCaptureMeetingId, setVexaCaptureMeetingId] = useState<string | null>(null);
  const [vexaCaptureStatus, setVexaCaptureStatus] = useState<any>(null);

  const pollVexaCapture = useCallback(async () => {
    if (!vexaCaptureMeetingId) return;
    try {
      setVexaCaptureStatus(await api.getVexaCaptureStatus(vexaCaptureMeetingId));
    } catch {
      // Non-blocking status polling.
    }
  }, [vexaCaptureMeetingId]);

  useEffect(() => {
    if (!vexaCaptureMeetingId) return;
    pollVexaCapture();
    const id = setInterval(pollVexaCapture, 4000);
    return () => clearInterval(id);
  }, [pollVexaCapture, vexaCaptureMeetingId]);

  const handleStartVexaCapture = async (meetingUrl: string) => {
    const result = await api.startVexaCapture(meetingUrl);
    setVexaCaptureMeetingId(result.meeting_id);
    setVexaCaptureStatus(result);
  };

  const handleStopVexaCapture = async (meetingId?: string) => {
    const target = meetingId || vexaCaptureMeetingId;
    if (!target) return;
    const result = await api.stopVexaCapture(target);
    setVexaCaptureStatus(result);
    await pollVexaCapture();
    await pollActiveCaptures();
  };

  const [activeCaptures, setActiveCaptures] = useState<any[]>([]);

  const pollActiveCaptures = useCallback(async () => {
    try {
      const res = await api.getActiveVexaCaptures();
      setActiveCaptures(res.active || []);
    } catch {
      // Non-blocking; an empty list simply hides the section.
    }
  }, []);

  useEffect(() => {
    pollActiveCaptures();
    const id = setInterval(pollActiveCaptures, 5000);
    return () => clearInterval(id);
  }, [pollActiveCaptures]);

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
    if (!googleConn || googleConn.status !== "active") {
      items.push({
        title: "Google Meet source not connected",
        detail: "Connect Google Meet from Sources to enable transcript sync.",
      });
    }
    return items;
  }, [googleConn]);

  const agentActivity = useMemo(() => {
    const rawEvents: Array<{ timestamp: number; time: string; text: string }> = [];

    // 1. Evidence events (WhatsApp, Google Meet, Uploads)
    allEvidence.slice(0, 6).forEach((ev) => {
      const ts = ev.created_at ? new Date(ev.created_at).getTime() : Date.now();
      const timeStr = ev.created_at
        ? new Date(ev.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "—";
      const sourceLabel =
        ev.source === "whatsapp"
          ? "WhatsApp evidence processed"
          : ev.source === "google_meet"
          ? "Google Meet transcript processed"
          : "Source evidence processed";
      rawEvents.push({
        timestamp: ts,
        time: timeStr,
        text: sourceLabel,
      });
    });

    // 2. Candidate items (Requirements, Decisions)
    candidates.slice(0, 6).forEach((cand) => {
      const ts = cand.created_at ? new Date(cand.created_at).getTime() : Date.now();
      const timeStr = cand.created_at
        ? new Date(cand.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "—";
      const isReq = cand.category?.toLowerCase().includes("req") || cand.classification === "requirement";
      const label = isReq ? "Requirement identified" : "Decision analyzed";
      rawEvents.push({
        timestamp: ts,
        time: timeStr,
        text: cand.title ? `${label}: ${cand.title}` : label,
      });
    });

    // 3. Excalidraw proposals
    excalProposals.slice(0, 4).forEach((prop) => {
      const ts = prop.created_at ? new Date(prop.created_at).getTime() : Date.now();
      const timeStr = prop.created_at
        ? new Date(prop.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "—";
      rawEvents.push({
        timestamp: ts,
        time: timeStr,
        text: `Architecture proposal created (v${prop.derived_from_state_version})`,
      });
    });

    // 4. Project state history
    history.slice(0, 4).forEach((hist) => {
      const ts = hist.created_at ? new Date(hist.created_at).getTime() : Date.now();
      const timeStr = hist.created_at
        ? new Date(hist.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "—";
      rawEvents.push({
        timestamp: ts,
        time: timeStr,
        text: `Project state updated to v${hist.version_number}${hist.reason ? ` — ${hist.reason}` : ""}`,
      });
    });

    // 5. Conflicts
    conflicts.slice(0, 3).forEach((conf) => {
      const ts = conf.created_at ? new Date(conf.created_at).getTime() : Date.now();
      const timeStr = conf.created_at
        ? new Date(conf.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "—";
      rawEvents.push({
        timestamp: ts,
        time: timeStr,
        text: `Conflict detected: ${conf.title}`,
      });
    });

    // Sort descending by timestamp
    rawEvents.sort((a, b) => b.timestamp - a.timestamp);

    // No fallback fabrication: an empty project shows an empty feed, and the
    // UI renders its designed empty state instead of invented activity.
    if (rawEvents.length === 0) {
      return [];
    }

    return rawEvents.slice(0, 8).map((e) => ({ time: e.time, text: e.text }));
  }, [allEvidence, candidates, excalProposals, history, conflicts]);

  const activeProject = projects.find((p) => p.id === currentProjectId) || null;

  const pendingProposalsCount = excalProposals.filter((p) => p.status === "pending").length;
  const excalSyncStatus = pendingProposalsCount > 0 ? "pending" : "synchronized";

  return (
    <Shell
      currentTab={currentTab}
      onTabChange={(tab) => {
        setSelectedMeetingId(null);
        setCurrentTab(tab);
      }}
      projectVersion={state?.current_version || 1}
      openConflictsCount={openConflictsCount}
      unknownContextCount={unknownPendingCount}
      projects={projects}
      currentProjectId={currentProjectId || undefined}
      activeProject={activeProject}
      workspaceName={workspaceName}
      notifications={notifications}
      onSelectProject={(pId) => {
        setSelectedMeetingId(null);
        if (pId === currentProjectId) return;
        setCurrentProjectId(pId);
        // REPLACE (never replicate): clear the old project's canvas state so
        // the newly selected project's Excalidraw file paints fresh.
        setState(null);
        setExcalArtifact(null);
        setExcalProposals([]);
        setCandidates([]);
        setAllEvidence([]);
        setHistory([]);
        refreshAll(pId);
      }}
      onCreateProject={handleCreateProject}
      onDeleteProject={handleDeleteProject}
      onOpenAgentSheet={() => setIsAgentSheetOpen(true)}
      onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
      onOpenStoryModal={() => setIsStoryModalOpen(true)}
    >
      {/* Project Pulse — What is happening right now */}
      {currentTab === "overview" && (
        <ProjectPulseView
          state={state}
          conflicts={conflicts}
          evidence={allEvidence}
          candidates={candidates}
          history={history}
          connections={connections}
          activeProjectName={activeProject?.name || "Synora Core"}
          projectVersion={state?.current_version || 1}
          onNavigateToTab={(tab: NavTab) => {
            setSelectedMeetingId(null);
            setCurrentTab(tab);
          }}
          onOpenEvidence={handleOpenEvidence}
          onReviewConflict={(conf) =>
            handleReviewConflict(conf.id, "mark_unresolved", "Flagged for human review from Project Pulse")
          }
          onOpenAgentSheet={() => setIsAgentSheetOpen(true)}
          onOpenStoryModal={() => setIsStoryModalOpen(true)}
        />
      )}

      {/* Project State Screen — Authoritative brain & Change Replay */}
      {currentTab === "state" && (
        <ProjectStateView
          state={state}
          history={history}
          onRollback={handleRollback}
          onOpenEvidence={handleOpenEvidence}
        />
      )}

      {/* Project Atlas — one infinite, database-backed Excalidraw workspace */}
      {currentTab === "excalidraw" && (
        <WorkspaceAtlasView
          atlas={atlasData}
          projects={projects}
          activeProjectId={currentProjectId}
          onChanged={handleAtlasChanged}
        />
      )}

      {/* Meetings Screen & Detail View */}
      {currentTab === "meetings" &&
        (!selectedMeetingId ? (
          <MeetingsView
            meetings={meetings}
            autoSyncStatus={autoSyncStatus}
            onSelectMeeting={(mId) => setSelectedMeetingId(mId)}
            vexaCaptureStatus={vexaCaptureStatus}
            activeCaptures={activeCaptures}
            onStartVexaCapture={handleStartVexaCapture}
            onStopVexaCapture={handleStopVexaCapture}
          />
        ) : (
          <MeetingDetailView
            meetingId={selectedMeetingId}
            meetingData={meetingDetail}
            meetingCanvas={meetingCanvas}
            candidates={candidates.filter(
              // Strict meeting scoping: only this meeting's own candidates.
              // Legacy rows without a meeting_id previously leaked into every
              // meeting's detail view (e.g. data-pipeline items appearing on
              // a hospital-queue meeting).
              (c) => c.meeting_id && c.meeting_id === selectedMeetingId
            )}
            onBack={() => setSelectedMeetingId(null)}
            onOpenEvidence={handleOpenEvidence}
          />
        ))}

      {/* Sources Screen */}
      {currentTab === "sources" && (
        <SourcesView
          connections={connections}
          subscriptionsActive={activeSubscriptions.length > 0}
          lastMeetEventAt={lastMeetEventAt}
          pendingMeetEvents={pendingMeetEvents.length}
          onConnectGoogle={() => {
            const uid = getFrontendUserId();
            window.location.href = `${getBackendBaseUrl()}/auth/google?user_id=${encodeURIComponent(uid)}&return_to=${encodeURIComponent(getFrontendBaseUrl())}`;
          }}
          onSyncGoogleMeet={handleSyncGoogleMeet}
          onNavigateToArchitecture={() => setCurrentTab("excalidraw")}
        />
      )}

      {/* Settings Screen */}
      {currentTab === "settings" && (
        <SettingsView
          workspaceName={workspaceName}
          onSaveWorkspace={async (name) => setWorkspaceName(name)}
        />
      )}

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

      {/* Global Command Palette (⌘K) */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        onNavigateToTab={(tab) => {
          setSelectedMeetingId(null);
          setCurrentTab(tab);
        }}
        currentTab={currentTab}
        projects={projects}
        currentProjectId={currentProjectId}
        onSelectProject={(pId) => {
          setSelectedMeetingId(null);
          if (pId === currentProjectId) return;
          setCurrentProjectId(pId);
          setState(null);
          setExcalArtifact(null);
          setExcalProposals([]);
          setCandidates([]);
          setAllEvidence([]);
          setHistory([]);
          refreshAll(pId);
        }}
        onOpenAgentSheet={() => setIsAgentSheetOpen(true)}
        onOpenStoryModal={() => setIsStoryModalOpen(true)}
      />

      {/* Persistent Synora Agent Intelligence Surface */}
      <AgentIntelligenceSheet
        isOpen={isAgentSheetOpen}
        onClose={() => setIsAgentSheetOpen(false)}
        projectId={currentProjectId}
        projectVersion={state?.current_version || 1}
        onDispatchCapability={handleDispatchAgentCapability}
      />

      {/* Interactive Intelligence Pipeline Storytelling */}
      <PipelineStorytellingModal
        isOpen={isStoryModalOpen}
        onClose={() => setIsStoryModalOpen(false)}
        onExploreAtlas={() => {
          setIsStoryModalOpen(false);
          setSelectedMeetingId(null);
          setCurrentTab("excalidraw");
        }}
      />
    </Shell>
  );
}
