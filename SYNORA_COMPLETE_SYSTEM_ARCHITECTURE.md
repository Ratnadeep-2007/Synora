# Synora (Synesis) — Comprehensive System Architecture, Ideation & Engineering Guide

> **Document Role:** Canonical System Specification & Master Architecture Guide  
> **Target Audience:** AI Coding Assistants (ChatGPT, Claude, Gemini), Senior Systems Architects, and Enterprise Engineering Teams  
> **Status:** Canonical Production Architecture (Aligned with PRD, Design Specs & Production Codebase)  
> **Maintenance Rule:** Canonical architecture; keep product state version history distinct from document governance.

---

## 1. What is Synora? (The Core Ideation & Problem Statement)

**Synora** (codebase-named *Synesis*) is an **Enterprise Project Intelligence and Living Visual Architecture Platform**.

Its mission is to maintain an authoritative, continuously updated, and evidence-backed representation of what a team is building across distributed, asynchronous, and multi-channel organizations.

### The Problem It Solves: Organizational Context Drift
In modern product and engineering teams, project truth is scattered across:
- **Video Conferences:** Google Meet, Zoom, Microsoft Teams
- **Chat & Messaging:** WhatsApp, Slack
- **Visual Whiteboards:** Excalidraw, Miro, Figma
- **Documents & Repositories:** Google Docs, PRDs, GitHub PRs
- **Human Memory & Ad-hoc Discussions**

Because information is fragmented, team members operate with conflicting mental models:
```text
Person A (attending Product Architecture Meeting):
"We agreed to: BA Agent → Project Planner → Functional → Tech → Frappe"

Person B (chatting in WhatsApp / Slack):
"We agreed to insert an Onboarding Agent: Onboarding → BA → Project → Functional → Tech → Frappe"
```
Both team members act completely rationally based on conversations they were part of. But downstream, this causes:
1. **Knowledge Drift:** Teams build conflicting features without realizing it.
2. **Decision Loss:** Crucial architectural commitments made in meetings disappear in hours of unwatched recordings.
3. **Silent AI Hallucinations:** Downstream AI coding agents hallucinate or overwrite code because they lack an authoritative, verified system of record.
4. **Lack of Provenance:** Nobody can answer: *"Why does the team believe this decision was confirmed?"*

### What Synora Is NOT:
To maintain architectural integrity, Synora is explicitly **NOT**:
- NOT a generic meeting summarizer.
- NOT a toy chatbot or floating conversational widget.
- NOT a meeting bot that joins calls as a participant or records raw audio (No Vexa, no audio scrapers, no headless browser recording bots).
- NOT a generic unstructured RAG application.
- NOT a collection of uncoordinated, autonomous agents hallucinating state changes.

---

## 2. The Three Architectural Pillars

Synora is built upon three uncompromisable architectural pillars:

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             PILLAR 1: TRUST LAYER                                │
│          Immutable Evidence Records with Verbatim Text & Timestamps              │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│                        PILLAR 2: SYSTEM OF RECORD                                │
│       PostgreSQL / SQLite Database with Historically Versioned State             │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│                    PILLAR 3: LIVING VISUAL WORKSPACE                             │
│       Excalidraw Canvas (application/vnd.excalidraw+json) Driven by AI           │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Pillar 1: Evidence as the Trust Layer
- Every claim, decision, requirement, or proposed architectural modification must point to immutable **Evidence** (`Evidence` model).
- Evidence captures:
  - Source channel (`google_meet`, `whatsapp`, `slack`, `excalidraw`)
  - Meeting / Conversation ID
  - Speaker / Participant identity
  - Precise timestamp
  - Verbatim excerpt from the transcript or message
- **Core Question:** When a user or auditor asks, *"Why does Synora believe this?"*, the system provides the exact evidence record and source citation.

### Pillar 2: Database (PostgreSQL / SQLite) as the System of Record
- **Never treat an LLM as the source of truth.**
  - **Wrong:** Meeting transcript $\to$ LLM $\to$ Directly overwrite database.
  - **Correct:** Meeting transcript $\to$ Evidence Log $\to$ Narrow LLM Extraction $\to$ Candidate Knowledge $\to$ Conflict Detection $\to$ State Change Proposal $\to$ Human Approval Gate $\to$ Authoritative Database State.
- Project State is versioned sequentially (`v1 → v2 → v3...`).
- Full immutable snapshots are stored at every version in `project_state_versions`, enabling instant, zero-drift rollback to any prior state.
- Optimistic concurrency control (`current_version` checking) prevents race conditions and overwrites.

### Pillar 3: Excalidraw as the Living Visual Workspace
- Excalidraw is not a static screenshot viewer; it is an interactive, bidirectional canvas:
  - **Role A (Input Ingestion):** Teams can upload or import `.excalidraw` / JSON diagrams. Synora parses them into architectural evidence.
  - **Role B (Output Generation):** The Project Agent and AI Visual Architect translate approved project states, decisions, and components into standard Excalidraw JSON scenes with visual diff previews.
  - **Visual Decision Provenance:** Decisions and requirements appear as living sticky cards directly on the canvas, citing their source Evidence IDs.

---

## 3. The Canonical Organizational Model: "One Project = One Project Agent"

Rather than spawning unpredictable independent agent processes, Synora organizes intelligence into a strict hierarchical topology:

```text
                         WORKSPACE AGENT
                   (Portfolio-Level Oversight)
                                │
        ┌───────────────────────┴───────────────────────┐
        │                                               │
   PROJECT A                                       PROJECT B
(Healthcare Claims Engine)                    (Synora Core Architecture)
        │                                               │
PROJECT AGENT A                                 PROJECT AGENT B
  - Memory Context A                              - Memory Context B
  - State Tree A (v3)                             - State Tree B (v16)
  - Evidence Scope A                              - Evidence Scope B
  - Living Canvas A                               - Living Canvas B
        │                                               │
┌───────┴───────┐                               ┌───────┴───────┐
│ Specialist    │                               │ Specialist    │
│ Capabilities: │                               │ Capabilities: │
│ - BA          │                               │ - BA          │
│ - Tech        │                               │ - Tech        │
│ - Functional  │                               │ - Functional  │
│ - Planner     │                               │ - Planner     │
│ - Frappe      │                               │ - Frappe      │
└───────────────┘                               └───────────────┘
```

### Key Principles of the Project Agent:
1. **Logical Isolation, Shared Model Infrastructure:**
   - A new project does not spin up a heavy container or VM. It creates an isolated logical context boundary inside the database (`ProjectAgent` record).
2. **Context Boundaries:**
   - Cross-project context leakage is prohibited. A WhatsApp message or meeting for *Healthcare Claims* cannot alter the state or canvas of *Core Architecture*.
3. **Unified User Experience:**
   - The user communicates with **ONE Project Agent** per project. The 5 specialist roles (BA, Planner, Functional, Tech, Frappe) are internal execution capabilities coordinated by the Project Agent, not separate top-level chatbots.

---

## 4. Conflict as a First-Class Citizen

In Synora, a contradiction is **not an error or exception** — it is vital project knowledge that must be exposed.

### Example:
- **Approved State (v2):** `BA Agent → Project Planner → Functional Agent → Tech Agent`
- **New Google Meet Candidate:** Alice states: *"We decided to add an Onboarding Agent before BA."*
- **Slack Candidate:** Bob writes: *"Adding an Onboarding Agent creates redundant handoffs; let's keep BA first."*

### Synora's Action:
1. Identifies the semantic contradiction using the **Conflict Detection Engine** ([`ConflictService`](file:///E:/webstack/trikaal/Synora/backend/app/services/conflict_service.py)).
2. Generates a `Conflict` record with:
   - `conflict_type = "architecture_contradiction"`
   - `current_state_ref = "agent_workflow"`
   - `diverging_evidence_ids = ["ev_meet_101", "ev_slack_204"]`
   - `status = "open"`
3. Presents the conflict in the **Conflict Center** UI with side-by-side evidence quotes.
4. **Never silently chooses a winner:** Requires an authorized human reviewer to click **Approve Change**, **Reject**, or **Mark Unresolved**.

---

## 5. Technology Stack & Component Specifications

### 5.1 Backend Infrastructure
- **Runtime:** Python 3.11.15
- **Framework:** FastAPI (ASGI async architecture)
- **Database ORM:** SQLAlchemy 2.0 (`SessionLocal`, SQLite `synesis.db` for local dev, PostgreSQL for production)
- **Data Validation:** Pydantic V2 (`BaseModel`, `Field`, `ConfigDict`)
- **Cryptography:**
  - Token Encryption: Fernet (AES-128-CBC) symmetric encryption for third-party OAuth access/refresh tokens in `source_connections`.
  - CSRF / State Signing: HMAC-SHA256 with 10-minute expiry timestamps.
- **Background Tasks:** Non-blocking async workers and scheduled background execution.

### 5.2 Frontend Application
- **Framework:** Next.js 15+ (App Router architecture)
- **UI Engine:** React 19, TypeScript
- **Styling:** Tailwind CSS, Custom Design System (Editorial Glassmorphism + Precision Neumorphism)
- **Canvas Integration:** `@excalidraw/excalidraw` (dynamically imported with SSR disabled)
- **Icons:** `lucide-react`

### 5.3 Communication & Ingestion Gateways

| Connector | Architecture & Protocols | Key Constraints & Policies |
|---|---|---|
| **Google Meet** | Google Cloud REST API v2 + Google Workspace Events API + Cloud Pub/Sub Webhooks. | Scopes: `meetings.space.readonly`. Obsolete scopes (`meetings.conference.readonly`) and Drive scopes are strictly rejected at startup. Webhook carries notification only; background worker fetches transcript chunks via REST. |
| **WhatsApp** | Node.js Baileys WebSocket daemon connecting to WhatsApp Web Multi-Device protocol. | Ingests incoming group chats/DMs. Natural Language Router identifies whether discussion relates to Core Architecture or specific domain projects. Includes ChatOps simulation endpoint `/connectors/whatsapp/simulate`. |
| **Slack** | Slack Events API + Bot Token. | Webhooks verified via HMAC-SHA256 signature (`X-Slack-Signature`). Parses threaded discussions into evidence. |
| **Excalidraw** | Standard Open Schema (`application/vnd.excalidraw+json`). | Role A (Ingests `.excalidraw` files into architectural evidence) and Role B (Derives diagram modification proposals with visual diff previews). |

---

## 6. Comprehensive Database Schema & Entities

The system defines 24 normalized database entities across domain modules:

```text
                    users
                      │ 1:N
               source_connections (Encrypted OAuth credentials)
                      │
                  workspaces ── 1:1 ── workspace_agents
                      │ 1:N
                   projects ──── 1:1 ── project_agents
                      │ 1:N
        ┌─────────────┼───────────────┬─────────────────┐
        │             │               │                 │
  project_states  meetings      source_events   excalidraw_artifacts
        │             │               │                 │
project_state_  meeting_         evidence       excalidraw_proposals
  versions    transcripts             │                 │
        │             │        candidate_knowledge      │
  state_changes transcript_            │                │
        │         entries          conflicts            │
        └─────────────┴───────────────┴─────────────────┘
                               │
                           agent_runs
                               │
                           audit_logs
```

### Detailed Entity Reference:
1. `User` (`users`): System users (`id`, `email`, `name`, `tenant_id`, `role`, `created_at`).
2. `SourceConnection` (`source_connections`): Connected accounts (`user_id`, `provider`, `status`, `encrypted_credentials`, `scopes`).
3. `Project` (`projects`): Projects (`id`, `workspace_id`, `name`, `description`, `project_agent_id`).
4. `ProjectAgent` (`project_agents`): Logical agent context (`project_id`, `memory_context_json`, `capabilities_json`, `connected_tools_json`).
5. `Workspace` (`workspaces`): Multi-project boundary (`id`, `name`, `description`).
6. `WorkspaceAgent` (`workspace_agents`): Portfolio oversight (`workspace_id`, `portfolio_memory_json`).
7. `SourceEvent` (`source_events`): Ingested raw payloads (`source`, `event_type`, `payload_json`, `status`).
8. `Evidence` (`evidence`): Immutable ground truth (`project_id`, `meeting_id`, `actor_id`, `content`, `source`, `occurred_at`).
9. `Meeting` (`meetings`): Google Meet records (`provider_conference_id`, `title`, `start_time`, `end_time`).
10. `Participant` (`meeting_participants`): Meeting attendees (`provider_participant_id`, `display_name`, `email`).
11. `Transcript` (`meeting_transcripts`): Meeting transcripts (`meeting_id`, `provider_transcript_id`, `state`).
12. `TranscriptEntry` (`transcript_entries`): Timecoded speech (`participant_id`, `text`, `start_time`, `end_time`).
13. `MeetSubscription` (`meet_subscriptions`): Workspace Events subscriptions (`target_resource`, `status`, `expires_at`).
14. `MeetEventRecord` (`meet_event_records`): Pub/Sub push notification deduplication table (`message_id`, `attempts`).
15. `AgentRun` (`agent_runs`): Audit trail of all AI extractions (`model`, `latency_ms`, `input_evidence_ids_json`).
16. `CandidateKnowledge` (`candidate_knowledge`): Extracted items (`category`, `classification`, `title`, `content`, `evidence_ids_json`).
17. `ProjectState` (`project_states`): Authoritative state (`current_version`, `requirements_json`, `decisions_json`, `agent_workflow_json`).
18. `ProjectStateVersion` (`project_state_versions`): Immutable historical state snapshots (`version_number`, `snapshot_json`).
19. `StateChange` (`state_changes`): Proposed state mutations (`approval_status`, `proposed_by`, `evidence_ids_json`).
20. `Conflict` (`conflicts`): Contradiction records (`current_state_ref`, `diverging_evidence_ids_json`, `status`).
21. `AgentExecution` (`agent_executions`): Workforce specialist task execution records (`agent_id`, `output_payload_json`).
22. `ExcalidrawArtifact` (`excalidraw_artifacts`): Authoritative diagram canvas (`elements_json`, `app_state_json`, `extracted_nodes_json`).
23. `ExcalidrawProposal` (`excalidraw_proposals`): Proposed diagram diffs awaiting human review (`proposed_elements_json`, `diff_preview_json`).
24. `AuditLog` (`audit_logs`): Operational audit records for security and compliance.

---

## 7. Dual-Engine LLM Architecture: NVIDIA NIM & DeepSeek

Synora operates a dual-engine architecture to guarantee 100% platform availability:

### 7.1 Primary AI Engine: NVIDIA NIM
- **Base URL:** `https://integrate.api.nvidia.com/v1`
- **Model Selected:** `deepseek-ai/deepseek-v4.1-flash` (with optional switch to `deepseek-ai/deepseek-r1`)
- **Client Class:** [`NvidiaNimLLMClient`](file:///E:/webstack/trikaal/Synora/backend/app/services/llm.py#L196)
- **Role:** High-speed, structured JSON candidate extraction, semantic intent analysis, and architectural component synthesis.
- **Configuration in [`.env`](file:///E:/webstack/trikaal/Synora/.env):**
  ```env
  LLM_PROVIDER="nvidia"
  NVIDIA_API_KEY="nvapi-..."
  NVIDIA_MODEL="deepseek-ai/deepseek-v4.1-flash"
  NVIDIA_BASE_URL="https://integrate.api.nvidia.com/v1"
  ```

### 7.2 Secondary Fallback: Deterministic Rule Engine
- **Client Class:** [`DeterministicRuleLLMClient`](file:///E:/webstack/trikaal/Synora/backend/app/services/llm.py#L48)
- **Behavior:** If `NVIDIA_API_KEY` is empty, expired, or if NVIDIA NIM experience a cold-start timeout (>30s), the client **automatically and gracefully falls back** to the local deterministic rule engine without throwing an unhandled exception or crashing the pipeline.

---

## 8. AI Visual Architecture Engine on Excalidraw

The user requested that **AI design and create the final visual architecture diagrams placed directly onto Excalidraw**.

### 8.1 Architectural Implementation
In [`ExcalidrawService`](file:///E:/webstack/trikaal/Synora/backend/app/services/excalidraw_service.py), the method [`generate_ai_visual_architecture`](file:///E:/webstack/trikaal/Synora/backend/app/services/excalidraw_service.py#L233) synthesizes a complete **57-element visual software architecture diagram** organized into 3 clear operational tiers:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 📐 SYNORA SYSTEM ARCHITECTURE • LIVING EXCALIDRAW BLUEPRINT                            │
│ Orchestrated by Project Agent | Powered by DeepSeek AI Intelligence | PostgreSQL Audit │
└────────────────────────────────────────────────────────────────────────────────────────┘

┌────────────────── TIER 1: PRESENTATION & MULTI-CHANNEL INGESTION ──────────────────────┐
│  🖥️ Next.js 15 Web Client   📹 Google Meet Ingestor   💬 WhatsApp Gateway   ⚡ Slack Bot │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Protocol Arrows (REST / SSE / WebSockets)
┌────────────────── TIER 2: APPLICATION CORE & AUTONOMOUS AI WORKFORCE ──────────────────┐
│  ⚙️ FastAPI Core Engine    🧠 Project Agent (Memory)  🤖 DeepSeek AI NIM   👥 Specialists│
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ ACID Commits & Context Lineage
┌────────────────── TIER 3: PERSISTENCE, EVIDENCE PROVENANCE & AUDIT TRAIL ───────────────┐
│  🗄️ PostgreSQL System of Record  📜 Immutable Evidence Store  🎨 Living Excalidraw Store│
└────────────────────────────────────────────────────────────────────────────────────────┘

┌────────────────── KEY ARCHITECTURAL DECISIONS & EVIDENCE CITATIONS ───────────────────┐
│  [DECISION: DeepSeek on NIM]     [DECISION: 1 Project = 1 Agent]    [DECISION: Wa Bot]  │
│  Evidence: EV-DEC-001            Evidence: EV-DEC-002               Evidence: EV-DEC-003│
└────────────────────────────────────────────────────────────────────────────────────────┘

┌────────────────── ACTIVE REQUIREMENTS & SCOPE BOUNDARIES ──────────────────────────────┐
│  [REQUIREMENT: Zero Hallucination]   [REQUIREMENT: Human Review Gate]  [REQUIREMENT: ..]│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Element Design Standards
- **Container Tiers:** Dashed border boxes with soft semantic background fills (`#f5f3ff` for Ingress, `#ecfdf5` for Core, `#fffbeb` for Storage).
- **Component Cards:** Rounded rectangles (`roundness: {"type": 3}`) with crisp contrast text and technology subtitle tags.
- **Directional Connectors:** Dynamic Excalidraw arrows (`points: [[0, 0], [dx, dy]]`, `endArrowhead: "arrow"`).
- **Living Decision Cards:** Emerald green cards (`#dcfce7`) with bold decision titles and verbatim Evidence citations (`EV-...`).
- **Standard Normalization:** Every element is validated by `_normalize_element` ensuring valid seeds, versions, bounding coordinates, and full compliance with Excalidraw v2 specs.

### 8.3 Dedicated API & Frontend Triggers
- **API Endpoint:** `POST /projects/{project_id}/excalidraw/ai-generate`
  - Accepts `{ "focus_prompt": "Optional focus area", "direct_apply": true }`
  - Returns the generated `ExcalidrawProposal` and updated `ExcalidrawArtifact`.
- **Frontend Action Button:** Added an **"AI Visual Architect"** button with a sparkling gradient in [`ArchitectureView.tsx`](file:///E:/webstack/trikaal/Synora/frontend/src/components/views/ArchitectureView.tsx#L202). Clicking it immediately instructs the AI to compose and render the visual diagram directly onto the canvas.

---

## 9. Output Safety & Human-in-the-Loop Governance

Synora enforces strict **Risk Impact Categorization** before modifying production state:

```text
Impact Level   Examples                                  Governance Policy
──────────────────────────────────────────────────────────────────────────────────
Low            Spelling, formatting, tags                Automated with logging
Medium         Requirement metadata, entity mapping      Automated with audit trail
High           Architecture changes, agent workflow      STRICT HUMAN APPROVAL REQUIRED
               modifications, confirmed decisions        (Remains in Proposed/Pending)
```

No AI model can bypass this rule. Consequential changes create a reviewable proposal. Humans retain final operational authority.

---

## 10. Verification, Test Results & Operational State

### 10.1 Automated Pytest Suite
- **Location:** [`backend/tests/`](file:///E:/webstack/trikaal/Synora/backend/tests/)
- **Total Test Cases:** **176 tests**
- **Test Status:** **176 Passed (100% pass rate in 35.91 seconds)**
- **Coverage Areas Verified:**
  - `test_google_oauth_service.py` & `test_google_meet_service.py`: Token refresh, space-readonly scope enforcement, error resilience.
  - `test_meet_event_pipeline.py` & `test_meet_event_worker.py`: Pub/Sub webhook ingestion, deduplication, transcript entry pagination.
  - `test_whatsapp_baileys.py`: Baileys socket integration, project identification, ChatOps simulation, and Excalidraw node synchronization.
  - `test_project_agent.py`: Isolated memory boundary, specialist capability dispatch, living Excalidraw sync.
  - `test_conflicts.py`: Contradiction detection, diverging evidence tracking, review actions.
  - `test_project_state.py`: Semantic version snapshots, zero-drift rollback, optimistic concurrency control.
  - `test_golden_scenario.py`: End-to-end golden path (Meet transcript $\to$ Evidence $\to$ Intelligence $\to$ Conflict $\to$ Excalidraw Proposal $\to$ Human Approval).

### 10.2 Server Health
- **Backend API:** `http://localhost:8000/health` $\to$ **HTTP 200 OK**
- **Frontend Application:** `http://localhost:3000` $\to$ **HTTP 200 OK**

---

## 11. Quick-Start Guide for Engineers / LLMs

### Start Backend:
```bash
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Start Frontend:
```bash
cd frontend
npm run dev
```

### Run Entire Regression Test Suite:
```bash
pytest backend/tests -q
```
