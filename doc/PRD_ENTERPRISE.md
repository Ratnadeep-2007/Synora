# Synesis — Project Intelligence & AI Workforce Platform

**Working product name:** Synesis  
**Document:** Product Requirements Document (PRD)  
**Status:** Enterprise Master Specification  
**Document role:** Product requirements, architecture, enterprise operating model, and capability roadmap  
**Maintenance rule:** This document is canonical; do not label it with product-version numbers.

---

## 1. Executive Summary

Synesis is an enterprise project intelligence platform that continuously converts authorized project activity into evidence-backed project knowledge, governed project actions, and a living visual project workspace.

The central product model is:

```text
                         SYNESIS AGENT
                              |
              +---------------+---------------+
              |               |               |
           Project A       Project B       Project C
              |               |               |
          Context A       Context B       Context C
          State A         State B         State C
          Evidence A      Evidence B      Evidence C
          Tools A         Tools B         Tools C
          Excalidraw A    Excalidraw B    Excalidraw C
```

There is ONE shared Synesis Agent runtime/orchestrator. A new project does not create another permanently running AI process. Instead, the platform establishes a project context boundary inside the shared agent system.

Each project context contains:

- project identity
- Project State and historical state
- project knowledge
- evidence and provenance scope
- memory/context
- authorized source connections
- tool permissions
- agent execution history
- Excalidraw workspace association
- audit lineage

The runtime can be shared; project context and authorization cannot be shared implicitly.

### Specialist capabilities

The existing BA, Planning, Functional, Tech, and Frappe implementations remain useful, but they are specialist execution capabilities coordinated by the single Synesis Agent rather than five top-level project identities.

```text
                    SYNESIS AGENT
                          |
        +-----------------+-----------------+
        |                 |                 |
       BA            Planning          Functional
        |                 |                 |
       Tech            Frappe        Other capabilities
```

### Excalidraw

Excalidraw is both a supported input source and the primary human-facing living visual workspace for each project. The Synesis Agent can read visual project information and, through governed structured operations, maintain the project's visual representation.

### PostgreSQL

PostgreSQL is the primary transactional system of record. It stores structured project data, identity, authorization, provenance, Project State, execution records, synchronization metadata, and audit information.

### Core principle

> **Evidence is the trust layer. PostgreSQL is the system of record. The Synesis Agent is the shared intelligence/orchestration layer. Excalidraw is the living visual project workspace. Humans govern consequential changes.**

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
               +-------------+-------------+
               |             |             |
           Google Meet     Slack       Excalidraw
               |             |          (input)
               +-------------+-------------+
                             |
                             v
                    CONNECTOR / INGESTION
                             |
                             v
                    NORMALIZED SOURCE EVENTS
                             |
                             v
                          EVIDENCE
                             |
                             v
                    INTELLIGENCE PIPELINE
                             |
                             v
                       SYNESIS AGENT
                    shared runtime/orchestrator
                             |
                 +-----------+-----------+
                 |                       |
                 v                       v
         PROJECT KNOWLEDGE        PROJECT STATE
                 |                 PostgreSQL
                 +-----------+-----------+
                             |
                             v
                    GOVERNED ACTION / PROPOSAL
                             |
                +------------+------------+
                |                         |
                v                         v
        Specialist capability      Human approval
                |                         |
                +------------+------------+
                             |
                             v
                  EXCALIDRAW WORKSPACE
                         OUTPUT
```

### Architectural boundaries

**Shared runtime:** one Synesis Agent runtime may serve all projects.

**Project context boundary:** every operation is scoped by workspace and project and receives only authorized context.

**System of record:** PostgreSQL owns identity, permissions, structured knowledge, Project State, execution history, and synchronization metadata.

**Visual workspace:** Excalidraw represents project information in a human-facing visual form and may also supply project evidence.

**Provider isolation:** provider-specific connector logic does not leak into the intelligence domain model.

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

# 20. Shared Synesis Agent Context

The Synesis Agent is a shared runtime that serves many projects. The project is the security and context boundary, not the process.

For every agent operation, the system must establish:

```text
workspace_id
project_id
actor / execution identity
current Project State context
authorized tools
relevant evidence
relevant knowledge
```

Context should be composed from:

```text
Current Project State
+
Relevant Requirements
+
Relevant Decisions
+
Relevant Evidence
+
Relevant Constraints
+
Recent Approved Changes
+
Task-specific Context
```

The agent must not receive every project's information. Retrieval must first enforce authorization and project boundaries, then apply structured filters, then semantic retrieval where useful.

### Specialist execution

The shared agent may dispatch:

- Business Analysis capability
- Project Planning capability
- Functional Design capability
- Technical Design capability
- Frappe Engineering capability

The user experiences one Synesis Agent.

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

# 29. Enterprise Capability Roadmap

The roadmap is capability-driven rather than document-version-driven.

## Foundation and Trust

Deliver and verify:

- multi-tenant isolation
- enterprise identity and SSO readiness
- centralized RBAC and policy
- secure secrets and credential lifecycle
- audit logging
- reliable ingestion
- retries and idempotency
- observability
- backup and restore
- staging and production deployment discipline
- real integration verification

## Living Project Agent

Evolve the platform so that one shared Synesis Agent continuously operates across many projects with isolated contexts.

Capabilities:

- automatic project initialization
- project-scoped context
- project-scoped tools
- continuous source processing
- structured agent actions
- specialist capability dispatch
- execution lineage

## Living Excalidraw Workspace

Make Excalidraw a first-class project workspace.

Capabilities:

- project workspace association
- visual project overview
- decisions and requirements as visual objects
- architecture and workflow maps
- evidence references
- images and diagrams
- structured visual patches
- synchronization status
- approval-aware visual changes

## Cross-Source Intelligence

Unify information across authorized sources.

Capabilities:

- entity resolution
- cross-source evidence linking
- contradiction detection
- change timelines
- stale knowledge detection
- impact analysis

## Governed Project Execution

Move from understanding to controlled execution.

Capabilities:

- project analysis
- specifications
- plans
- architecture proposals
- artifact creation
- approved external actions
- task execution with provenance

## Connected Engineering Reality

Expand to engineering and project-management systems when the core operating model is stable.

Potential integrations:

- GitHub
- Jira
- Linear
- documents
- additional meeting systems

The important outcome is traceability between conversation, project state, design, and implementation.

## Continuous Project Intelligence

The agent proactively detects:

- project drift
- unresolved decisions
- stale requirements
- architecture changes
- dependency changes
- implementation gaps
- emerging risks

## Portfolio Intelligence

When explicitly authorized, a workspace-level intelligence layer can reason across projects about:

- shared dependencies
- common systems
- cross-project risks
- repeated requirements
- resource dependencies

Cross-project information must never bypass explicit authorization.

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

> **Synesis connects to authorized work systems, builds evidence-backed project knowledge, maintains a governed Project State, coordinates work through one shared Synesis Agent, and keeps the project's Excalidraw workspace aligned with approved reality.**

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
