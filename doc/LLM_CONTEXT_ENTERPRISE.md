# Synesis — LLM Context & Engineering Guide

**Purpose:** Canonical persistent context for any LLM/AI coding assistant working on Synesis.  
**Status:** Enterprise Master Engineering Context  
**Relationship to other documents:** `PRD.md` defines product requirements and enterprise architecture. `design.md` defines the UI/UX language. This document defines engineering reasoning and implementation rules.
**Maintenance rule:** Do not add document-version numbers; keep product Project State history separate from document governance.

---

# 1. What is Synesis?

Synesis is a **Project Intelligence and AI Workforce platform**.

Its purpose is to create a reliable, evidence-backed representation of a project's current state from fragmented information across meetings, chats, documents, whiteboards, repositories, and other work systems.

The key idea is:

> Synesis does not merely summarize conversations. It maintains project knowledge derived from conversations and other evidence.

The product is designed to solve a real organizational problem:

Different people can work on the same project while holding different assumptions about what is being built.

Example:

```text
Person A believes:

BA → Project → Functional → Tech → Frappe
```

while:

```text
Person B believes:

Onboarding → BA → Project → Functional → Tech → Frappe
```

Both may be acting rationally based on different conversations.

Synesis creates a common, inspectable Project State so that humans and AI agents can operate from the same context.

---

# 2. The Product Is NOT

Do not reduce Synesis to:

- a meeting summarizer
- a chatbot
- a note-taking tool
- a transcription service
- a generic RAG application
- a visual editor
- a collection of independent top-level agents
- an autonomous company manager

The core abstraction is:

```text
External Activity
      ↓
Evidence
      ↓
Project Knowledge
      ↓
Project State
      ↓
ONE SHARED SYNESIS AGENT
      ↓
Governed Project Action
      ↓
EXCALIDRAW LIVING WORKSPACE
```

---

# 3. Canonical Product Model & Architecture

There is one shared Synesis Agent runtime/orchestrator serving many projects.

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

A project is a context/security boundary, not a separate long-running AI process.

Every agent operation must establish:

```text
workspace_id
project_id
execution identity
current state context
authorized tool scope
relevant evidence
```

## Specialist capabilities

BA, Planning, Functional, Tech, and Frappe are specialist execution capabilities underneath the shared Synesis Agent.

```text
                    SYNESIS AGENT
                          |
        +-----------------+-----------------+
        |                 |                 |
       BA            Planning          Functional
        |                 |                 |
       Tech            Frappe        Other capabilities
```

The user experiences ONE Synesis Agent.

## Primary storage

PostgreSQL is the primary system of record for structured project data, identity, permissions, Project State, evidence metadata, execution history, synchronization metadata, and audit records.

pgvector is a retrieval mechanism within PostgreSQL where semantic search is useful.

Object storage is for large files/artifacts.

Redis/worker infrastructure is for asynchronous processing, retries, and durable jobs.

## Excalidraw

Excalidraw is both an input source and the living visual project workspace.

The system of record remains PostgreSQL.

The visual workspace is maintained by the Synesis Agent through validated, project-scoped operations.

# 4. The Most Important Architectural Principle

## Never treat an LLM as the source of truth.

Wrong:

```text
Meeting
 ↓
LLM
 ↓
Overwrite database
```

Correct:

```text
Raw Evidence
 ↓
LLM Extraction
 ↓
Candidate Knowledge
 ↓
Validation / Comparison
 ↓
Change Proposal
 ↓
Human Approval when required
 ↓
Project State
```

The LLM produces interpretations.

The application/database stores authoritative state.

---

# 5. Evidence-First Architecture

Every important claim must have provenance.

A useful internal mental model is:

```text
PROJECT STATE
     ↑
     │
   Change
     ↑
     │
   Evidence
     ↑
     │
 Source Artifact
```

For example:

```text
Decision:
"Onboarding happens before BA"

Source:
Google Meet

Meeting:
Product Architecture #42

Speaker:
CEO

Timestamp:
14:24:12

Transcript entry:
#1834

Status:
Confirmed
```

A user must be able to answer:

> Why does Synesis believe this?

The system must provide the answer.

---

# 6. Proposals Are Not Decisions

This distinction is mandatory.

Consider:

> "Maybe we should add an onboarding agent."

This is a **proposal**.

It must not automatically become:

```text
Decision:
Add onboarding agent.
```

A real decision may look like:

> "Okay, let's include the onboarding agent before BA."

Even then, the system should store the evidence and the participants/context that support the classification.

Recommended states:

```text
Idea
Proposal
Under Discussion
Decision
Rejected
Superseded
Unresolved
```

---

# 7. Project State Is Historically Versioned

Never silently destroy important historical state.

Use versions:

```text
v16
 ↓
v17
 ↓
v18
```

Each state transition should capture:

```text
previous state
proposed new state
reason
source
evidence
actor
timestamp
approval status
```

This creates a project history rather than a mutable black box.

---

# 8. Conflict Is a First-Class Entity

A conflict is not an error condition.

It is a piece of project information requiring attention.

Example:

```text
Current:
BA → Project → Functional → Tech

New:
Onboarding → BA → Project → Functional → Tech
```

Synesis should create:

```text
Conflict #07

Topic:
Agent Pipeline

Type:
Architecture contradiction / proposed change

Current:
BA → Project → Functional → Tech

Proposed:
Onboarding → BA → Project → Functional → Tech

Source:
Google Meet #42

Status:
Needs review
```

The system should not silently choose one.

---

# 9. AI Decision-Making Policy

For every AI-generated change, classify the impact.

## Low-impact

Examples:

- spelling correction
- duplicate detection
- formatting
- low-risk categorization

Can potentially be automated.

## Medium-impact

Examples:

- requirement metadata change
- task categorization
- entity merge

May be automated with audit logging.

## High-impact

Examples:

- architecture changes
- scope changes
- major requirements
- agent workflow changes
- confirmed project decisions

Require explicit human confirmation.

The product should be conservative where mistakes can propagate into downstream agents.

---

# 10. Connector Architecture

All source integrations should feed a common event model.

Each connector should hide provider-specific details.

Conceptual interface:

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

All should produce normalized events.

Example:

```json
{
  "project_id": "p123",
  "source": "google_meet",
  "source_event_id": "xyz",
  "event_type": "transcript",
  "actor": "user_123",
  "timestamp": "2026-09-23T14:24:12+05:30",
  "content": "We should add a general onboarding agent before BA.",
  "metadata": {}
}
```

The intelligence engine should process the normalized format, not provider-specific JSON.

---

# 11. Current Google Meet Scope

The first technical proof-of-concept is Google Meet.

Current target flow:

```text
Google Account
   ↓
OAuth
   ↓
Google Meet API
   ↓
Conference Record
   ↓
Transcript
   ↓
Transcript Entries
   ↓
Ingestion
   ↓
Meeting Intelligence
   ↓
Project State
```

The first version should avoid unnecessary complexity.

Do not start by building a custom browser extension or live meeting bot if post-meeting transcript ingestion is sufficient to validate the product.

Real-time meeting capture is a later capability.

---

# 12. Meeting Intelligence Service

The Meeting Intelligence Service is responsible for turning meeting information into structured project events.

Responsibilities:

```text
1. Receive transcript data
2. Normalize transcript entries
3. Detect speakers / participants where available
4. Segment meaningful discussion
5. Extract project knowledge
6. Preserve evidence references
7. Produce candidate changes
8. Send candidates to validation / conflict detection
```

It should NOT directly own the entire Project State.

---

# 13. Intelligence Pipeline

Recommended pipeline:

```text
Raw Event
   ↓
Preprocessing
   ↓
Chunking / segmentation
   ↓
Extraction
   ↓
Classification
   ↓
Entity Resolution
   ↓
State Comparison
   ↓
Conflict Detection
   ↓
Impact Analysis
   ↓
Change Proposal
   ↓
Approval workflow
   ↓
Project State update
```

Each stage should have a narrow responsibility.

Avoid one giant LLM prompt that performs all steps.

---

# 14. Suggested Extraction Schema

The exact schema may evolve, but LLM outputs should be structured.

Example:

```json
{
  "items": [
    {
      "type": "proposal",
      "topic": "agent_pipeline",
      "content": "Add onboarding agent before BA",
      "speaker_id": "user_123",
      "confidence": 0.91,
      "evidence": {
        "source": "google_meet",
        "meeting_id": "meeting_42",
        "timestamp": "14:24:12",
        "transcript_entry_id": "entry_1834"
      }
    }
  ]
}
```

Important:

- enforce a schema
- validate values
- reject malformed model output
- never assume the model returned correct JSON

---

# 15. LLM Output Rules

All model output entering application logic must be:

1. schema validated
2. sanitized
3. checked for required fields
4. checked for valid enum values
5. associated with evidence
6. logged for observability

Never use free-form model text as a database command.

Bad:

```text
LLM:
"Update architecture to include onboarding."
```

Good:

```json
{
  "operation": "propose_state_change",
  "entity": "agent_workflow",
  "risk_level": "high",
  "evidence_id": "ev_1834"
}
```

---

# 16. Shared Synesis Agent Context

The Synesis Agent is shared across projects. The current project determines the context available to the execution.

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
Task-specific context
```

Do not load the entire organization into the model context.

Do not allow context retrieval to cross project boundaries.

Specialist capabilities receive task-specific context selected by the Synesis Agent.

# 17. Context Retrieval Strategy

Use structured filtering first.

Then semantic retrieval.

Preferred order:

```text
1. Project ID / tenant
2. Entity / feature
3. State version
4. Structured filters
5. Semantic retrieval
6. Ranking
7. Context assembly
```

Do not blindly vector-search the entire database.

Vectors are a retrieval mechanism, not a replacement for structured data.

---

# 18. Recommended Data Storage

Primary:

```text
PostgreSQL
```

Vector retrieval:

```text
pgvector
```

Files / large raw artifacts:

```text
S3-compatible object storage
```

Temporary/cache/queue:

```text
Redis
```

Do not introduce a separate vector database unless scale proves it necessary.

---

# 19. Backend Architecture

Start as a modular monolith.

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

This is preferable to premature microservices.

A module should have a clear responsibility and clean interfaces.

---

# 20. Recommended Backend Stack

```text
Python
FastAPI
PostgreSQL
pgvector
Redis
Celery
S3-compatible object storage
Docker
Langfuse
```

Frontend:

```text
Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
TanStack Query
React Flow
Framer Motion
Lucide
```

Use an LLM-provider abstraction rather than coupling application logic to one provider.

---

# 21. Background Processing

Long-running work must be asynchronous.

Example:

```text
Meeting transcript received
       ↓
Create ingestion event
       ↓
Queue
       ↓
Worker
       ↓
AI processing
       ↓
Validation
       ↓
State proposal
```

Do not perform large transcript analysis inside the HTTP request that the UI waits for.

---

# 22. Reliability Requirements

Assume every external dependency can fail.

Cases:

```text
API unavailable
Rate limited
Webhook duplicated
Transcript delayed
LLM timeout
Worker crash
Network interruption
Malformed response
```

System requirements:

### Idempotency

The same source event processed twice must not create duplicate knowledge.

### Retries

Retry transient failures with bounded backoff.

### Dead-letter handling

Repeatedly failing events need an explicit failure state.

### Checkpointing

Large jobs should be restartable.

### State versioning

Never silently overwrite high-value state.

### Observability

Trace major processing steps.

---

# 23. Security Model

Synesis will process sensitive organizational information.

## Authentication

Use OAuth for external systems.

## Authorization

At minimum:

```text
Owner
Admin
Member
Viewer
Agent
```

## Tenant isolation

Every project and project-related record must belong to a tenant/workspace boundary.

## Secrets

Never expose:

- client secrets
- refresh tokens
- API keys

to the browser.

Never commit them to Git.

## Least privilege

Request only required OAuth scopes.

## Auditability

Record security-sensitive and state-changing actions.

---

# 24. Important Security Rule for AI Agents

An AI agent must not be granted unrestricted authority simply because it is an internal service.

Agent actions should have explicit permissions.

Example:

```text
BA Agent
  Can read:
    requirements
    decisions
    evidence

  Can write:
    proposed requirements
    analysis

  Cannot:
    approve architecture change
    delete decisions
```

Agent permissions should be explicit in the authorization model.

---

# 25. Frontend Design Context

The UI is:

**Light theme + restrained Editorial Glassmorphism + Precision Neumorphism.**

The interface should feel:

```text
Professional
Calm
Precise
Trustworthy
Operational
```

Avoid:

```text
Neon
Cyberpunk
Excessive gradients
Purple AI aesthetics
AI robots
Glowing brains
Overly rounded cards
Generic chatbot dashboards
```

Primary color family:

```text
Warm neutral canvas
Deep green primary
White surfaces
Muted gray/green text
Reserved status colors
```

---

# 26. UX North Star

Every important screen should help the user answer:

```text
What is true?
What changed?
Why?
What needs attention?
What can I do?
```

The UI is not primarily a place to chat with AI.

It is a place to understand and control project knowledge.

---

# 27. Signature UI Component: Evidence Drawer

This is a key Synesis interaction.

Any important decision, requirement, or state change should have a “Why?” or “Evidence” action.

Example:

```text
Decision DEC-019

Onboarding happens before BA.

[ Why? ]
```

Clicking opens:

```text
WHY THIS EXISTS

Source:
Google Meet

Meeting:
Product Architecture #42

Timestamp:
14:24:12

Speaker:
CEO

Evidence:
"We should add..."
```

The Evidence Drawer should feel like a first-class part of the product.

---

# 28. Signature UI Component: Conflict Review

Example:

```text
CURRENT STATE

BA
 ↓
Project
 ↓
Functional
 ↓
Tech

PROPOSED CHANGE

Onboarding
 ↓
BA
 ↓
Project
 ↓
Functional
 ↓
Tech

SOURCE:
Google Meet #42

[ Approve ]
[ Keep current ]
[ Mark unresolved ]
```

Never use a misleading “Fix with AI” button for high-impact changes.

---

# 29. Frontend Pages — MVP

Build these first:

```text
1. Overview
2. Project State
3. Meetings
4. Meeting Detail
5. Conflict Center
6. Evidence Drawer
```

Then:

```text
7. Decisions
8. Sources
9. AI Workforce
10. Search
```

---

# 30. Product Language

Use precise language.

Good:

```text
Proposal detected
Potential conflict
Requires review
Evidence
Current state
Proposed change
Confirmed decision
Superseded
```

Avoid:

```text
AI magic
AI knows
AI solved everything
Amazing insight
Autonomous brain
```

The system must communicate confidence without pretending certainty.

---

# 31. Naming Conventions

Use stable, explicit entity IDs.

Examples:

```text
project: proj_123
meeting: meet_042
decision: dec_019
requirement: req_014
conflict: conflict_007
evidence: ev_1834
agent_run: run_0091
state_version: v18
```

Avoid ambiguous IDs and database-generated integers in user-facing references when traceability matters.

---

# 32. Suggested Domain Model

Core entities:

```text
Workspace
Project
User
Membership
SourceConnection
SourceEvent
Meeting
Transcript
TranscriptEntry
Evidence
ProjectEntity
Requirement
Decision
Proposal
Assumption
Question
Conflict
ProjectState
ProjectStateVersion
StateChange
Agent
AgentRun
AgentArtifact
Approval
AuditEvent
```

The model may evolve; do not create every table before validating the flow.

---

# 33. Event Model

Prefer event records that are append-only at the ingestion boundary.

Example:

```json
{
  "event_id": "evt_123",
  "tenant_id": "tenant_001",
  "project_id": "proj_123",
  "source": "google_meet",
  "source_event_id": "abc",
  "event_type": "transcript_entry",
  "actor_id": "user_123",
  "occurred_at": "2026-09-23T14:24:12+05:30",
  "payload": {},
  "ingested_at": "2026-09-23T14:28:01+05:30"
}
```

Never assume source event delivery is exactly once.

---

# 34. Project State Update Model

State changes should be expressed as operations.

Example:

```json
{
  "change_id": "chg_008",
  "state_version_before": 17,
  "operation": "insert_node",
  "target": "agent_workflow",
  "value": {
    "agent": "onboarding",
    "position": 1
  },
  "reason": "Approved architecture change",
  "evidence_ids": ["ev_1834"],
  "approved_by": ["user_001", "user_002"]
}
```

This is safer than directly replacing an entire JSON blob.

---

# 35. API Design Principles

APIs should be:

- explicit
- versioned
- idempotent where appropriate
- tenant-scoped
- permission-checked
- observable

Potential endpoints:

```text
POST   /auth/google/start
GET    /auth/google/callback

GET    /projects
GET    /projects/{id}/state
GET    /projects/{id}/state/history

GET    /projects/{id}/meetings
GET    /meetings/{id}
GET    /meetings/{id}/transcript

GET    /projects/{id}/decisions
GET    /projects/{id}/conflicts
POST   /conflicts/{id}/approve
POST   /conflicts/{id}/reject

GET    /projects/{id}/sources
POST   /sources/connect
POST   /sources/{id}/disconnect

GET    /projects/{id}/agents
GET    /agents/{id}/runs
```

Exact routes can change; maintain consistency rather than following this list blindly.

---

# 36. Testing Strategy

Testing must cover more than CRUD.

## Unit tests

- normalization
- classification
- state transitions
- permission checks
- conflict rules

## Integration tests

- Google OAuth
- source ingestion
- database persistence
- queue execution

## Evaluation tests

Create a curated dataset of real/representative meeting excerpts.

Evaluate:

```text
decision precision
proposal precision
requirement extraction
conflict detection
evidence attachment
```

## Adversarial tests

Test cases such as:

```text
"Maybe..."
"I think..."
"We could..."
"Let's discuss..."
"I am not agreeing yet..."
"Okay, approved."
"Let's reverse yesterday's decision."
```

The model must not collapse these into one category.

---

# 37. AI Evaluation Principle

Do not evaluate an AI agent only by asking:

> Does the answer sound good?

Evaluate:

> Is the extracted knowledge correct, supported by evidence, and consistent with current Project State?

For example, a beautifully written summary that incorrectly states a proposal as a decision is a failure.

---

# 38. Observability

Every meaningful AI operation should record:

```text
request ID
project ID
agent
model
prompt/version identifier
input references
output schema
latency
token/cost metrics where available
validation result
final state impact
```

Use Langfuse or equivalent instrumentation.

Do not log sensitive raw content unnecessarily.

---

# 39. Enterprise Implementation Strategy

Build in controlled vertical slices.

## Slice A — Trust foundation

```text
Identity
↓
Authorization
↓
Project isolation
↓
PostgreSQL integrity
↓
Audit
```

## Slice B — Source reliability

```text
Google Meet
Slack
Excalidraw
↓
Normalized events
↓
Evidence
```

## Slice C — Shared Synesis Agent

```text
Incoming event
↓
Project resolution
↓
Context retrieval
↓
Agent orchestration
↓
Specialist capability dispatch when needed
```

## Slice D — Governed project state

```text
Candidate knowledge
↓
Validation
↓
Conflict / impact
↓
Approval when required
↓
Project State
```

## Slice E — Living Excalidraw Workspace

```text
Approved knowledge/state
↓
Structured visual operation
↓
Excalidraw workspace
↓
Sync status / audit
```

## Slice F — Enterprise reliability

```text
Queues
Retries
Idempotency
Recovery
Observability
Backups
Deployment
```

## Enterprise validation scenario

The most important end-to-end test is:

1. Create a project.
2. Initialize the project's context automatically.
3. Connect Google Meet, Slack, and Excalidraw.
4. Receive real source activity.
5. Normalize it into evidence.
6. Process it through the shared Synesis Agent using only the selected project context.
7. Persist structured knowledge in PostgreSQL.
8. Update Project State through the governed change lifecycle.
9. Require approval for high-impact changes.
10. Reflect approved/appropriate information in Excalidraw.
11. Record agent execution lineage.
12. Verify a second project cannot access the first project's context, data, tools, or Excalidraw.
13. Verify failure, retry, and recovery behavior.

Do not execute the whole roadmap as one uncontrolled rewrite.

# 41. Engineering Decision Rules for Future LLMs

When making implementation decisions:

### Prefer simplicity

Do not introduce infrastructure unless it solves a demonstrated problem.

### Prefer explicit state over hidden memory

Persist important information in structured storage.

### Prefer deterministic logic for critical state transitions

Do not let an LLM decide things that can be enforced with normal application code.

### Preserve provenance

Never create important knowledge with no source reference.

### Design for failure

Assume APIs, networks, workers, and models fail.

### Keep provider-specific code isolated

Do not let Google Meet, Slack, or Zoom concepts leak through the whole domain layer.

### Avoid premature microservices

Start with a modular monolith.

### Never expose secrets client-side

OAuth secrets and refresh tokens belong in secure server-side storage.

### Do not invent requirements

When requirements are missing or ambiguous, surface the ambiguity.

---

# 42. What the LLM Should Ask Itself Before Changing Code

Before modifying the repository, the coding assistant should determine:

```text
1. Which product requirement does this change support?
2. Which module owns this responsibility?
3. Does this introduce provider-specific coupling?
4. Is the change tenant-safe?
5. Is the change observable?
6. Is the change idempotent if processing events?
7. Does this change affect Project State integrity?
8. Does it require human approval?
9. What tests prove the behavior?
10. Does the existing architecture already provide a reusable abstraction?
```

Avoid making architectural changes simply because they are technically elegant.

---

# 43. Anti-Patterns

Do NOT:

```text
- Put LLM logic directly in route handlers
- Store project truth only in vector embeddings
- Let the model directly mutate core state
- Use one giant prompt for the whole platform
- Couple every service to Google Meet
- Build microservices before scale requires them
- Add five databases because each has a specialized feature
- Expose OAuth secrets to the frontend
- Automatically accept high-impact architecture changes
- Build a generic AI chat UI and call it the product
```

---

# 44. Strategic Product Differentiation

The likely differentiating layer is not:

```text
transcription
OAuth
RAG
meeting summaries
generic AI agents
```

Those are infrastructure/capability layers.

The differentiated product should be:

```text
Evidence-backed Project State
+
Change Detection
+
Conflict Detection
+
Provenance
+
Human-controlled State Transitions
+
Shared context for AI Workforce
```

That should influence architecture and prioritization.

---

# 45. Enterprise Readiness Status

Never infer readiness from documentation alone.

For each subsystem classify:

```text
Implemented
Verified
Partially Verified
Demo / Simulation
Unverified
Broken
Blocked
```

A coding assistant must inspect the repository, runtime, configuration, tests, and real integration behavior before declaring an enterprise capability complete.

Pay particular attention to any simulated Excalidraw ingestion path and verify whether it is a real integration or demonstration behavior.

# 47. Final Mental Model

```text
                       SYNESIS AGENT
                              |
           +------------------+------------------+
           |                  |                  |
        Project A          Project B          Project C
           |                  |                  |
      isolated context   isolated context   isolated context
           |                  |                  |
        PostgreSQL       PostgreSQL         PostgreSQL
           |                  |                  |
       Excalidraw A      Excalidraw B       Excalidraw C
```

Sources are inputs.

Evidence is the trust layer.

PostgreSQL is the system of record.

Project State is the authoritative project representation and remains historically versioned.

The Synesis Agent is shared.

Project context, data, permissions, tools, and visual workspaces are isolated.

Excalidraw is the living human-facing visual workspace.

Humans govern consequential changes.

# 48. One-Sentence Definition

> **Synesis is an enterprise project intelligence platform where one shared AI agent transforms authorized project activity into evidence-backed Project State, governed project actions, and living Excalidraw workspaces.**
