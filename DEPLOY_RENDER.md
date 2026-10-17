# Render deployment

Synora uses the existing Neon project `synora` (`sweet-math-41950160`) in
`aws-ap-southeast-1`. The `main` branch already contains the application
tables. Neon Auth is enabled on that branch with email verification by code.

The Render Blueprint is [render.yaml](render.yaml). It defines two web services
and two background workers. Render does not offer free background workers, so
the workers use the smallest paid compute plan. The web services are on the
free plan and can sleep when idle.

## Before applying the Blueprint

1. Put the desired release on GitHub `main`. The Blueprint deploys `main`.
2. In Render, create or update the Blueprint from this repository.
3. Supply `DATABASE_URL` to the backend and both workers. Use the **pooled**
   connection string for the existing Neon project's `main` branch, with
   `sslmode=require`. Keep the value in Render secrets; do not commit it.
4. No email allowlist is required. Anyone can create an account and verify
   their email. The first verified account to register becomes workspace owner;
   later accounts remain pending until the owner assigns them in Settings →
   Workspace members. Make sure the intended owner registers first after the
   membership feature is deployed.
5. Set the Google OAuth and AI provider keys if those features are needed
   (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` are currently unset on
   Render, so Google Meet connect is degraded there). Google Cloud must allow
   `https://synora-oduz.onrender.com/auth/google/callback` as a redirect URI
   (the live backend slug is `synora-oduz`, not `synora-backend`).
6. Keep `SYNORA_AUTH_URL` on the frontend and the two `NEON_AUTH_*` values on
   the backend pointed at the same Neon Auth branch. The trusted frontend
   domain is already registered in Neon Auth.

`SECRET_KEY`, `ENCRYPTION_KEY`, and `WHATSAPP_WEBHOOK_SECRET` are generated in
the shared Render environment group. If a separately hosted Baileys bridge is
used, give it the same WhatsApp secret as
`SYNORA_WHATSAPP_WEBHOOK_SECRET` and point `SYNORA_BACKEND_URL` at the Render
backend. The Render Blueprint does not host Baileys or Vexa.

For a public production launch, configure a custom SMTP provider in Neon Auth.
The shared Neon mail provider is suitable for initial verification codes.

## After deploy

Open the frontend, register and verify the intended owner account first, then
confirm it can access the workspace. Register a second account and verify it;
it should see the pending assignment screen. From the owner account, open
Settings → Workspace members and assign the pending account. Confirm it can
then access shared projects. Also verify `/health/ready` responds when Neon is
reachable. Connect Google Meet from the Sources page only after configuring its
OAuth client.
