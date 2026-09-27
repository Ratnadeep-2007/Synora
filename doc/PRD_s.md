# Synesis — Project Intelligence & AI Workforce Platform

**Working product name:** Synesis  
**Document:** Product Requirements Document (PRD)  
**Version:** 0.1  
**Status:** Draft / Technical Validation  
**Date:** 2026-09-23

---

## 1. Executive Summary

Synesis is a project intelligence and AI workforce platform designed to maintain a reliable, continuously updated representation of what a team is building.

Modern project knowledge is fragmented across meetings, chat, whiteboards, documents, repositories, and project-management tools. Different people therefore operate with different assumptions about the same project. This creates knowledge drift, lost decisions, contradictory requirements, and inconsistent AI-agent behavior.

### The Core Architectural Model: One Project = One Logical Project Agent

Synesis organizes intelligence around a strict hierarchy:

```text
Workspace
    │
    ├── Project A ────────► Logical Project Agent A
    ├── Project B ────────► Logical Project Agent B
    └── Project C ────────► Logical Project Agent C
```

When a new project is created, Synesis automatically provisions its dedicated **Project Agent**. Each Project Agent establishes an isolated logical context boundary containing its own:
- `project_id` & Project Agent identity
- Project memory / isolated context
- Versioned Project State & change history
- Evidence scope & source provenance
- Role-based permissions & security boundaries
- Connected tools & source connectors
- Agent execution history & audit lineage
- Excalidraw living visual workspace association

*(Note: This represents **logical isolation** on shared runtime/model infrastructure; it does NOT spawn separate long-running containers per project).*

### Specialist Capabilities under the Project Agent

The Project Agent is the project's primary intelligent entity. Specialist functions are organized as execution modules / capabilities coordinated by the Project Agent:

```text
                PROJECT AGENT
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        BA         Planning     Functional
        │
       Tech
        │
      Frappe
```

The user experiences **ONE Project Agent**, not five disconnected top-level agents.

### Excalidraw: Both Input and Primary Living Visual Workspace

Excalidraw is not merely a diagram viewer; it is the **project's living visual workspace**. The Project Agent consumes evidence from sources, updates PostgreSQL (system of record), and continuously maintains the project's Excalidraw visual canvas (displaying Decisions, Requirements, Architecture, and Evidence links).

### Primary Database: PostgreSQL (System of Record)

PostgreSQL is the authoritative transactional system of record for all structured entities (workspaces, projects, project agents, users, state, versions, evidence, conflicts, and synchronization checkpoints). Excalidraw visual scenes and metadata are linked to PostgreSQL references.

### Core principle

> **AI may propose changes to project knowledge, but important project state must remain evidence-backed, traceable, versioned, and controllable by humans.**

---

# 2. Problem Statement

Project information is distributed across:

- Google Meet / Zoom / Microsoft Teams
- Slack / WhatsApp
- Excalidraw and other design tools
- Documents
- GitHub and source repositories
- Project-management tools
- Human memory

This fragmentation creates several problems:
1. **Context fragmentation**: Relevant information is spread across disjoint systems.
2. **Knowledge drift**: Team members operate from conflicting versions of the project.
3. **Decision loss**: Key commitments made in meetings disappear in raw transcripts.
4. **Contradictions**: New proposals collide with earlier decisions without detection.
5. **AI context fragmentation**: AI agents hallucinate because they lack a single authoritative source of truth.
6. **Lack of provenance**: Inability to answer: *"Why does the system believe this?"*

---

# 3. Product Vision & Core Data Flow

Synesis is the **shared intelligence layer for a project**.

### Conceptual Data Flow

```text
           GOOGLE MEET
                │
             SLACK
                │
           EXCALIDRAW
          (input side)
                │
                ▼
         SOURCE CONNECTORS (Google Meet, Slack, Excalidraw)
                │
                ▼
          NORMALIZED EVENTS (SourceEvents)
                │
                ▼
          PROJECT AGENT (Logical Coordinator)
                │
                ▼
           POSTGRESQL (System of Record)
        ┌───────┴───────┐
        ▼               ▼
  Project State      Evidence /
    Knowledge        Provenance
        │
        ▼
   AGENT REASONING (Specialist Capabilities: BA, Planning, Tech, Functional, Frappe)
        │
        ▼
  Structured action / proposal (Human Review Gate)
        │
        ▼
EXCALIDRAW WORKSPACE OUTPUT (Decisions, Requirements, System Architecture)
```

---

# 4. Product Goals

## 4.1 Primary Goals

### G1 — Create a single project context

Maintain a structured representation of the current project.

### G2 — Capture project knowledge automatically

Ingest information from meetings and connected work tools.

### G3 — Preserve evidence

Every significant extracted fact should be traceable to its source.

### G4 — Detect changes and contradictions

Identify when new information differs from existing Project State.

### G5 — Provide trusted context to AI agents

Agents should consume shared project context instead of independently reconstructing it.

### G6 — Build a reusable connector architecture

Adding new tools should not require redesigning the intelligence layer.

---

# 5. Non-Goals for the MVP

The MVP will not attempt to:

- fully autonomously manage companies or projects
- make irreversible project decisions without human control
- automatically modify architecture or whiteboards without review
- build a foundation model
- support every integration at launch
- process every conversation in real time
- replace project managers or decision makers

The first objective is to prove the core loop:

```text
Source → Evidence → Intelligence → Project State → Conflict/Change → Human Review
```

---

# 6. Target Users

## 6.1 Founder / CEO

Needs to understand:

- What are we actually building?
- What changed?
- Where are major disagreements?
- What decisions are pending?

## 6.2 Product / Project Lead

Needs to understand:

- Current project state
- Requirements
- Decisions
- Open questions
- Impact of new changes

## 6.3 CTO / Engineering Lead

Needs:

- current requirements
- technical decisions
- architecture state
- dependencies
- evidence behind decisions

## 6.4 AI Agent

Needs:

- authoritative project context
- relevant requirements
- relevant decisions
- relevant evidence
- current project-state version

---

# 7. Core Product Concepts

These should become first-class entities in the system.

## Project

Container for all project-related information.

## Source

An external system providing information.

Examples:

- Google Meet
- Slack
- Zoom
- Microsoft Teams
- GitHub
- Excalidraw
- Documents

## Evidence

A source fragment that supports an extracted fact or proposed change.

## Proposal

Something someone suggests.

Example:

> “Maybe we should add an onboarding agent.”

## Decision

A project decision that has been explicitly confirmed.

## Requirement

Something the product or system is expected to satisfy.

## Assumption

Something currently believed but not yet confirmed.

## Conflict

A potential inconsistency between new information and existing project knowledge.

## Project State

The current structured representation of the project.

## Agent

An AI worker that operates using Project State and relevant context.

---

# 8. Product Architecture

At a high level:

```text
                    EXTERNAL SOURCES

      ┌────────────┬────────────┬─────────────┐
      ↓            ↓            ↓             ↓
   Google Meet    Slack        Zoom        GitHub
      │            │            │             │
      └────────────┴────────────┴─────────────┘
                         │
                         ▼
                  CONNECTOR LAYER
                         │
                         ▼
                  INGESTION SERVICE
                         │
                         ▼
                  RAW EVENT STORE
                         │
                         ▼
                INTELLIGENCE ENGINE
             ┌────────────┼────────────┐
             ↓            ↓            ↓
         Extraction    Change       Conflict
                      Detection     Detection
             └────────────┼────────────┘
                          ↓
                     PROJECT STATE
                          │
                 PostgreSQL + pgvector
                          │
               ┌──────────┼──────────┐
               ↓          ↓          ↓
              BA       Project      Tech
             Agent      Agent      Agent
```

---

# 9. MVP User Experience

The initial frontend should be intentionally small.

### Primary navigation

```text
Overview
Project State
Meetings
Decisions
Conflicts
AI Workforce
Sources
Settings
```

---

# 10. Frontend Requirements

## 10.1 Onboarding

The user can create a project and provide:

- project name
- business / product description
- initial project context
- team members
- source connections

Future versions may support conversational onboarding via WhatsApp or Telegram.

### Example

```text
Welcome to Synesis

Project name
[________________]

What are you building?
[________________]

Describe your product
[________________]

Team members
[ Add member ]

Connect your tools
[ Google Meet ]
[ Slack ]
[ Zoom ]

Continue →
```

---

## 10.2 Project Overview

The home screen should expose:

- current project state
- recent changes
- recent decisions
- unresolved conflicts
- open questions
- agent status

Example:

```text
PROJECT: WorkSimplified

3 Decisions today
2 Open conflicts
7 Open questions
14 Active tasks

Current Agent Workflow

BA
↓
Project
↓
Functional
↓
Tech
↓
Frappe

⚠ Attention Required

Onboarding agent proposed before BA.

[ Review ]
```

---

## 10.3 Project State

The user can view:

- Vision
- Requirements
- Architecture
- Agent Workflow
- Constraints
- Assumptions
- Stakeholders

The state must show its version.

Example:

```text
PROJECT STATE v18

Vision
Build an AI Work OS...

Agent Workflow

Onboarding
↓
BA
↓
Project
↓
Functional
↓
Tech
↓
Frappe

Last changed:
23 Sep 2026

Reason:
Product Architecture Meeting #42

Evidence →
```

---

## 10.4 Decisions

Display:

- decision text
- status
- participants
- date
- source
- evidence

Every meaningful decision must expose the evidence behind it.

---

## 10.5 Conflicts

Display:

- existing state
- newly detected proposal/change
- source
- reason for conflict
- evidence
- impact
- resolution controls

Example:

```text
POTENTIAL CONFLICT

Current:
BA → Project → Functional → Tech → Frappe

New proposal:
Onboarding → BA → Project → Functional → Tech → Frappe

Source:
Product Architecture Meeting #42

[ Accept ]
[ Reject ]
[ Discuss ]

Evidence →
```

---

## 10.6 Meetings

Display:

- meetings
- participants
- transcript availability
- extracted decisions
- proposals
- requirements
- action items
- conflicts

A meeting detail screen should support:

```text
[ Transcript ]
[ Decisions ]
[ Requirements ]
[ Conflicts ]
[ Action Items ]
```

---

## 10.7 AI Workforce

Display:

- agent status
- current Project State version
- current inputs
- outputs
- dependencies
- execution history

Initial agents:

- BA Agent
- Project Agent
- Functional Agent
- Tech Agent
- Frappe Agent

---

## 10.8 Sources / Connectors

Display:

- connected tools
- connection status
- account identity
- permissions
- last synchronization
- reconnect / disconnect controls

Example:

```text
Google Meet
Status: Connected

Permissions:
Read meeting information
Read transcripts

Last sync:
2 minutes ago
```

---

# 11. Meeting Intelligence

The initial technical proof-of-concept will start with Google Meet.

### V1 flow

```text
Google Meet
     ↓
Google OAuth
     ↓
Meet API
     ↓
Conference Record
     ↓
Transcript
     ↓
Transcript Entries
     ↓
Meeting Ingestion
     ↓
AI Extraction
     ↓
Project State
```

The first implementation does not require a custom meeting bot.

### Future real-time architecture

For providers where a real-time media/transcript interface is appropriate:

```text
Meeting
  ↓
Real-time stream
  ↓
Meeting Intelligence Service
  ↓
Normalized Events
  ↓
Intelligence Engine
```

---

# 12. Connector Architecture

External tools must be abstracted behind a common connector contract.

Conceptually:

```python
class Connector:
    authenticate()
    health_check()
    fetch_events()
    subscribe()
    normalize()
```

Examples:

```text
GoogleMeetConnector
ZoomConnector
SlackConnector
TeamsConnector
GitHubConnector
ExcalidrawConnector
```

All connectors must produce a normalized internal event.

Example:

```json
{
  "project_id": "p123",
  "source": "google_meet",
  "source_event_id": "xyz",
  "event_type": "transcript",
  "actor": "user_123",
  "timestamp": "...",
  "content": "...",
  "metadata": {}
}
```

The intelligence engine should not depend on provider-specific formats.

---

# 13. Connector Technology Strategy

The team should evaluate reusable open-source infrastructure rather than implement every integration from scratch.

Potential components:

### Nango

Potentially useful for:

- OAuth
- credential lifecycle
- integrations
- webhooks
- connection management

License and commercial-use implications must be reviewed before deep integration.

### Airbyte

Potentially useful for:

- source connectivity
- data synchronization
- large connector ecosystem

It should be treated as an ingestion/integration tool, not as the product intelligence layer.

### Vexa (REJECTED / REMOVED)

**Architecture Decision:** Synesis will **NOT** use Vexa for Google Meet.
Synesis will **NOT** build a custom meeting bot, Chrome extension, or custom audio transcription pipeline.

The Google Meet pipeline is:
```text
Google Meet
    ↓
Google native transcript
    ↓
Google Meet REST API
    ↓
Synesis
    ↓
Evidence
    ↓
Meeting Intelligence
    ↓
Project State
```

### Native APIs

Use directly where they provide better semantics or control.

---

# 14. Intelligence Engine

The Intelligence Engine is a set of capabilities, not one giant prompt.

## 14.1 Extraction

Extract structured project information from source content.

## 14.2 Classification

Classify extracted content as:

- Proposal
- Decision
- Requirement
- Question
- Assumption
- Action Item

## 14.3 Entity Resolution

Understand that different expressions may refer to the same entity.

Example:

```text
BA
Business Analyst
BA Agent
Requirement Agent
```

## 14.4 Change Detection

Determine whether new information changes existing project knowledge.

## 14.5 Conflict Detection

Determine whether new information is inconsistent with Project State.

## 14.6 Impact Analysis

Determine which requirements, components, or agents may be affected.

## 14.7 Context Generation

Create relevant context for downstream AI agents.

---

# 15. Project State Model

The Project State is the central data product.

It may contain:

```text
Vision
Requirements
Architecture
Agent Workflow
Decisions
Constraints
Assumptions
Stakeholders
Open Questions
Tasks
Conflicts
```

The state must be versioned.

Example:

```text
v16
 ↓
v17
 ↓
v18
```

Each significant state change should have:

- previous value
- proposed value
- reason
- actor
- source
- evidence
- timestamp
- approval status

---

# 16. Evidence / Provenance Requirements

Every important extracted item should have provenance.

Example:

```text
Decision DEC-19

Statement:
“Onboarding will happen before BA.”

Source:
Google Meet

Meeting:
Product Architecture #42

Speaker:
CEO

Timestamp:
14:24:12

Evidence:
Transcript Entry #1834

Confirmed by:
CEO + CTO

Status:
Confirmed
```

The UI should allow the user to answer:

> Why does Synesis believe this?

---

# 17. AI Reliability Model

The system must not treat the LLM as the source of truth.

Correct architecture:

```text
Raw Evidence
      ↓
LLM Extraction
      ↓
Candidate Knowledge
      ↓
Validation
      ↓
Project State
```

### Mandatory distinctions

The system must distinguish:

- Idea
- Suggestion
- Proposal
- Assumption
- Decision
- Reversal

Example:

> “Maybe we should use an onboarding agent.”

must not automatically become:

> “Decision: add onboarding agent.”

---

# 18. Human-in-the-Loop

High-impact project changes require human review.

Example:

```text
AI detects change
        ↓
Change proposal
        ↓
Conflict / impact analysis
        ↓
Human review
        ↓
Approve / Reject / Discuss
        ↓
Project State update
```

Human review is specifically intended to reduce the risk of incorrect project-state mutations.

---

# 19. Conflict Detection

The system should support at least:

### Direct contradiction

```text
Existing:
BA is first processing agent.

New:
Onboarding should come before BA.
```

### Requirement conflict

```text
Requirement:
System works offline.

New architecture:
Requires cloud-only service.
```

### Decision reversal

```text
Previous:
Use PostgreSQL.

New:
Replace PostgreSQL with MongoDB.
```

### Scope conflict

```text
Approved scope:
B2B product.

New requirement:
Consumer marketplace.
```

---

# 20. AI Workforce Context

AI agents should not receive the entire database indiscriminately.

Agent context should be assembled from:

```text
Current Project State
+
Relevant Requirements
+
Relevant Decisions
+
Relevant Evidence
+
Relevant Prior Agent Outputs
```

Example:

```text
Tech Agent
   ↓
Current architecture
   +
approved requirements
   +
technical decisions
   +
relevant evidence
```

---

# 21. Recommended Tech Stack

## Frontend

```text
Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
TanStack Query
React Flow
```

## Backend

```text
Python
FastAPI
```

## Database

```text
PostgreSQL
pgvector
```

## Async Processing

```text
Redis
Celery
```

## Object Storage

```text
S3-compatible storage
```

## AI Observability

```text
Langfuse
```

## Deployment

```text
Docker
```

---

# 22. Initial Backend Structure

Use a modular monolith initially.

Suggested modules:

```text
/api
/auth
/connectors
/ingestion
/transcripts
/intelligence
/project_state
/evidence
/conflicts
/agents
/notifications
```

Do not introduce microservices until actual scale or operational requirements justify them.

---

# 23. Security Requirements

Because Synesis processes potentially sensitive organization data:

## Authentication

Use secure OAuth flows for external sources.

## Authorization

Initial roles:

```text
Owner
Admin
Member
Viewer
Agent
```

## Tenant isolation

Organization data must be isolated.

## Credential security

OAuth refresh tokens and client secrets must be stored securely.

Never expose credentials to frontend code.

## Encryption

Use secure transport and appropriate encryption at rest.

## Audit logging

Record:

- source connections
- permission changes
- approvals/rejections
- agent actions
- Project State changes
- relevant administrative events

## Least privilege

Request only permissions required for the integration.

## Data retention

Provide configurable retention policies in later production versions.

---

# 24. Reliability Requirements

External APIs and AI services will fail.

The system must assume:

- API downtime
- rate limits
- duplicate webhook delivery
- delayed transcripts
- LLM timeouts
- worker crashes
- network errors

### Idempotency

Repeated ingestion of the same event must not produce duplicate project knowledge.

### Retries

Retry transient failures automatically.

### Dead-letter handling

Repeatedly failing events should be isolated.

### Checkpointing

Large transcripts should be processed incrementally.

### State versioning

Do not perform destructive updates to core project knowledge.

### Observability

Every AI operation should be traceable.

---

# 25. Performance Targets

These are initial engineering targets rather than production SLAs.

### Connector ingestion

Normal events should reach ingestion within seconds/minutes depending on provider behavior.

### Meeting processing

Meeting processing should be asynchronous and must not block the UI.

### Frontend

Common project-state reads should feel near-instant through caching and optimized queries.

### Availability

Target 99.9% service availability after production stabilization and measurement.

---

# 26. AI Quality Metrics

Track:

### Decision precision

How often extracted decisions are actually confirmed decisions.

### False decision rate

Percentage of proposals/ideas incorrectly classified as decisions.

### Conflict precision

Percentage of detected conflicts that are genuine.

### Conflict recall

Percentage of meaningful conflicts detected.

### Evidence coverage

Percentage of meaningful state changes with traceable evidence.

### Human override rate

How often users reject AI-proposed changes.

### Agent task success

Whether agents operating against shared Project State produce better outcomes.

---

# 27. Product Metrics

Track:

- source connection rate
- time to first useful project insight
- number of validated decisions
- number of validated requirements
- conflict detection and resolution rate
- active AI-agent usage
- project retention
- weekly/monthly active teams

---

# 28. MVP Acceptance Criteria

The MVP is successful when all of the following are demonstrated:

### A

A user can connect a Google account.

### B

The application can identify an eligible Google Meet conference.

### C

The application can retrieve available transcript information.

### D

The transcript can be normalized into the internal event format.

### E

The intelligence layer can extract:

- decisions
- proposals
- requirements
- questions
- action items

### F

Each meaningful extraction includes evidence metadata.

### G

New information can be compared against Project State.

### H

A contradiction generates a conflict instead of silently overwriting state.

### I

A human can approve or reject a proposed change.

### J

An AI agent can consume the resulting Project State.

---

# 29. Development Roadmap

## Phase 0 — Google Meet Technical Spike

```text
Google OAuth
↓
Meet API
↓
Conference record
↓
Transcript retrieval
```

Goal:

> Get one real meeting transcript into the backend.

---

## Phase 1 — Meeting Intelligence

```text
Transcript
↓
Normalization
↓
LLM extraction
↓
Structured knowledge
```

Goal:

> Convert a real meeting into useful structured project information.

---

## Phase 2 — Project State

Add:

- PostgreSQL
- evidence
- decisions
- requirements
- state versioning

Goal:

> Maintain persistent project knowledge.

---

## Phase 3 — Conflict Engine

Add:

- semantic state comparison
- contradiction detection
- change proposals
- human review
- audit trail

Goal:

> Detect and safely manage project drift.

---

## Phase 4 — AI Workforce

Add:

- BA Agent
- Project Agent
- Functional Agent
- Tech Agent
- Frappe Agent

Goal:

> AI agents operate against shared Project State.

---

## Phase 5 — Additional Connectors

Add:

- Slack
- Zoom
- Microsoft Teams
- GitHub

Goal:

> Prove that the architecture is source-independent.

---

## Phase 6 — Work / Design Artifacts

Add:

- Excalidraw
- documents
- Jira / Linear
- other project artifacts

Goal:

> Connect conversations to implementation artifacts.

---

## Phase 7 — Real-Time Intelligence

Evaluate:

- real-time meeting streams
- live extraction
- live conflict suggestions
- near-real-time project-state updates

Goal:

> Move from post-event intelligence toward real-time project intelligence.

---

# 30. Key Risks

## Risk 1 — Incorrect AI interpretation

**Mitigation:** evidence, structured extraction, validation, human approval.

## Risk 2 — Too many false conflicts

**Mitigation:** semantic comparison, thresholds, conflict categories, human review.

## Risk 3 — Connector instability

**Mitigation:** retries, idempotency, normalized connector contract, health checks.

## Risk 4 — Overengineering

**Mitigation:** modular monolith and small MVP scope.

## Risk 5 — Becoming another meeting summarizer

**Mitigation:** optimize the product around Project State and downstream action, not summaries.

## Risk 6 — Users do not trust AI-generated project state

**Mitigation:** provenance, versioning, evidence, audit trail, and “Why?” views.

---

# 31. Core Product Principle

> **The system does not merely remember conversations. It maintains project knowledge derived from conversations and other evidence.**

The project knowledge layer is more important than any individual connector or meeting feature.

---

# 32. MVP in One Sentence

> **Synesis connects to a team's work systems, extracts evidence-backed project knowledge, detects changes and contradictions, maintains a versioned Project State, and provides that context to humans and AI agents.**

---

# 33. First Engineering Milestone

Build only:

```text
Google Meet
    ↓
OAuth
    ↓
Meet API
    ↓
Transcript
    ↓
FastAPI
    ↓
Meeting Intelligence
    ↓
Structured Knowledge
    ↓
PostgreSQL
    ↓
Project State
    ↓
Conflict Detection
```

Do not simultaneously build every connector, all five agents, automatic Excalidraw changes, and real-time meeting capture.

The first proof must be:

> **A real meeting can reliably become structured project knowledge, and that knowledge can update a project state without the AI inventing or silently overwriting truth.**
