# Synesis Backend — Google OAuth (Phase 1)

This module implements Phase 1 of the Synesis project intelligence backend: **Google OAuth Integration**.

## Architecture & Security Principles

1. **Strict Secret Isolation**:
   - Client secrets, access tokens, and refresh tokens are **never** exposed to frontend JavaScript or client API responses.
   - Public schemas (`SourceConnectionRead`) only expose safe metadata: `id`, `provider`, `status`, `expires_at`, `created_at`.
2. **Encrypted Credentials at Rest**:
   - OAuth tokens are encrypted using AES-128-CBC with HMAC-SHA256 authenticated encryption (`cryptography.fernet.Fernet`).
   - Keys can be 32-byte Fernet keys or derived passphrases via deterministic SHA-256 derivation.
3. **CSRF-Safe State Token**:
   - State tokens are constructed with a cryptographic nonce, user identifier, optional return URL, and timestamp.
   - Tamper-proof HMAC-SHA256 signature ensures state cannot be forged.
   - Double-submit HTTP-only session cookie (`synesis_oauth_nonce`) prevents cross-site request forgery and login CSRF attacks.
   - 10-minute expiry window blocks replay attacks.
4. **GoogleOAuthService Abstraction**:
   - All OAuth network communication, token exchange, and refresh logic is encapsulated within `GoogleOAuthService` to prevent leaking details into unrelated modules.
5. **Database Models**:
   - `User`: Synesis user entity.
   - `SourceConnection`: Tracks provider (`google`), `provider_account_id` (Google `sub`), `status`, `encrypted_credentials`, `scopes`, and timestamps.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/auth/google` | Initiates Google OAuth flow (307 redirect to Google consent) |
| `GET` | `/auth/google/callback` | OAuth callback, exchanges code, encrypts and persists credentials |
| `POST` | `/auth/google/refresh` | Refreshes expired credentials using stored refresh token |
| `POST` | `/auth/google/disconnect` | Revokes Google token and marks connection disconnected |
| `GET` | `/auth/google/connections` | Lists connections for user (strictly excludes secrets) |
| `GET` | `/health` | Health check endpoint |
| `GET` | `/docs` | Interactive Swagger API documentation |

## Quick Start

### 1. Configure Environment
```bash
cp .env.example .env
```
Fill in `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

### 2. Run Tests
```bash
python -m pytest backend/tests -v
```

### 3. Run Server
```bash
python run_backend.py
```
Visit [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive Swagger documentation.

For complete real-account testing instructions, see [MANUAL_TESTING.md](MANUAL_TESTING.md).
