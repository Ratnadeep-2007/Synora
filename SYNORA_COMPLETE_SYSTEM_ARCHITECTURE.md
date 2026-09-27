# Synora Enterprise System Architecture

## Purpose

Synora is a multi-source project intelligence system. It continuously turns authorized project activity into evidence-backed project knowledge, governed project changes, and a living visual Excalidraw workspace.

## Canonical runtime model

There is **one shared Synora Agent**.

A project is a **context and security boundary**, not a separate agent. The same logical agent operates on many projects by receiving an explicit project-scoped context and permissions.

```text
Google Meet ─┐
Slack ───────┼──→ Source Events → Evidence ─→ Synora Agent
WhatsApp ────┤                              │
Excalidraw ──┘                              ▼
                                      Project Context
                                             │
                                             ▼
                                  PostgreSQL Project State
                                             │
                              ┌──────────────┴──────────────┐
                              ▼                             ▼
                       Governed State Change          Visual Proposal
                              │                             │
                              └──────────────┬──────────────┘
                                             ▼
                                      Human Approval
                                             │
                                             ▼
                                   Living Excalidraw Workspace
```

## Agent and deterministic system

NVIDIA NIM + DeepSeek provides semantic intelligence:
- language understanding
- classification
- entity and relationship extraction
- contradiction interpretation
- impact analysis
- proposal composition
- visual composition suggestions

Deterministic services remain equally important and authoritative:
- authentication and authorization
- tenant/project boundary enforcement
- project assignment validation
- idempotency
- persistence and transactions
- state transitions
- approval policy
- connector checkpoints
- retries and recovery
- schema validation
- audit logging
- safe external actions

If NVIDIA NIM is unavailable, the system may use supported deterministic operations, but it must never claim that deterministic output is AI-generated or fabricate semantic results.

## Project context

Each execution context contains:
- tenant and authenticated actor
- project id
- project permissions
- current Project State
- relevant Evidence and provenance
- candidate knowledge
- approved decisions and requirements
- available tools
- current Excalidraw representation

The same Synora Agent can move between projects only through an explicit authorized context switch.

## Specialist capabilities

The shared agent invokes specialist capabilities as modules:

```text
Business Analysis
Project Planning
Functional Analysis
Technical Architecture
Frappe / ERP Implementation
```

These are not independent agents and do not own independent memory boundaries.

## Data architecture

Production:
- PostgreSQL as system of record
- pgvector for semantic retrieval
- object storage for large artifacts
- Redis and workers for asynchronous processing

Development/test may use SQLite only as a convenience when explicitly configured.

Project State is authoritative and historically versioned. Evidence is immutable and provenance-linked.

## Google Meet

Native Meet transcription is the source.

```text
Google Meet native transcription
    ↓
Workspace Events API notification
    ↓
Pub/Sub
    ↓
Synora worker
    ↓
Meet REST API
    ↓
Transcript + entries + participants
    ↓
PostgreSQL → Evidence → Synora Agent
```

Workspace Events carries the notification; Meet REST retrieves transcript content.

No browser caption scraping, meeting bots, raw-audio capture, or custom Google Meet speech-to-text is part of the canonical path.

## WhatsApp

Baileys is an external connector boundary for controlled deployments.

```text
WhatsApp → Baileys bridge → normalized SourceEvent → Evidence → Synora Agent
```

The model may propose the project a message belongs to. Deterministic policy validates that the project is an authorized destination. Uncertain mappings remain unassigned/reviewable.

## Excalidraw

Excalidraw is the living visual workspace and a source of visual evidence.

The visual representation should use minimum text and maximum visual structure:
- nodes
- arrows
- groups
- relationships
- concise labels
- decision markers
- requirement markers
- compact evidence references

It must not become a transcript dump or generic document editor.

High-impact visual changes follow:

```text
proposal → visual diff → human approval → apply
```

## Governance

High-impact changes to Project State or the visual workspace require human approval according to policy.

Every important change must be traceable:

```text
Current State
 → Change
 → Evidence
 → Source
```

## Enterprise controls

Required:
- tenant isolation
- RBAC
- source permissions
- encryption at rest
- audit trail
- retention controls
- idempotent processing
- bounded retries
- observability
- backup and restore
- explicit degraded/error states
- no fabricated metrics or status

## UI principle

The UI is a control room, not a chatbot.

Primary navigation:

```text
Overview
Project State
Excalidraw
Meetings
Evidence
Decisions
Conflicts
Agent
Sources
Settings
```

The Agent view must show one shared Synora Agent and its capabilities, with the active project context clearly visible.
