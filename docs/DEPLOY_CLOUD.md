# Cloud database + deploy (Neon + Render)

Target architecture:

```text
Neon Postgres  <--  Render: synora-backend (Docker)
                   Render: synora-frontend (Docker)
                   Render: synora-worker (Docker, WhatsApp batch)
```

Redis is intentionally not provisioned: the backend does not use Redis
(the local compose entry is unused). Vexa is intentionally not on Render
(see §5).

## 1. Create the Neon database (you do this once)

1. Sign up at https://neon.tech (free tier is enough to start).
2. New project -> name `synora` -> region closest to you -> Postgres 16+.
3. Open the project dashboard -> **Connection Details** -> check **Pooled**
   connection -> copy the connection string. It looks like:
   `postgresql://<user>:<password>@<host>.neon.tech/<db>?sslmode=require`
4. Keep the `?sslmode=require` suffix: Neon refuses non-TLS connections and
   SQLAlchemy passes it through to psycopg.

No schema setup needed: the backend runs `Base.metadata.create_all()` on boot,
so tables are created on first connect. This is a fresh database; local SQLite
history is not migrated (see §6 if you later want it).

## 2. Deploy on Render (blueprint)

1. Push `main` (contains `render.yaml`, the Postgres driver, PORT-aware
   backend CMD, and the runtime-config frontend).
2. dashboard.render.com -> **New +** -> **Blueprint** -> select the Synora repo.
3. Render shows three services: `synora-backend`, `synora-frontend`,
   `synora-worker`. Click **Apply**.
4. When prompted for `sync: false` values, fill in:
   - `DATABASE_URL`: the Neon pooled string from §1 (backend AND worker).
   - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (Google Cloud console).
   - `GEMINI_API_KEY` and/or `GROQ_API_KEY`.
   - `SARVAM_API_KEY` (cloud STT path; local Whisper is OFF here, see §4).
5. First deploy takes several minutes (Docker builds). Backend health check is
   `/health/ready`.

## 3. Post-deploy checks

```text
https://synora-backend.onrender.com/health/ready  -> 200
https://synora-backend.onrender.com/docs           -> API docs
https://synora-frontend.onrender.com               -> UI, talking to backend
```

In the Google Cloud console, the OAuth redirect must be exactly:
`https://synora-backend.onrender.com/auth/google/callback`
(render.yaml already sets `GOOGLE_REDIRECT_URI` to this).

## 4. What is deliberately OFF in the cloud

| Feature | State | Why |
|---|---|---|
| `VEXA_ENABLED` | `false` | Vexa's 13 containers need a real Docker daemon (bot spawning, 6.5 GB browser image). Render cannot run them. Meet capture keeps working against a local backend + local Vexa. |
| `WHISPER_ENABLED` | `false` | Free tier has neither the RAM nor the disk for `large-v3-turbo`. Sarvam (`SARVAM_API_KEY`) is the transcription path in the cloud. |
| Redis | absent | Unused by the backend. |

## 5. Vexa in the cloud (later, VPS)

When Meet capture must work remotely: rent a small VPS with Docker (Hetzner
CX22-class is enough to start), clone the Vexa checkout there, bring up the
same compose stack, then set the cloud backend's `VEXA_ENABLED=true` and
`VEXA_BASE_URL=https://<vps-host>:18056` (behind TLS). No code changes: the
adapter reads the base URL from configuration. The transcription unit in that
topology should be Sarvam (no GPU on a small VPS) or a GPU box for local STT.

## 6. Notes

- Free-tier Render services sleep after inactivity: first request after idle
  takes ~1 minute. The 30-second visual-sync loop and WhatsApp polling only
  run while the backend is awake.
- `SECRET_KEY` / `ENCRYPTION_KEY` use `generateValue`: Render mints them once.
  Back them up if you ever recreate the services (encrypted OAuth tokens in
  Neon depend on `ENCRYPTION_KEY`).
- SQLite (`synesis.db`) remains the local dev database; nothing about local
  development changes.
