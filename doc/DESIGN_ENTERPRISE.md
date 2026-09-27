# Synora Enterprise System Design

## Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                         SYNORA AGENT                        │
│              one shared coordinator / executor             │
└──────────────────────────────┬──────────────────────────────┘
                               │ project context boundary
                 ┌─────────────┴─────────────┐
                 │ Project A                  │
                 │ Project B                  │
                 │ Project N                  │
                 └─────────────┬─────────────┘
                               │
 Sources → SourceEvent → Evidence → Semantic Analysis
                               │
                               ▼
                    PostgreSQL Project State
                               │
                  Proposal / Validation / Audit
                         ┌─────┴─────┐
                         │           │
                    State Change   Excalidraw
                         │           │
                    Human Gate  Visual Diff
```

## Deterministic boundary
Deterministic services own authorization, tenant/project isolation, persistence, idempotency, state transitions, transactionality, connector checkpoints, approval gates, and external side effects.

The LLM owns semantic interpretation: classification, extraction, entity/relationship understanding, conflict interpretation, impact analysis, and visual composition suggestions.

## Agent
The shared agent receives an explicit project context containing project identity, permissions, Project State, relevant evidence, knowledge, tools, and current visual workspace. It cannot use another project's context unless an explicitly authorized cross-project operation exists.

Specialist capabilities are modules:
- Business analysis
- Project planning
- Functional analysis
- Technical architecture
- Frappe/ERP implementation

They are not independent agents.

## Data
PostgreSQL + pgvector is the authoritative production database. Object storage is used for large artifacts. Redis/workers handle asynchronous processing.

## Visual operations
Excalidraw changes are represented as validated structured operations. High-impact changes are proposal-first. The visual diff is inspectable before apply.

## Reliability
Every connector is idempotent. Provider events are recorded before AI processing. Retries are bounded. Failed semantic inference is surfaced as unavailable/pending rather than represented as successful AI analysis.

## Security
OAuth credentials are encrypted at rest. Secrets are never logged or committed. Every project-scoped endpoint enforces server-side authorization.

## UI
Professional light interface with restrained glass/neumorphism. Warm canvas, white surfaces, deep green primary, subtle borders, Inter typography. Avoid AI gradients, robot imagery, decorative dashboards, fake metrics, and excessive cards.
