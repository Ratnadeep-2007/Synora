# Synora memory and context plan

This file records the implementation state for the active `Synora` checkout.
The earlier context capability score of 69/100 was a code-review estimate,
not a measured benchmark. No new overall quality score is claimed here.

## Architecture and invariants

1. **Evidence ledger:** source text and original media are retained with source,
   time, scope, processing status, and links from derived text. Evidence is the
   factual record; generated canvas text and agent answers are not evidence.
2. **Claims:** extracted decisions, requirements, actions, assumptions,
   proposals, and conflicts retain status, provenance, and revision history.
   Proposals do not become approved project state until the applicable review
   policy accepts them. A replacement conflict leaves the active state intact.
3. **Project state:** `ProjectState` remains the canonical, versioned approved
   view. Retrieval and optional external services are derived layers.
4. **Working context:** each task receives a bounded, scoped selection of
   approved state and source excerpts with omissions recorded.
5. **Authorization:** workspace/project membership is checked before scoped
   reads and writes. Similarity and continuity can suggest a destination; they
   do not authorize cross-project assignment.

## Implementation status

### 1. Evaluation corpus and baseline — partial

- Added `fixtures/eval/context_eval_v1.json` with 18 synthetic routing cases for
  explicit IDs/tags, Hinglish, transcription errors, media text, duplicates,
  ambiguous project names, topic switches, short replies, and safe abstention.
- Added `scripts/run_context_eval.py` and `context_eval.py` for reproducible,
  offline routing-policy metrics and a JSON report.
- The semantic candidate list is supplied by a per-case stub. The observed
  1.0 routing precision/recall and 0 wrong routes therefore describe this
  fixture's resolver-policy behavior only. They are **not** live model quality,
  semantic retrieval quality, or a production accuracy score.
- Still needed: human-labeled, held-out source examples; retrieval recall and
  citation support metrics; unsupported-claim and correction-rate measures;
  report versioning and a paced live-provider evaluation that avoids quota
  spikes. Mem0 has not passed an adoption benchmark.

### 2. Bounded retrieval, durable indexes, and jobs — implemented; scale gate open

- Token-based lexical ranking and aliases search a bounded candidate set before
  limiting results. The retrieval layer validates tenant/project scope and
  excludes rejected or superseded claims from ordinary memory context.
- Context packing uses a configurable serialized-byte budget (default 18,000
  bytes, roughly 6,000 tokens at the configured estimate of 3 bytes/token).
  This is not an exact model tokenizer. Omissions and source offsets are kept.
- Added persisted `MemoryIndex` chunks and indexed `MemoryTerm` rows. Index and
  embedding jobs are written transactionally from evidence/claim changes,
  leased by the worker, bounded per tick, retried, and dead-lettered.
- Embeddings store provider/model metadata. A changed content hash or configured
  model invalidates the existing index. Lexical-hash fallback is not described
  as semantic search. Semantic ranking currently scans at most 2,500 scoped
  vectors; this is not an ANN/pgvector index and needs load testing before large
  archives.
- Added a project memory briefing API and Project Context UI source links.
- Still needed: a measured scale target and benchmark; evaluate ANN/pgvector
  only if the bounded scan misses that target. Add operational metrics and a
  verified reindex/backfill procedure for existing production rows.

### 3. Claim validity, review, and conflict handling — implemented; migration review open

- Added append-only `MemoryClaimRevision` snapshots with support/status and
  validity dates; superseded claims close their active revision.
- Same-title changed-content decisions/requirements/constraints create a
  proposed change and open conflict. The current approved state remains active
  until review. Proposal/idea/discussion candidates are held for review.
- Exact repeats consolidate provenance instead of adding duplicate state
  entries. Conflict approval applies the replacement and marks the prior claim
  superseded; revision history is available through the memory API.
- Still needed: verify concurrent approvals against Neon/PostgreSQL, cover
  existing conflict rows without a linked state change, and provide a production
  migration/backfill plan before enabling the new tables on a live database.

### 4. Topic segmentation and continuity — implemented; routing audit open

- Added explicit switch detection, bounded transcript windows, and persisted
  stream topic windows with project scope and 45-minute expiry.
- Continuity no longer imports unrelated group context as same-thread evidence.
  Meet-to-chat context requires lexical overlap when a current message exists;
  a no-query helper call returns the recent tenant-scoped Meet context.
- Multi-project transcript spans can route independently; uncertain spans stay
  in Unknown Context. A newly created project can suggest matches for pending
  Unknown Context items without auto-assigning them.
- Still needed: held-out multi-project meetings, workspace-boundary tests for
  every resolver entry point, and evaluation of topic-switch false positives.

### 5. Bounded meeting reflection — implemented; quality gate open

- Meeting/project reflection is queued as a content-fingerprinted job and reads
  a bounded set of original evidence. It creates reviewable proposals and does
  not approve them or cite generated answers as independent evidence.
- Provider unavailability is represented as a processing result; job retries
  use the shared bounded worker policy.
- Still needed: labeled recall/precision for missed decisions/actions, source
  span checks for every reflected item, explicit unavailable-provider retry
  behavior, and a measured per-project cooldown/cost budget.

### 6. Original media and processing state — partial

- Audio/image/document originals can be retained as scoped `SourceArtifact`
  rows (10 MB cap) with hashes, extraction metadata, status, and retry jobs.
  Failed extraction stays visible and retryable; derived text is linked back to
  its original. The inbox, source list, and evidence drawer expose previews and
  download/retry actions. Manual audio transcripts remain reviewable drafts.
- Project deletion now removes project-scoped artifacts and the new memory,
  topic, and proactive-memory derivative rows. Evidence immutability applies to
  ordinary meeting deletion; project deletion removes project-owned records as
  documented in `AGENTS.md`.
- **Current artifact bytes are stored in the database.** Durable object-storage
  support and migration of existing blobs are not implemented. Add an
  S3-compatible adapter and configure it before storing substantial media in a
  production Neon database. Define retention/deletion policy for external
  object versions at the same time.
- Still needed: object-storage tests, association tests for multi-span/multi-
  evidence media, and verification of late UI fetch cancellation and retry
  idempotency.

### 7. Canvas provenance and preservation — partial

- Added a provenance pass that validates cited evidence against project and
  tenant, maps known text aliases to persisted evidence, links matched claims,
  and labels supported/inferred/conflicting records. Reconciliation preserves
  unchanged managed elements and their user positions when safe.
- Project canvas paths use provenance enrichment; the evidence inspector can
  open cited sources and original artifacts. User scene edits remain separate
  from evidence ingest and visual revisions remain versioned.
- Fixed project decision cards to show decision content instead of generic
  labels. Meeting-canvas provenance integration and systematic reconciliation
  tests across every compiler/agent ID scheme remain outstanding.
- Still needed: verify all material nodes have real claim/evidence IDs, ensure
  generated source labels never imply unsupported authority, test arrows,
  bindings, collisions, user edits, and version history through UI flows, and
  prove canvas output cannot enter the evidence ledger.

## Mem0 decision

Use the session-start, context-trigger, and scheduled-reflection patterns from
[Mem0's proactive-memory guide](https://mem0.ai/library/agent-memory/proactive-memory),
implemented in Synora's own scoped jobs and triggers. Synora's database remains
authoritative for evidence, approvals, claim history, and project state. Mem0
is an optional retrieval experiment behind an adapter; do not enable it as a
production provider until it passes the same labeled evaluation and proves
scope isolation, source traceability, correction/deletion propagation, and
acceptable latency/cost. Its SDK/API compatibility has not been verified here.

## Verification status

- Final full backend run after the fixes in this branch: **481 passed**, with
  one upstream Starlette/httpx deprecation warning. Changes include compatible
  retained-media assertions, corrected meeting segmentation and canvas text,
  cross-source continuity, review-gated replacement behavior, and deletion
  cleanup for the added memory tables.
- A focused run over the affected paths also passed: **50 passed** across direct
  media inputs, meeting windows, canvas, lifecycle, cross-source continuity,
  multisource routing, memory retrieval, evaluation, and project cleanup.
- Frontend `npx tsc --noEmit` passed before the latest backend-only fixes.
- The full backend suite must be rerun after these changes before calling the
  branch regression-clean. No live Neon migration, Render deployment, provider
  quality benchmark, or object-storage integration has been verified.
- Evaluation command: `python scripts/run_context_eval.py`. Its offline report
  is policy-only as described above. Backend suite:
  `python -m pytest backend/tests -q`. Frontend type check:
  `npx tsc --noEmit` from `frontend/`.

## Completion gates

1. Full backend suite and frontend type check pass on the final tree.
2. Human-labeled held-out evaluation reports retrieval recall, routing precision,
   abstention quality, citation support, unsupported claims, and review
   corrections without using a stubbed semantic layer for quality claims.
3. No workspace/project leakage in source retrieval, proactive triggers,
   reflection, Mem0 experiments, or canvas citations.
4. Neon migration/backfill, object storage, job recovery, and project deletion
   are exercised against isolated PostgreSQL before production deployment.
5. Canvas nodes preserve user edits/history and cite only persisted evidence;
   unresolved conflicts and inferences remain explicit.
