import {
  AgentDefinition,
  AgentExecutionRecord,
  CandidateKnowledgeItem,
  Conflict,
  LegacyCoordinatorBriefing,
  EvidenceItem,
  ExcalidrawArtifact,
  ExcalidrawProposal,
  MeetingItem,
  Project,
  ProjectAgent,
  WorkspaceAgent,
  WorkspaceAtlasData,
  ProjectState,
  ProjectStateVersion,
  SourceConnection,
  StateChangeProposal,
  UnknownContextItem,
  WhatsAppStatus,
  WhatsAppSimulateResult,
  WhatsAppMessageItem,
} from "./types";

declare global {
  interface Window {
    __SYNORA_API_URL__?: string;
  }
}

// Resolved per call, not at import time: the backend URL is injected at
// container start via /runtime-config.js (SYNORA_API_URL env), so the same
// image works against localhost, staging, and production without rebuilding.
function apiBaseUrl(): string {
  if (typeof window !== "undefined" && window.__SYNORA_API_URL__) {
    return window.__SYNORA_API_URL__;
  }
  const baked = process.env.NEXT_PUBLIC_API_URL;
  if (baked) return baked;
  return "http://localhost:8000";
}

// Session identity: the backend requires an explicit user ID (no implicit
// demo identity). Persist it per browser so a returning user keeps context.
const USER_ID_KEY = "synesis_user_id";

function getSessionUserId(): string {
  if (typeof window === "undefined") return "";
  let id = window.localStorage.getItem(USER_ID_KEY);
  if (!id) {
    const rand = Math.random().toString(36).slice(2, 10);
    id = `usr_${Date.now().toString(36)}${rand}`;
    window.localStorage.setItem(USER_ID_KEY, id);
  }
  return id;
}

export function getFrontendUserId(): string {
  return getSessionUserId();
}

// Restore an identity from another browser (Settings UI). The meetings,
// projects and memory visible in the app are scoped to this id, so moving
// it is what makes a second browser see the same workspace.
export function setFrontendUserId(id: string): boolean {
  const clean = (id || "").trim();
  if (typeof window === "undefined" || !clean) return false;
  window.localStorage.setItem(USER_ID_KEY, clean);
  return true;
}

// Public base URL of the backend (runtime-injected when deployed).
// Used for full-page navigations such as the OAuth flow, where the api()
// helper's relative-path fetch cannot go.
export function getBackendBaseUrl(): string {
  return apiBaseUrl();
}

export function getFrontendBaseUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "http://localhost:3000";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${apiBaseUrl()}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options?.headers as Record<string, string>) || {}),
  };
  if (!headers["X-User-ID"]) {
    const sessionId = getSessionUserId();
    if (sessionId) headers["X-User-ID"] = sessionId;
  }
  const res = await fetch(url, {
    ...options,
    headers,
  });

  if (!res.ok) {
    let errMsg = `Request failed: ${res.status} ${res.statusText}`;
    try {
      const errJson = await res.json();
      if (errJson) {
        if (typeof errJson.detail === "string") {
          errMsg = errJson.detail;
        } else if (errJson.detail && typeof errJson.detail === "object") {
          errMsg = errJson.detail.message || errJson.detail.hint || errJson.detail.error || JSON.stringify(errJson.detail);
        } else if (typeof errJson.message === "string") {
          errMsg = errJson.message;
        }
      }
    } catch {
      // fallback
    }
    throw new Error(errMsg);
  }

  return res.json();
}

export const api = {
  // 1. Project State
  getProjectState: (projectId: string): Promise<ProjectState> =>
    request<ProjectState>(`/projects/${projectId}/state`),

  getProjectHistory: (projectId: string): Promise<ProjectStateVersion[]> =>
    request<ProjectStateVersion[]>(`/projects/${projectId}/state/history`),

  getProjectStateAtVersion: (projectId: string, version: number): Promise<ProjectStateVersion> =>
    request<ProjectStateVersion>(`/projects/${projectId}/state/${version}`),

  rollbackState: (projectId: string, targetVersion: number, reason: string): Promise<ProjectStateVersion> =>
    request<ProjectStateVersion>(`/projects/${projectId}/state/rollback`, {
      method: "POST",
      body: JSON.stringify({ target_version: targetVersion, reason }),
    }),

  // 2. Proposals
  getStateProposals: (projectId: string, status?: string): Promise<StateChangeProposal[]> =>
    request<StateChangeProposal[]>(`/projects/${projectId}/state/proposals${status ? `?approval_status=${status}` : ""}`),

  approveProposal: (projectId: string, proposalId: string, note?: string): Promise<ProjectStateVersion> =>
    request<ProjectStateVersion>(`/projects/${projectId}/state/proposals/${proposalId}/approve`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),

  rejectProposal: (projectId: string, proposalId: string, reason?: string): Promise<StateChangeProposal> =>
    request<StateChangeProposal>(`/projects/${projectId}/state/proposals/${proposalId}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),

  // 3. Conflict Engine
  getConflicts: (projectId: string, status?: string): Promise<Conflict[]> =>
    request<Conflict[]>(`/projects/${projectId}/conflicts${status ? `?status=${status}` : ""}`),

  getConflictDetail: (projectId: string, conflictId: string): Promise<Conflict> =>
    request<Conflict>(`/projects/${projectId}/conflicts/${conflictId}`),

  reviewConflict: (
    projectId: string,
    conflictId: string,
    action: "approve" | "reject" | "mark_unresolved",
    reason?: string,
    note?: string
  ): Promise<{ conflict: Conflict; message: string; project_state_version?: number }> =>
    request(`/projects/${projectId}/conflicts/${conflictId}/review`, {
      method: "POST",
      body: JSON.stringify({ action, reason, note }),
    }),

  // 4. Evidence & Candidates
  getEvidence: (projectId: string): Promise<EvidenceItem[]> =>
    request<EvidenceItem[]>(`/projects/${projectId}/evidence`),

  getCandidates: (projectId: string): Promise<CandidateKnowledgeItem[]> =>
    request<CandidateKnowledgeItem[]>(`/projects/${projectId}/intelligence/candidates`),

  // 5. Meetings
  getMeetings: (): Promise<MeetingItem[]> =>
    request<MeetingItem[]>("/meetings"),

  deleteMeeting: (meetingId: string): Promise<{ success: boolean; meeting_id: string; message: string }> =>
    request(`/meetings/${meetingId}`, {
      method: "DELETE",
    }),

  // Server-side Google Meet capture via Vexa; Sarvam transcribes after the meeting.
  startVexaCapture: (meeting_url: string): Promise<any> =>
    request<any>("/vexa/meetings/start", {
      method: "POST",
      body: JSON.stringify({ meeting_url }),
    }),

  getVexaCaptureStatus: (meetingId: string): Promise<any> =>
    request<any>(`/vexa/meetings/${meetingId}`),

  stopVexaCapture: (meetingId: string): Promise<any> =>
    request<any>(`/vexa/meetings/${meetingId}/stop`, { method: "POST" }),

  // Captures still running for this user. The Stop buttons are driven by
  // this server state so a page reload can never hide a live bot.
  getActiveVexaCaptures: (): Promise<{ ok: boolean; active: any[] }> =>
    request<{ ok: boolean; active: any[] }>("/vexa/meetings/active"),

  processVexaCapture: (meetingId: string): Promise<any> =>
    request<any>(`/vexa/meetings/${meetingId}/process`, { method: "POST" }),

  routeMeetingEvidence: (
    meetingId: string,
    candidateProjectIds: string[],
    dryRun = false
  ): Promise<any> =>
    request<any>(`/meetings/${meetingId}/route-evidence`, {
      method: "POST",
      body: JSON.stringify({
        candidate_project_ids: candidateProjectIds,
        dry_run: dryRun,
      }),
    }),

  syncGoogleMeetings: (maxConferences?: number): Promise<any> =>
    request<any>(`/meetings/sync${maxConferences ? `?max_conferences=${maxConferences}` : ""}`, {
      method: "POST",
    }),

  getMeetingDetail: (meetingId: string): Promise<any> =>
    request<any>(`/meetings/${meetingId}`),
  getMeetingCanvas: (meetingId: string): Promise<any> =>
    request<any>(`/meetings/${meetingId}/canvas`),

  getMeetingIntelligence: (meetingId: string): Promise<any> =>
    request<any>(`/meetings/${meetingId}/intelligence`),

  processMeetingPipeline: (projectId: string, meetingId: string): Promise<any> =>
    request<any>(`/projects/${projectId}/meetings/${meetingId}/process`, {
      method: "POST",
    }),

  ingestTranscript: (payload: {
    project_id?: string;
    title?: string;
    provider?: string;
    raw_transcript?: string;
    entries?: Array<{ speaker: string; text: string; start_time?: string; end_time?: string }>;
    auto_process?: boolean;
  }): Promise<any> =>
    request<any>("/meetings/ingest-transcript", {
      method: "POST",
      body: JSON.stringify(payload),
    }),


  syncSlackChannel: (channel: string, projectId: string): Promise<any> =>
    request<any>(`/connectors/slack/sync?channel=${encodeURIComponent(channel)}&project_id=${encodeURIComponent(projectId)}`, {
      method: "POST",
    }),

  // Event-driven Meet pipeline: subscriptions, Pub/Sub event records, reconcile
  createMeetSubscription: (payload: {
    target_resource: string;
    target_type?: string;
    project_id?: string;
    workspace_id?: string;
    event_types?: string[];
    pubsub_topic?: string;
  }): Promise<any> =>
    request<any>("/meet/subscriptions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listMeetSubscriptions: (params?: { project_id?: string; status?: string }): Promise<any[]> => {
    const qs = new URLSearchParams();
    if (params?.project_id) qs.append("project_id", params.project_id);
    if (params?.status) qs.append("status", params.status);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<any[]>(`/meet/subscriptions${suffix}`);
  },

  renewMeetSubscription: (subscriptionId: string): Promise<any> =>
    request<any>(`/meet/subscriptions/${subscriptionId}/renew`, { method: "POST" }),

  listMeetEvents: (status?: string, limit: number = 50): Promise<any[]> => {
    const qs = new URLSearchParams();
    if (status) qs.append("status", status);
    qs.append("limit", String(limit));
    return request<any[]>(`/meet/events?${qs.toString()}`);
  },

  processMeetEvent: (eventRecordId: string, opts?: { subscription_id?: string; project_id?: string }): Promise<any> => {
    const qs = new URLSearchParams();
    if (opts?.subscription_id) qs.append("subscription_id", opts.subscription_id);
    if (opts?.project_id) qs.append("project_id", opts.project_id);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<any>(`/meet/events/${eventRecordId}/process${suffix}`, { method: "POST" });
  },

  reconcileMeet: (opts?: { max_conferences?: number; project_id?: string }): Promise<any> => {
    const qs = new URLSearchParams();
    if (opts?.max_conferences) qs.append("max_conferences", String(opts.max_conferences));
    if (opts?.project_id) qs.append("project_id", opts.project_id);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<any>(`/meet/reconcile${suffix}`, { method: "POST" });
  },

  listUnassignedMeetings: (limit: number = 50): Promise<MeetingItem[]> =>
    request<MeetingItem[]>(`/meet/unassigned?limit=${limit}`),

  assignMeetingProject: (meetingId: string, projectId: string): Promise<MeetingItem> =>
    request<MeetingItem>(`/meet/unassigned/${meetingId}/assign?project_id=${encodeURIComponent(projectId)}`, {
      method: "POST",
    }),

  // 5b. Unknown Context triage
  listUnknownContext: (status?: string, limit: number = 100): Promise<UnknownContextItem[]> => {
    const qs = new URLSearchParams();
    if (status) qs.append("status", status);
    qs.append("limit", String(limit));
    return request<UnknownContextItem[]>(`/unknown-context/items?${qs.toString()}`);
  },

  getUnknownBoard: (): Promise<{
    id: string;
    project_id: string;
    name: string;
    version: number;
    elements: any[];
    app_state: any;
    extracted_nodes: string[];
    pending_notes: Array<{
      item_id: string;
      content: string;
      sender: string;
      source: string;
      suggested_project: string;
      reasons: string[];
      created_at: string | null;
    }>;
  }> => request("/unknown-context/board"),

  getUnknownContextSummary: (): Promise<{ pending: number }> =>
    request<{ pending: number }>("/unknown-context/summary"),

  getUnknownSuggestions: (itemId: string): Promise<UnknownContextItem> =>
    request<UnknownContextItem>(`/unknown-context/items/${itemId}/suggestions`),

  assignUnknownItem: (itemId: string, projectId: string, note?: string): Promise<any> =>
    request(`/unknown-context/items/${itemId}/assign`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, note }),
    }),

  keepUnknownItem: (itemId: string): Promise<any> =>
    request(`/unknown-context/items/${itemId}/keep`, { method: "POST" }),

  createProjectFromUnknown: (itemId: string, name: string, description?: string): Promise<any> =>
    request(`/unknown-context/items/${itemId}/create-project`, {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),

  dismissUnknownItem: (itemId: string, reason?: string): Promise<any> =>
    request(`/unknown-context/items/${itemId}/dismiss${reason ? `?reason=${encodeURIComponent(reason)}` : ""}`, {
      method: "POST",
    }),

  // 5c. Visual revision history
  getVisualRevisions: (projectId: string): Promise<any> =>
    request<any>(`/projects/${projectId}/visual/revisions`),

  getCurrentVisualRevision: (projectId: string): Promise<any> =>
    request<any>(`/projects/${projectId}/visual/current`),

  getVisualRevision: (projectId: string, revisionNumber: number): Promise<any> =>
    request<any>(`/projects/${projectId}/visual/revisions/${revisionNumber}`),

  compareVisualRevisions: (projectId: string, fromRevision: number, toRevision: number): Promise<any> =>
    request<any>(
      `/projects/${projectId}/visual/revisions/compare?from_revision=${fromRevision}&to_revision=${toRevision}`
    ),

  restoreVisualRevision: (projectId: string, revisionNumber: number, reason?: string): Promise<any> =>
    request<any>(
      `/projects/${projectId}/visual/revisions/${revisionNumber}/restore${reason ? `?reason=${encodeURIComponent(reason)}` : ""}`,
      { method: "POST" }
    ),

  // 6. Synora Agent capabilities.
  // These endpoints are retained for compatibility with the legacy multi-agent
  // records; the product model is ONE shared Synora Agent plus capabilities.
  getWorkforceAgents: (projectId: string): Promise<AgentDefinition[]> =>
    request<AgentDefinition[]>(`/projects/${projectId}/agents`),

  triggerAgentRun: (
    projectId: string,
    agentId: string,
    taskDescription?: string
  ): Promise<{ execution: AgentExecutionRecord; message: string }> =>
    request(`/projects/${projectId}/agents/${agentId}/run`, {
      method: "POST",
      body: JSON.stringify({ task_description: taskDescription }),
    }),

  getAgentRuns: (projectId: string, agentId: string): Promise<AgentExecutionRecord[]> =>
    request<AgentExecutionRecord[]>(`/projects/${projectId}/agents/${agentId}/runs`),

  // 7. Sources
  getSourceConnections: (): Promise<SourceConnection[]> =>
    request<SourceConnection[]>("/auth/google/connections"),

  // 8. Coordinator Briefing
  // Deprecated legacy coordinator briefing (multi-agent era shape).
  getCoordinatorBriefing: (projectId: string): Promise<LegacyCoordinatorBriefing> =>
    request<LegacyCoordinatorBriefing>(`/projects/${projectId}/agents/coordinator-briefing`),

  // 8c. Shared Project Memory
  getProjectMemory: (projectId: string): Promise<{
    tenant_id: string;
    project_id: string;
    state_version: number;
    project_state: Record<string, any>;
    knowledge: CandidateKnowledgeItem[];
    evidence: EvidenceItem[];
  }> => request(`/projects/${projectId}/memory`),
  // 8b. Single infinite Project Atlas
  getWorkspaceAtlas: (): Promise<WorkspaceAtlasData> =>
    request<WorkspaceAtlasData>("/workspace/atlas"),

  syncWorkspaceAtlas: (): Promise<WorkspaceAtlasData> =>
    request<WorkspaceAtlasData>("/workspace/atlas/sync", { method: "POST" }),

  // 9. Excalidraw Visual Architecture
  getExcalidrawArtifact: (projectId: string): Promise<ExcalidrawArtifact> =>
    request<ExcalidrawArtifact>(`/projects/${projectId}/excalidraw`),

  ingestExcalidrawDiagram: (
    projectId: string,
    payload: { name: string; elements: any[]; app_state?: any }
  ): Promise<ExcalidrawArtifact> =>
    request<ExcalidrawArtifact>(`/projects/${projectId}/excalidraw/ingest`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getExcalidrawProposals: (projectId: string, status?: string): Promise<ExcalidrawProposal[]> =>
    request<ExcalidrawProposal[]>(
      `/projects/${projectId}/excalidraw/proposals${status ? `?status=${status}` : ""}`
    ),

  generateExcalidrawProposal: (
    projectId: string,
    stateVersion?: number,
    reason?: string
  ): Promise<ExcalidrawProposal> => {
    const params = new URLSearchParams();
    if (stateVersion) params.append("state_version", stateVersion.toString());
    if (reason) params.append("reason", reason);
    const qs = params.toString() ? `?${params.toString()}` : "";
    return request<ExcalidrawProposal>(`/projects/${projectId}/excalidraw/proposals/generate${qs}`, {
      method: "POST",
    });
  },

  reviewExcalidrawProposal: (
    projectId: string,
    proposalId: string,
    action: "approve" | "reject",
    reason?: string
  ): Promise<{ proposal: ExcalidrawProposal; artifact?: ExcalidrawArtifact; message: string }> =>
    request(`/projects/${projectId}/excalidraw/proposals/${proposalId}/review`, {
      method: "POST",
      body: JSON.stringify({ action, reason }),
    }),

  generateAiExcalidrawDiagram: (
    projectId: string,
    focusPrompt?: string,
    directApply: boolean = true
  ): Promise<{ proposal: ExcalidrawProposal; artifact?: ExcalidrawArtifact; message: string }> =>
    request(`/projects/${projectId}/excalidraw/ai-generate`, {
      method: "POST",
      body: JSON.stringify({ focus_prompt: focusPrompt, direct_apply: directApply }),
    }),

  generateDiagramFromText: (
    projectId: string,
    text: string,
    autoApply: boolean = true,
    title?: string
  ): Promise<{ success: boolean; artifact_version: number; elements: any[]; plan: any; message: string }> =>
    request(`/projects/${projectId}/excalidraw/text-to-diagram`, {
      method: "POST",
      body: JSON.stringify({ text, auto_apply: autoApply, title }),
    }),


  // 10. One Project = One Logical Project Agent Architecture
  getProjects: (): Promise<Project[]> =>
    request<Project[]>("/projects"),

  createProject: (name: string, description?: string, workspaceId?: string, sources?: string[]): Promise<Project> =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description, ...(workspaceId ? { workspace_id: workspaceId } : {}), ...(sources ? { sources } : {}) }),
    }),

  deleteProject: (projectId: string): Promise<{ success: boolean; project_id: string; project_name: string; message: string }> =>
    request(`/projects/${projectId}`, {
      method: "DELETE",
    }),

  getProjectAgent: (projectId: string): Promise<ProjectAgent> =>
    request<ProjectAgent>(`/projects/${projectId}/agent`),

  dispatchProjectAgentCapability: (
    projectId: string,
    capabilityId: string,
    taskDescription?: string
  ): Promise<{ execution: AgentExecutionRecord; message: string }> =>
    request(`/projects/${projectId}/agent/dispatch`, {
      method: "POST",
      body: JSON.stringify({ capability_id: capabilityId, task_description: taskDescription }),
    }),

  getProjectAgentMemory: (projectId: string): Promise<Record<string, any>> =>
    request<Record<string, any>>(`/projects/${projectId}/agent/memory`),

  updateProjectAgentMemory: (projectId: string, memoryUpdates: Record<string, any>): Promise<Record<string, any>> =>
    request<Record<string, any>>(`/projects/${projectId}/agent/memory`, {
      method: "POST",
      body: JSON.stringify({ memory_updates: memoryUpdates }),
    }),

  syncProjectAgentExcalidraw: (projectId: string): Promise<{ status: string; message: string; artifact_id?: string; elements_count: number }> =>
    request(`/projects/${projectId}/agent/sync-excalidraw`, {
      method: "POST",
    }),

  // 12. Deprecated workspace-agent compatibility endpoints (legacy records only)
  getWorkspaceAgent: (workspaceId?: string): Promise<WorkspaceAgent> =>
    request<WorkspaceAgent>(`/workspace/agent${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`),

  dispatchWorkspaceCapability: (
    capabilityId: string,
    projectId?: string,
    taskDescription?: string,
    workspaceId?: string
  ): Promise<{ execution: AgentExecutionRecord; message: string }> =>
    request(`/workspace/agent/dispatch${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`, {
      method: "POST",
      body: JSON.stringify({
        capability_id: capabilityId,
        project_id: projectId,
        task_description: taskDescription,
      }),
    }),

  updateWorkspaceAgentMemory: (
    memoryUpdates: Record<string, any>,
    workspaceId?: string
  ): Promise<Record<string, any>> =>
    request(`/workspace/agent/memory${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`, {
      method: "POST",
      body: JSON.stringify(memoryUpdates),
    }),

  // 13. WhatsApp Baileys Group Chat Connector
  getWhatsAppStatus: (connectionId?: string): Promise<WhatsAppStatus> =>
    request<WhatsAppStatus>(`/connectors/whatsapp/status${connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : ""}`),

  simulateWhatsAppMessage: (payload: {
    text: string;
    sender_name?: string;
    group_name?: string;
    group_jid?: string;
  }): Promise<WhatsAppSimulateResult> =>
    request<WhatsAppSimulateResult>("/connectors/whatsapp/simulate?immediate=true", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getWhatsAppHistory: (projectId?: string, limit: number = 20): Promise<WhatsAppMessageItem[]> =>
    request<WhatsAppMessageItem[]>(
      `/connectors/whatsapp/history?limit=${limit}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`
    ),

  uploadWhatsAppExport: async (
    file: File,
    targetProjectId?: string,
    limit?: number,
    includeMedia: boolean = true
  ): Promise<{
    ok: boolean;
    filename: string;
    total_in_archive: number;
    processed_count: number;
    matched_count: number;
    unknown_context_count: number;
    visual_proposals_created: number;
    audio_transcriptions: number;
    images_analyzed: number;
    elapsed_seconds: number;
  }> => {
    const formData = new FormData();
    formData.append("file", file);
    const query = new URLSearchParams();
    if (targetProjectId) query.set("target_project", targetProjectId);
    if (limit) query.set("limit", String(limit));
    query.set("include_media", String(includeMedia));

    const url = `${apiBaseUrl()}/connectors/whatsapp/import-export?${query.toString()}`;
    const headers: Record<string, string> = {};
    const sessionId = getSessionUserId();
    if (sessionId) headers["X-User-ID"] = sessionId;

    const res = await fetch(url, {
      method: "POST",
      body: formData,
      headers,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Failed to upload WhatsApp export");
    }
    return res.json();
  },
};
