# Synora Enterprise System Design

## Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                          ONE SYNORA AGENT                              │
│                    Shared Intelligence Pipeline                        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
Sources (Meet, WhatsApp, Slack, Excalidraw)
    ↓
Normalized SourceEvent
    ↓
┌────────────────────────────────────────────────────────────────────────┐
│                   ContextResolutionService (Parallel)                  │
│  ┌───────────────────────────────┐  ┌────────────────────────────────┐ │
│  │      Context Resolution       │  │      Knowledge Extraction      │ │
│  │   Deterministic + Semantic    │  │  Requirements, Decisions, etc. │ │
│  └───────────────┬───────────────┘  └────────────────┬───────────────┘ │
└──────────────────┼───────────────────────────────────┼─────────────────┘
                   └─────────────────┬─────────────────┘
                                     ▼
                               Resolution Join
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
       Authorized Project ID                      Unknown Context
                 │                             (proj_unknown_context)
                 ▼                                       │
      PostgreSQL Project State                   Human Triage Queue
                 │                                       │
        ┌────────┴────────┐                              ▼
        ▼                 ▼                     (Assign/Keep/Create)
 Governed State      VisualPlan
     Proposal             │
        │                 ▼
        │        ExcalidrawCompiler (Deterministic)
        │                 │
        └────────┬────────┘
                 ▼
          Human Approval (Visual Diff Preview)
                 │
                 ▼
     Living Excalidraw Workspace (VisualRevision)
```

## Core Architectural Invariants

1. **One Shared Synora Agent**: There are no independent user-facing specialist agents. BA, Project Planning, Functional Analysis, Technical Architecture, and Frappe Implementation are capabilities within the single agent pipeline.
2. **Context as Boundary**: Projects are security and context boundaries. Authorization is enforced deterministically; semantic similarity never grants project access.
3. **Parallel Ingestion**: For every incoming `SourceEvent`, context resolution ("Which project?") and knowledge extraction ("What does it mean?") run concurrently on read-only snapshots before joining into routing decisions.
4. **Google Meet Segment Intelligence**: Native Google Meet transcripts use bounded 45-second / 12-entry session windows with speaker and timestamp provenance; each window resolves independently to its relevant project or Unknown Context.
5. **Meet Session Projection**: After shared Project Memory updates, MeetingSessionIntelligence adds topics, decisions, requirements, action items with owner/due hints, open questions, and per-project memory version deltas. It is stored in existing Meeting metadata, not as a second memory store.
6. **Unknown Context Quarantine**: Ambiguous or unassigned events route to `proj_unknown_context`. The system provides explainable candidate matches (`ContextCandidate` / `PossibleProjectMatch`) with deterministic and semantic scores, awaiting human triage (`Assign to Project`, `Keep Unknown`, `Create New Project`).
7. **Visual-First Excalidraw & VisualPlan**:
   - The model emits structured `VisualPlan` (`nodes`, `edges`, `groups`, `layout`), never direct Excalidraw JSON.
   - `ExcalidrawCompiler` deterministically handles collision avoidance, coordinates, and styling (including `infrastructure`, `system`, `actor`, `database`).
   - Every change commits an immutable `VisualRevision` (`ExcalidrawRevision`) supporting Current view and Compare mode with structured diffs (`added`, `removed`, `changed`).
8. **Zero Casual Chatter State Contamination**: Casual greetings and chatter are detected and discarded prior to database persistence.
9. **Authoritative Persistence**: PostgreSQL + pgvector is the system of record. Evidence is immutable and linked to source events by foreign keys.
