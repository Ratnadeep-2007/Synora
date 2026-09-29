# Synora Enterprise System Architecture

## Purpose

Synora is a multi-source project intelligence system. It continuously turns authorized project activity into evidence-backed project knowledge, governed project changes, and a living visual Excalidraw workspace.

## Canonical Runtime Model

There is **ONE SHARED SYNORA AGENT**.

A project is a **context and security boundary**, not a separate agent. The same logical agent operates on many projects by receiving an explicit project-scoped context and permissions. Specialist capabilities (Business Analysis, Project Planning, Functional Analysis, Technical Architecture, Frappe / ERP Implementation) are modular sub-capabilities of the single agent, not independent user-facing agents or separate memory silos.

```text
Google Meet ─┐
WhatsApp ────┼──→ Normalize → SourceEvent
Slack ───────┤                    │
Excalidraw ──┘                    │
                                  ▼
                ┌───────────────────────────────────┐
                │   Unified Context Intelligence    │
                │    (ContextResolutionService)     │
                └─────────────────┬─────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
            Context Resolution          Knowledge Extraction
         ("Which project is this?")     ("What does this mean?")
                    │                           │
                    └─────────────┬─────────────┘
                                  ▼
                            Resolution Join
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
          Resolved            Ambiguous          Unresolved
       (Authorized)               │                   │
              │                   └─────────┬─────────┘
              ▼                             ▼
        Target Project               Unknown Context
              │                   (proj_unknown_context)
              │                             │
              │                     Human Triage Queue
              │                 (Assign / Keep / Create)
              ▼
   PostgreSQL Project State
              │
       ┌──────┴──────┐
       ▼             ▼
 Governed State   VisualPlan
     Change          │
       │             ▼
       │     ExcalidrawCompiler (Deterministic)
       │             │
       └──────┬──────┘
              ▼
       Human Approval (Proposals & Visual Diff)
              │
              ▼
  Living Excalidraw Workspace (Immutable Revisions)
```

## Unified Context Intelligence (Source-Agnostic)

Context resolution is strictly source-agnostic and centralized in `ContextResolutionService` (`backend/app/services/context_resolution_service.py` / `ContextIntelligenceService`).
Google Meet, WhatsApp, Slack, and Excalidraw all route into this shared engine.

### Parallel Execution Architecture

For every incoming `SourceEvent`, the intelligence layer executes two concurrent paths:
1. **Context Resolution**: Evaluates deterministic signals (explicit IDs, group/space bindings, tags, member authorization, tenant boundaries) and semantic vector similarity against project profiles.
2. **Knowledge Extraction**: Extracts semantic meaning (requirements, decisions, proposals, questions, action items, contradictions, architecture entities) without waiting for project classification.
3. **Resolution Join**: Merges context resolution and extracted knowledge into a unified `ContextResolutionResult` for downstream routing and governance.

### Signals & Scoring Policy

- **Deterministic Signals (Authoritative)**: Explicit project ID (`proj_*`), group/space ID bindings, project tags, actor project membership, tenant isolation. Deterministic authorization is strictly authoritative; semantic similarity never overrides authorization.
- **Semantic Signals**: Vector/lexical similarity between the source event and project context (vision, decisions, requirements, architecture, constraints).
- **Casual Chatter Gate**: Banter, greetings, and casual chatter are identified and discarded before database persistence to prevent state contamination.
- **Decision Confidence**:
  - High confidence ($\ge 0.75$) with authorized project: Auto-routed (`resolved`).
  - Low confidence or multiple competing projects: Flagged as `ambiguous` or `unresolved`, routed to **Unknown Context**.

## Unknown Context & Human Triage

Synora never forces uncertain information into an arbitrary project.

- **Quarantine Project**: Unassigned, ambiguous, or unmapped events route to a dedicated system project: `proj_unknown_context` ("Unknown Context").
- **Explainable Candidates**: Ambiguous items include ranked `ContextCandidate` / `PossibleProjectMatch` entries displaying deterministic score, semantic score, combined confidence, and an explanation.
- **Human Triage Actions**:
  1. **Assign to Project**: Moves the evidence and extracted knowledge to an existing authorized project, triggering state and visual proposals.
  2. **Keep Unknown**: Retains the event in Unknown Context without project assignment.
  3. **Create New Project**: Seeds a new project workspace initialized with the triage evidence.

## Google Meet Multi-Context Intelligence

Meetings are not treated as monolithic single-project events. A multi-turn Google Meet transcript is segmented into semantic windows using speaker shifts and time gaps ($\ge 45$ seconds). Each segment is independently resolved:
- Segment 1 (e.g. Synora authentication) $\rightarrow$ Routes to Synora.
- Segment 2 (e.g. Healthcare Claims) $\rightarrow$ Routes to Healthcare project.
- Segment 3 (e.g. Unrelated discussion) $\rightarrow$ Routes to Unknown Context.

Meeting evidence is linked by `segment_id` and provenance timestamps back to the provider conference.

## Visual-First Excalidraw & VisualPlan Architecture

Excalidraw is the living visual workspace and a primary source of visual evidence.

### Immutable Revision Model (`VisualRevision` / `ExcalidrawRevision`)
- Every applied visual change creates a sequentially numbered, immutable `VisualRevision` (e.g., `rev_1`, `rev_2`).
- Revisions store raw scene JSON, schema version, parent revision ID, and commit metadata.
- **Current Mode vs. Compare Mode**: Users can inspect the active scene or compare any two revisions with structured visual diffs (`added`, `removed`, `changed`).

### AI VisualPlan & Deterministic Compiler
- LLMs are **prohibited** from emitting arbitrary, raw Excalidraw JSON.
- The shared agent proposes structured `VisualPlan` objects containing:
  - `nodes`: Keyed entities with label, description, type (`system`, `service`, `database`, `actor`, `queue`, `infrastructure`, `external`, `decision`), and optional group.
  - `edges`: Directed relationships (`from`, `to`, `label`, `style`).
  - `groups`: Logical boundaries (e.g., frontend, backend, cloud).
  - `layout`: Layout direction hints (`horizontal`, `vertical`, `layered`).
- The deterministic `ExcalidrawCompiler` (`backend/app/services/excalidraw_compiler.py`):
  - Renders rectangles, diamonds, ellipses, text elements, and binding arrows.
  - Applies design-system color tokens (e.g., `#e0e7ff` / `#3730a3` for infrastructure).
  - Enforces deterministic collision avoidance, automatic spacing, and container sizing.
- High-impact visual modifications follow the governance gate:
  `VisualPlan Proposal → Visual Diff Preview → Human Approval → ExcalidrawRevision Committed`.

## Governed State & Evidence Traceability

All project state transitions and visual changes maintain complete lineage:
$$\text{Current State} \longrightarrow \text{Proposed Change} \longrightarrow \text{Extracted Knowledge} \longrightarrow \text{Evidence} \longrightarrow \text{Source Event}$$

PostgreSQL is the production system of record; pgvector powers semantic retrieval; Redis and background workers handle asynchronous ingestion; SQLite is permitted only for self-contained local testing.
