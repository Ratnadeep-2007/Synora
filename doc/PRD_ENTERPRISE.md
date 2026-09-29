# Synora Product Requirements Document (PRD)

## Product Vision

Synora is an enterprise project-intelligence platform that continuously converts multi-source activity into evidence-backed project knowledge, governed project changes, and a living visual Excalidraw workspace.

## Canonical Agent Model

There is **ONE SHARED SYNORA AGENT** for the organization.
- Projects are context and security boundaries, not independent agents.
- Specialist capabilities (Business Analysis, Project Planning, Functional Analysis, Technical Architecture, Frappe / ERP Implementation) are modular capabilities invoked by the single agent.
- There are no separate user-facing specialist agents and no isolated agent memory silos.

## Unified Context Intelligence & Sources

All ingestion channels—Google Meet, WhatsApp, Slack, and Excalidraw—normalize into a unified `SourceEvent` and enter a single shared context engine: `ContextResolutionService`.

1. **Parallel Ingestion**:
   - **Context Resolution**: "Which project does this belong to?" (evaluating deterministic signals and semantic vector similarity).
   - **Knowledge Extraction**: "What does this information mean?" (extracting requirements, decisions, proposals, questions, action items, architecture changes).
   - Both tasks run concurrently on read-only event snapshots before joining into routing decisions.
2. **Google Meet Multi-Context Intelligence**:
   - Google Meet native transcripts are divided into semantic windows based on speaker turns and time gaps ($\ge 45$s).
   - Individual segments resolve independently to different projects or Unknown Context. Single meetings are never locked to one project.
3. **Casual Chatter Gate**:
   - Casual banter, greetings, and chit-chat are dropped before database persistence to prevent state contamination.
4. **Unknown Context & Human Triage**:
   - Events with low confidence or unresolved project assignment are quarantined into `proj_unknown_context`.
   - The UI surfaces explainable `ContextCandidate` rankings.
   - Humans triage items via three explicit actions:
     - **Assign to Project**: Migrates event to the chosen project and triggers state/visual updates.
     - **Keep Unknown**: Retains the item in quarantine.
     - **Create New Project**: Initializes a new project workspace around the evidence.

## Visual-First Excalidraw Workspace

Excalidraw is the living visual workspace and an interactive visual intelligence artifact.

1. **VisualPlan Specification**:
   - Generative models are prohibited from directly authoring raw Excalidraw JSON.
   - The shared agent outputs structured `VisualPlan` specifications containing `nodes`, `edges`, `groups`, and `layout`.
2. **Deterministic Compiler**:
   - `ExcalidrawCompiler` translates `VisualPlan` into valid Excalidraw elements with automatic collision avoidance, node styling (e.g. `infrastructure`, `system`, `actor`), and container bounds.
3. **Immutable Revision Model**:
   - Every state change committed to the visual canvas generates an immutable `VisualRevision` (`ExcalidrawRevision`).
   - Supports **Current Mode** (interactive live view) and **Compare Mode** (structured visual diff showing added, removed, and modified elements).

## Governed State & Trust Chain

- High-impact Project State changes and visual updates follow strict governance:
  `SourceEvent → Evidence → Extracted Knowledge → Proposal → Visual/State Diff → Human Approval → Commit`.
- PostgreSQL + pgvector is the authoritative system of record.
- Complete traceability is maintained from project state back to original source evidence.
