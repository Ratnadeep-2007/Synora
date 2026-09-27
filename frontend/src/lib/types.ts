export interface ProjectState {
  project_id: string;
  current_version: number;
  title: string;
  vision: string;
  requirements: Array<{ id: string; title: string; content: string; evidence_ids?: string[] }>;
  architecture: Array<{ component: string; role: string; details: string }>;
  agent_workflow: string[];
  decisions: Array<{ id: string; text: string; date: string; evidence_ids?: string[]; approved_by?: string; detail?: string }>;
  constraints: string[];
  assumptions: string[];
  open_questions: string[];
  updated_at: string | null;
}

export interface ProjectStateVersion {
  id: string;
  project_id: string;
  version_number: number;
  snapshot: Record<string, any>;
  reason: string;
  change_summary: Record<string, any>;
  actor_id: string;
  created_at: string;
}

export interface StateChangeProposal {
  id: string;
  project_id: string;
  candidate_id?: string;
  state_version_before: number;
  state_version_after?: number;
  operation: string;
  target_section: string;
  value: any;
  reason: string;
  actor_id: string;
  evidence_ids: string[];
  approval_status: "candidate" | "proposed" | "approved" | "rejected" | "superseded";
  created_at: string;
  resolved_at?: string;
}

export interface Conflict {
  id: string;
  tenant_id: string;
  project_id: string;
  state_change_id?: string;
  candidate_id?: string;
  type: "architecture" | "requirement" | "scope" | "decision" | "workflow" | "dependency";
  severity: "low" | "medium" | "high";
  title: string;
  description?: string;
  current_state_reference: string;
  proposed_change_reference: string;
  evidence_ids: string[];
  status: "open" | "under_review" | "approved" | "rejected" | "unresolved" | "superseded";
  impact?: string;
  risk_level: string;
  source: string;
  created_at: string;
  resolved_at?: string;
  resolved_by?: string;
}

export interface EvidenceItem {
  id: string;
  project_id: string;
  source: string;
  source_event_id: string;
  meeting_id?: string;
  transcript_id?: string;
  transcript_entry_id?: string;
  actor_id?: string;
  occurred_at?: string;
  content: string;
  created_at: string;
}

export interface CandidateKnowledgeItem {
  id: string;
  project_id: string;
  meeting_id?: string;
  category: string;
  classification: string;
  title: string;
  content: string;
  confidence: number;
  evidence_ids: string[];
  status: string;
  agent_run_id?: string;
  created_at: string;
}

export interface MeetingItem {
  id: string;
  title: string;
  start_time: string;
  end_time: string;
  provider: string;
  provider_conference_id: string;
  status: string;
  participants?: Array<{ id: string; display_name: string; email?: string }>;
  transcripts?: Array<{ id: string; provider_transcript_id: string; state: string }>;
}

export interface AgentDefinition {
  agent_id: string;
  name: string;
  role: string;
  description: string;
  capabilities: string[];
  permissions_read: string[];
  permissions_write: string[];
  permissions_prohibited: string[];
  input_types: string[];
  output_types: string[];
  status: string;
  current_task?: string;
  last_run_at?: string;
  current_project_state_version?: number;
}

export interface AgentExecutionRecord {
  id: string;
  agent_id: string;
  project_id: string;
  project_state_version: number;
  input_references: string[];
  output_references: string[];
  model: string;
  prompt_version: string;
  status: string;
  output_type: string;
  output_payload: Record<string, any>;
  duration_ms: number;
  error?: string;
  created_at: string;
}

export interface SourceConnection {
  id: string;
  provider: string;
  status: string;
  account_email?: string;
  account_name?: string;
  scopes: string[];
  last_synced_at?: string;
  created_at: string;
}

export interface ExcalidrawDiffPreview {
  nodes_before: string[];
  nodes_after: string[];
  nodes_added: string[];
  nodes_removed: string[];
  connections_before: string[];
  connections_after: string[];
}

export interface ExcalidrawArtifact {
  id: string;
  project_id: string;
  tenant_id: string;
  name: string;
  version: number;
  elements: any[];
  app_state: Record<string, any>;
  extracted_nodes: string[];
  created_at: string;
  updated_at: string;
}

export interface ExcalidrawProposal {
  id: string;
  artifact_id: string;
  project_id: string;
  tenant_id: string;
  derived_from_state_version: number;
  status: "pending" | "approved" | "rejected";
  reason: string;
  diff_preview: ExcalidrawDiffPreview;
  proposed_elements: any[];
  evidence_ids: string[];
  created_at: string;
  approved_at?: string;
  approved_by?: string;
}

// Deprecated: the legacy per-project coordinator briefing shape. Synora has one
// shared agent, so capabilities are surfaced through AgentDefinition/CapabilityCard.
export interface LegacyCoordinatorBriefing {
  coordinator: string;
  project_id: string;
  project_title: string;
  current_state_version: number;
  agent_workflow: string[];
  capabilities: Record<
    string,
    {
      name: string;
      role: string;
      status: string;
      last_run_at: string | null;
      consumed_state_version: number | null;
    }
  >;
  health_score: number;
  status: string;
  generated_at: string;
}

export interface PossibleProjectMatch {
  id: string;
  unknown_item_id: string;
  candidate_project_id: string;
  candidate_project_name?: string | null;
  similarity_reason: string[];
  supporting_evidence_ids: string[];
  supporting_state_sections: string[];
  conflicts: string[];
  recommendation: string;
  created_at?: string | null;
}

export interface UnknownContextItem {
  id: string;
  project_id: string;
  tenant_id: string;
  source: string;
  source_event_id?: string | null;
  evidence_id?: string | null;
  meeting_id?: string | null;
  actor_id?: string | null;
  occurred_at?: string | null;
  content: string;
  payload: Record<string, any>;
  status: "pending" | "assigned" | "kept" | "dismissed";
  assigned_project_id?: string | null;
  assigned_by?: string | null;
  assigned_at?: string | null;
  created_at?: string | null;
  matches: PossibleProjectMatch[];
}

export interface SpecialistCapability {
  capability_id: string;
  name: string;
  role: string;
  description: string;
  status: string;
  last_dispatched_at?: string | null;
  consumed_state_version?: number | null;
}

export interface ProjectAgent {
  id: string;
  project_id: string;
  tenant_id: string;
  name: string;
  role: string;
  description: string;
  status: string;
  living_workspace_artifact_id?: string | null;
  workspace_sync_status: string;
  last_workspace_sync_at?: string | null;
  current_project_state_version: number;
  last_active_at?: string | null;
  memory_context: Record<string, any>;
  capabilities: Record<string, SpecialistCapability>;
  permissions: {
    read?: string[];
    dispatch?: string[];
    prohibited?: string[];
  };
  connected_tools: string[];
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  tenant_id: string;
  workspace_id: string;
  name: string;
  description?: string | null;
  status: string;
  project_agent_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Workspace {
  id: string;
  tenant_id: string;
  name: string;
  description?: string | null;
  created_at: string;
}

export interface WorkspaceAgent {
  id: string;
  workspace_id: string;
  name: string;
  status: string;
  role: string;
  identity: Record<string, any>;
  memory_context: Record<string, any>;
  capabilities: Array<{
    id: string;
    name: string;
    role: string;
    description: string;
    capabilities: string[];
    status: string;
    last_run_at?: string | null;
    current_task?: string | null;
  }>;
  connected_tools: string[];
  projects_count: number;
  managed_projects: Array<{
    id: string;
    name: string;
    current_state_version: number;
    description?: string;
  }>;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppStatus {
  provider: string;
  status: string;
  latency_ms: number | null;
  details: {
    client?: string;
    protocol?: string;
    session_id?: string;
    active_groups_count?: number | null;
    session_status: string;
    connected_at?: string | null;
    last_seen?: string | null;
  };
}

export interface WhatsAppSimulateResult {
  ok: boolean;
  processed: boolean;
  status?: string;
  reason?: string;
  message_id?: string;
  matched_project?: {
    id: string;
    name: string;
  } | null;
  confidence?: number;
  reasoning?: string;
  evidence_id?: string | null;
  candidate_id?: string | null;
  extracted_category?: string;
  extracted_title?: string;
  excalidraw_updated: boolean;
  artifact_version?: number | null;
  nodes_added?: string[];
  proposal_id?: string;
  message: string;
}

export interface WhatsAppMessageItem {
  id: string;
  project_id: string;
  content: string;
  created_at?: string | null;
  group_name?: string;
  sender_jid?: string;
  confidence?: number;
  reasoning?: string;
}

