# AGENTS.md — Synora

## Repo boundaries
- Work ONLY in `E:\webstack\trikaal\Synora`. Never read, copy to, or commit in `E:\webstack\trikaal\synora_2` (stale clone) or `E:\webstack\trikaal\vexa-local` (Vexa checkout; secrets live there).
- Branches: `main` is the product. `Version_2_gpt` is UI-only — pull from it, never push to it unless explicitly asked.

## Runtime topology (memorize the ports)
- Backend `:8000` — MUST start with CWD `backend/` (SQLite path resolves from CWD; repo-root `synora.db` vs `backend/synora.db` confusion is the classic bug — always verify with a query, never assume).
- Frontend `:3002` — `:3000`/`:3001` serve the stale `synora_2` builds. If the UI looks outdated, check the port first. Launchers (`start.bat`, `start_frontend.bat`) pin 3002.
- Backend serves the API the frontend expects; a stale backend on :8000 (orphaned reload workers ghost-hold the port after the parent dies) serves stale code — kill by PID, confirm the port is free, then start one holder.

## Interpreters (do not mix them)
- Server/tests: `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe`
- Quick scripts: anaconda3 python. Only anaconda3 has `soundcard`.
- `av==13.1.0` is pinned (v19 blocked by Application Control); `KMP_DUPLICATE_LIB_OK=TRUE` is forced in code for faster-whisper — do not remove.
- Backend import path: `PYTHONPATH=backend` (package is `backend/app/...` imported as `app.*`).

## Verify before claiming
- Backend: `python -m pytest backend/tests -q` from repo root (full suite ~2 min; use `-k` to focus).
- Frontend: `npx tsc --noEmit` from `frontend/`.
- Windows console is cp1252: never print non-ASCII (Hindi, emoji) to stdout — use `ascii()` or write files.
- PowerShell: no `2>/dev/null`, no bash `for` loops, quote carefully; prefer `python -c` / script files over inline shell pipelines.

## External services (quotas rule everything)
- Groq TPM quota (8000/min, org-wide) is the bottleneck: router fires 24 rapid calls, sync loop polls every 30s. Expect 429s; semantic features degrade to deterministic fallbacks. Never burn the batch — pace or backoff.
- Sarvam (STT primary, diarization, Hindi) → Whisper fallback (no diarization). Sarvam Translate rejects `source_language_code: "auto"` — detect source locally.
- Vexa needs Docker Desktop running + admitted bot (`awaiting_admission` until a human admits it). All Vexa work stops with Docker.
- Meta provider is dormant until `META_API_KEY` + base URL are supplied.

## Domain invariants (do not break)
- Evidence rows are immutable ground truth: meeting delete nulls links, never deletes rows. Project delete wipes project-scoped rows.
- Candidates are NOT memory until approved. Memory (`project_states`) is versioned and per-project scoped; cross-project queries must never leak.
- Canvas text: all text is server-side wrapped to container width (`_wrap_text`), `autoResize` must stay `False`, heights must grow with wrapped lines. Excalidraw never wraps for you.
- Canvas freedom rule: the agent is free-form on canvas **except project columns**. Project Atlas columns are the only workspace boundary (one column per project, enforced in `workspace_atlas_service.py`); the meeting canvas is fully unconstrained (`constraints=None`) — no columns, no fixed sections.
- `_is_agent_managed` decides what sync preserves: every compiler/atlas id scheme must be listed there or stale elements live forever.
- Speakers stay generic (`SPEAKER_00` etc.). No real-name resolution.
- Auth is per-browser `synesis_user_id`; test user `usr_muj84tlniw01yh5w`. Session identity is localStorage with copy/restore UI (no real OAuth yet).

## Deploy
- DB: SQLite local; Neon Postgres cloud (`DATABASE_URL`, pooled, `?sslmode=require`). `database.py` pins the psycopg3 dialect with pg8000 fallback — keep both drivers in `requirements.txt`.
- Render deploys `main` via `render.yaml` (backend + frontend + 2 workers). Secrets shared via the `synora-secrets` env group — workers cannot reference a web service's generated vars. Whisper + Vexa stay OFF in cloud.
- Neon CLI + skills: `.agents/skills/neon*`, `skills-lock.json` committed. `neon connection-string --project-id <id> --pooled` for URLs. Never print secrets; write them to files programmatically.

## Test tooling
- `.opencode/skills/synora-reset-retest/` — reset + retest workflow (`SKILL.md`, `scripts/reset_retest.py`, `references/`). Correct order: ingest → process → route → re-process (route needs evidence to exist).
