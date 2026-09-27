# Synora Product Requirements

## Product
Synora is an enterprise project-intelligence platform that continuously converts authorized project activity into evidence-backed project knowledge, governed project changes, and a living visual Excalidraw workspace.

## Core model
```
Sources → Evidence → One Shared Synora Agent
       → Project-scoped Context
       → PostgreSQL Project State
       → Governed Proposals
       → Living Excalidraw Workspace
```

There is one logical Synora Agent for the organization. Projects are context and security boundaries, not separate agents. BA, planning, functional, technical, and Frappe functions are specialist capabilities invoked by the shared agent.

## Authoritative truth
PostgreSQL is the production system of record. Project State is authoritative and historically versioned. Evidence is immutable and provenance-linked. Excalidraw is the visual workspace, not the database of record.

## Intelligence
Semantic ambiguity is handled by a local LLM through Ollama by default. Paid model providers are optional adapters. The system must never fabricate AI output when inference is unavailable.

## Sources
Initial connectors: Google Meet native transcription, Slack, WhatsApp through Baileys, and Excalidraw.

Google Meet flow:
native transcript → Workspace Events notification → Pub/Sub → worker → Meet REST transcript retrieval → persistence → Evidence → Synora Agent.

Workspace Events notifications do not contain transcript content.

WhatsApp messages enter as normalized SourceEvents. AI may propose a project match; deterministic project membership, channel/group mapping, authorization, and policy validate the assignment.

## Governance
High-impact Project State and visual changes use:
proposal → evidence → visual/state diff → human approval → apply.

Low-risk synchronization may be automatic according to policy.

## Visual workspace
Excalidraw must communicate with minimum text and maximum visual structure: nodes, arrows, grouping, concise labels, decision/requirement markers, and small evidence references. It must not become a transcript or document dump.

## Enterprise controls
Required: tenant isolation, RBAC, source permissions, audit trail, idempotency, retries, observability, encryption, retention controls, backup/restore, and explicit failure states.

## Product UI
The UI is a control room, not a chatbot. Core navigation:
Overview, Project State, Excalidraw, Meetings, Evidence, Decisions, Conflicts, Agent, Sources, Settings.

The Agent view presents one shared Synora Agent and its specialist capabilities. It must not present a collection of independent agents.
