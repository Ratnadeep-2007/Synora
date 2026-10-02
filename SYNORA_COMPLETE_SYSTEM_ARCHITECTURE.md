# Synora Enterprise System Architecture

## Purpose

Synora is a multi-source project intelligence system. It continuously turns authorized project activity into evidence-backed project knowledge, governed project changes, and a living visual Excalidraw workspace.

## Canonical Runtime Model

There is **ONE SHARED SYNORA AGENT** and **ONE SHARED MEMORY ENGINE**.

A project is a strict context and security boundary. The same logical agent operates
across projects by receiving project-scoped memory and permissions. WhatsApp and
completed meeting transcripts are input sources only; they do not create separate
agents or separate memory stores.

```text
WhatsApp ─────────────┐
Completed Meet ───────┤
                      ▼
               Normalize → Evidence
                      │
                      ▼
           Unified Context Intelligence
                      │
           ┌──────────┴──────────┐
           ▼                     ▼
    Project resolved       Project unresolved
           │                     │
           ▼                     ▼
    Shared Project Memory   Unknown Context
           │                (human attention only)
           │
    ┌──────┼─────────┐
    ▼      ▼         ▼
  State  Knowledge  Provenance
    │      │         │
    └──────┼─────────┘
           ▼
      Visual Projection
           │
           ▼
   Deterministic Excalidraw
        / Project Atlas
```

### Project Memory Contract

Project Memory is a logical layer over the existing PostgreSQL records:

- `ProjectState` — canonical current project snapshot.
- `ProjectStateVersion` — immutable history of automatic memory updates.
- `CandidateKnowledge` — detailed extracted knowledge ledger.
- `Evidence` — immutable source provenance.
- `ProjectMemoryService` — shared orchestration boundary for reads and automatic promotion.

Routine evidence-backed knowledge is written automatically. Memory writes are always
scoped to the resolved `project_id`; a candidate belonging to another project is never
promoted. Normal note updates do not require a human approval step.

The only intentional human interaction in the source pipeline is **project routing
when Synora cannot establish a safe destination**. This is an ambiguity boundary, not
a note-editing workflow.

## Meeting Input Model

Google Meet is processed **after the meeting transcript is complete**. The event worker
retrieves the transcript and its entries, preserves speaker/timestamp provenance, and
routes transcript segments to project context. The same Project Memory engine then
processes the resolved evidence used by WhatsApp.

```text
Meeting ends
   ↓
Transcript ready event
   ↓
Retrieve complete transcript
   ↓
Persist transcript + entries
   ↓
Resolve segment → project
   ↓
Extract knowledge
   ↓
Update that project's memory
   ↓
Refresh Project Atlas visual notes
```

A single meeting can contribute to multiple projects. Each segment is grouped by its
resolved project before memory promotion; Unknown Context segments are not written
into a real project's memory.
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

## Unknown Context & Human Attention

Synora never forces uncertain information into an arbitrary project.

- **Quarantine Project**: Unassigned, ambiguous, or unmapped events route to a dedicated system project: `proj_unknown_context` ("Unknown Context").
- **Explainable Candidates**: Ambiguous items include ranked `ContextCandidate` / `PossibleProjectMatch` entries displaying deterministic score, semantic score, combined confidence, and an explanation.
- **Human Triage Actions**:
  1. **Assign to Project**: Routes quarantined evidence into an authorized project and triggers memory/visual synchronization.
  2. **Keep Unknown**: Retains the evidence outside project memory.
  3. **Create New Project**: Seeds a new project workspace initialized from the evidence.

## Google Meet Multi-Context Intelligence

Meetings are not treated as monolithic single-project events. A multi-turn Google Meet transcript is segmented into semantic windows using speaker shifts and time gaps ($\ge 45$ seconds). Each segment is independently resolved:
- Segment 1 (e.g. Synora authentication) $\rightarrow$ Routes to Synora.
- Segment 2 (e.g. Healthcare Claims) $\rightarrow$ Routes to Healthcare project.
- Segment 3 (e.g. Unrelated discussion) $\rightarrow$ Routes to Unknown Context.

Meeting evidence is linked by `segment_id` and provenance timestamps back to the provider conference.

### Meet Session Intelligence (source-specific projection)

Meet is intentionally specialized only after it enters the common evidence pipeline. The
session layer adds conversational structure that is useful for a completed meeting:

```text
Complete transcript
      ↓
45s / 12-entry bounded windows
      ↓
Speaker order + timestamps + entry/evidence linkage
      ↓
Shared Candidate Knowledge
      ↓
Session projection
  ├─ topics (from extracted knowledge)
  ├─ decisions / requirements / questions
  ├─ action items + owner/due hints
  └─ per-project memory version delta
      ↓
Meeting.metadata_json.session_intelligence
```

This projection is not a separate memory system. It reads the same Evidence and
CandidateKnowledge records and the same Project Memory result used by other sources.
It is exposed through `GET /meetings/{meeting_id}/intelligence` and included in meeting
detail responses for the UI. The Visual Project Atlas continues to project only shared
project memory, not a standalone meeting knowledge base.

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
- Normal memory-driven visual synchronization is automatic and produces an immutable revision.
- Existing proposal/review endpoints remain available for explicit/manual visual changes, but routine source-driven note updates do not require them.

## Governed State & Evidence Traceability

All project state transitions and visual changes maintain complete lineage:
$$\text{Current State} \longrightarrow \text{Proposed Change} \longrightarrow \text{Extracted Knowledge} \longrightarrow \text{Evidence} \longrightarrow \text{Source Event}$$

PostgreSQL is the production system of record; pgvector powers semantic retrieval; Redis and background workers handle asynchronous ingestion; SQLite is permitted only for self-contained local testing.
