# Synesis — Google OAuth Manual & Integration Testing Guide

This guide provides step-by-step instructions for testing the Google OAuth flow with a **real Google account** and verifying that credentials are securely stored server-side.

---

## Prerequisites

1. **Google Cloud Project** with **Google Meet API** enabled.
2. **OAuth 2.0 Client ID** created in the Google Cloud Console (type: **Web application**).
3. OAuth Consent Screen configured with the required scope:
   - `https://www.googleapis.com/auth/meetings.space.readonly`
   - (Optional but recommended): `openid`, `email`, `profile`

---

## Step 1: Configure Authorized Redirect URI in Google Cloud Console

1. Navigate to [Google Cloud Console](https://console.cloud.google.com/).
2. Go to **APIs & Services** > **Credentials**.
3. Click your OAuth 2.0 Client ID to edit it.
4. Under **Authorized redirect URIs**, add:
   ```text
   http://localhost:8000/auth/google/callback
   ```
5. Click **Save**.

> **Note:** If your OAuth consent screen is in **Testing** publishing status, ensure your personal Google account email is added under **Test users** in the OAuth consent screen settings.

---

## Step 2: Configure Environment Variables

In `E:\webstack\trikaal\Synora\backend` (or project root):

1. Create a `.env` file from the example:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in your actual credentials:
   ```env
   # Google Cloud Credentials
   GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
   GOOGLE_CLIENT_SECRET="GOCSPX-your-client-secret"
   GOOGLE_REDIRECT_URI="http://localhost:8000/auth/google/callback"

   # Secret keys (generate random strings for production)
   SECRET_KEY="your-strong-random-state-secret"
   ENCRYPTION_KEY="your-strong-random-encryption-passphrase"

   # Database (defaults to local sqlite)
   DATABASE_URL="sqlite:///./synesis.db"
   ```

---

## Step 3: Start the Backend Server

Run from the project root or `backend/` directory:

```bash
python run_backend.py
```

Or using `uvicorn` directly:
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify the server is running by opening:
- API Overview: [http://localhost:8000](http://localhost:8000)
- Health Check: [http://localhost:8000/health](http://localhost:8000/health)
- Swagger Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Ensure `"configured": true` appears under `google_oauth` in the health response.

---

## Step 4: Test Authorization Flow in Browser

### 4.1 Initiate Flow
Open your browser and navigate to:
```text
http://localhost:8000/auth/google
```

**Expected behavior:**
1. Your browser will be redirected to `accounts.google.com`.
2. The Google account chooser / login page will appear.
3. The Google consent screen will display, asking for permission to:
   - **"See your Google Meet spaces and conferences"** (`meetings.space.readonly`)
4. An HTTP-only secure cookie named `synesis_oauth_nonce` will be set on `localhost`.

### 4.2 Consent & Callback
1. Select your Google test user account and click **Allow** (or **Continue** if Google displays an "unverified app" warning for testing apps).
2. Google redirects your browser back to:
   ```text
   http://localhost:8000/auth/google/callback?code=...&state=...
   ```
3. A confirmation page will appear with a green badge:
   - **Google Meet Connected**
   - Displays **Connection ID**, **User ID**, and connected **Email**.
   - Note: No client secrets or tokens are exposed to the browser.

---

## Step 5: Verify Secure Server-Side Storage

1. Inspect the local SQLite database to confirm tokens are encrypted at rest:
   ```bash
   python -c "import sqlite3; conn = sqlite3.connect('backend/synesis.db'); c = conn.cursor(); print(c.execute('SELECT id, user_id, provider, provider_account_email, status, encrypted_credentials FROM source_connections').fetchall())"
   ```
2. **Observe:**
   - The `encrypted_credentials` column contains a Fernet ciphertext starting with `gAAAAA...`.
   - The raw `access_token` (`ya29...`) and `refresh_token` (`1//0...`) are **never** stored in plaintext.

---

## Step 6: Test Token Refresh

To test refreshing the access token via the API:

```bash
curl -X POST "http://localhost:8000/auth/google/refresh?force=true" -H "X-User-ID: usr_synesis_default"
```

**Expected response (HTTP 200):**
```json
{
  "success": true,
  "message": "Google access token refreshed successfully.",
  "connection": {
    "provider": "google",
    "provider_account_id": "...",
    "provider_account_email": "your_email@gmail.com",
    "status": "active",
    "scopes": "https://www.googleapis.com/auth/meetings.space.readonly ...",
    "id": "conn_...",
    "user_id": "usr_synesis_default",
    "expires_at": "...",
    "created_at": "...",
    "updated_at": "..."
  }
}
```
*Note:* The response metadata contains no tokens or secrets.

---

## Step 7: Test Disconnect & Token Revocation

To disconnect the account and revoke Google credentials:

```bash
curl -X POST "http://localhost:8000/auth/google/disconnect" -H "X-User-ID: usr_synesis_default"
```

**Expected response (HTTP 200):**
```json
{
  "success": true,
  "message": "Google account disconnected and tokens revoked.",
  "connection_id": "conn_...",
  "status": "disconnected"
}
```

Verify in database that the connection status is now `"disconnected"`.

---

## Step 8: Test Error Handling

1. **User cancels consent:**
   - Visit `http://localhost:8000/auth/google`.
   - On the Google consent screen, click **Cancel**.
   - Google redirects to `/auth/google/callback?error=access_denied`.
   - Backend returns HTTP 400 with `error: "access_denied"`.

2. **Invalid / Tampered State (CSRF prevention):**
   - Attempt to call:
     ```text
     http://localhost:8000/auth/google/callback?code=mock_code&state=tampered_value
     ```
   - Backend returns HTTP 400 with `error: "invalid_state"` and rejects the request.

---

## Acceptance Criteria Checklist

- [x] User can start OAuth flow via `GET /auth/google`
- [x] Google consent screen appears with `meetings.space.readonly` scope
- [x] Callback `GET /auth/google/callback` succeeds and associates with Synesis user
- [x] Tokens are encrypted at rest with AES/Fernet in database
- [x] No access token, refresh token, or client secret is exposed to frontend JavaScript
- [x] Token refresh works via `POST /auth/google/refresh`
- [x] Disconnect/revocation state works via `POST /auth/google/disconnect`
- [x] 36 unit tests pass with mocked responses
