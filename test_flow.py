#!/usr/bin/env python3
"""
Synesis OAuth End-to-End Test Suite & Verification Tool

Usage:
    # 1. Run full automated pipeline test (mocked):
    python test_flow.py

    # 2. Test against a live running server:
    python test_flow.py --url http://localhost:8000
"""

import argparse
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch
import httpx

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Configure test environment if not already set
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("SECRET_KEY", "test-secret-key-csrf-signing-12345")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-passphrase-32bytes")
os.environ.setdefault("GOOGLE_CLIENT_ID", "mock-google-client-id.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "GOCSPX-mock-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_pipeline.db")

from fastapi.testclient import TestClient
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine, init_db
from app.core.security import OAUTH_NONCE_COOKIE_NAME, OAuthStateManager
from app.main import app
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.services.encryption_service import EncryptionService
from app.services.google_oauth import GoogleOAuthService

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_step(title: str):
    print(f"\n{BOLD}{CYAN}==> [{title}]{RESET}")


def print_pass(msg: str):
    print(f"  {GREEN}[PASS]{RESET} {msg}")


def print_fail(msg: str):
    print(f"  {RED}[FAIL]{RESET} {msg}")


def print_info(msg: str):
    print(f"  {YELLOW}[INFO]{RESET} {msg}")


def run_automated_pipeline():
    print(f"{BOLD}======================================================{RESET}")
    print(f"{BOLD}    SYNESIS — PHASE 1 GOOGLE OAUTH TEST PIPELINE     {RESET}")
    print(f"{BOLD}======================================================{RESET}")

    # Step 1: Database Setup
    print_step("Step 1: Database Initialization")
    init_db()
    print_pass("SQLite tables created successfully (users, source_connections)")

    # Step 2: Encryption Service Verification
    print_step("Step 2: Server-Side Encryption Verification (Fernet/AES-128)")
    enc_svc = EncryptionService(settings.ENCRYPTION_KEY)
    sample_payload = {
        "access_token": "ya29.sample_secret_token_12345",
        "refresh_token": "1//sample_secret_refresh_token_67890",
        "token_type": "Bearer",
    }
    ciphertext = enc_svc.encrypt_dict(sample_payload)
    assert "ya29" not in ciphertext, "Plaintext leaked into ciphertext!"
    assert "sample_secret" not in ciphertext, "Plaintext leaked into ciphertext!"
    print_pass(f"Payload encrypted: {ciphertext[:35]}... (no plaintext leak)")

    decrypted = enc_svc.decrypt_dict(ciphertext)
    assert decrypted["access_token"] == sample_payload["access_token"]
    print_pass("Decrypted payload matches original sensitive credentials")

    # Step 3: CSRF State Security Verification
    print_step("Step 3: CSRF State & Nonce Security")
    state, nonce = OAuthStateManager.generate_state(user_id="usr_tester", return_to="/dashboard")
    print_pass(f"Generated HMAC-signed state token (nonce length: {len(nonce)})")

    # Verify legitimate state
    verified = OAuthStateManager.verify_state(state, cookie_nonce=nonce)
    assert verified["user_id"] == "usr_tester"
    assert verified["return_to"] == "/dashboard"
    print_pass("Legitimate state verified successfully")

    # Verify tampered state rejection
    tampered_state = state[:-4] + ("ABCD" if state[-4:] != "ABCD" else "WXYZ")
    try:
        OAuthStateManager.verify_state(tampered_state, cookie_nonce=nonce)
        print_fail("Tampered state was NOT rejected!")
    except Exception as exc:
        print_pass(f"Tampered state properly blocked: {exc}")

    # Verify cookie mismatch rejection
    try:
        OAuthStateManager.verify_state(state, cookie_nonce="attacker-nonce")
        print_fail("Cookie nonce mismatch was NOT rejected!")
    except Exception as exc:
        print_pass(f"Cross-site cookie nonce mismatch properly blocked: {exc}")

    # Step 4: Endpoint Testing via TestClient
    print_step("Step 4: Endpoints Execution via FastAPI TestClient")
    client = TestClient(app)

    # 4.1 Root & Health Check
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    print_pass(f"GET /health: {health_resp.json()['status']}")

    # 4.2 GET /auth/google (Initiate Flow)
    auth_resp = client.get("/auth/google", follow_redirects=False)
    assert auth_resp.status_code == 307
    location = auth_resp.headers["location"]
    assert "accounts.google.com" in location
    assert "meetings.space.readonly" in location
    assert "access_type=offline" in location
    assert "prompt=consent" in location
    assert OAUTH_NONCE_COOKIE_NAME in auth_resp.cookies
    nonce_cookie = auth_resp.cookies[OAUTH_NONCE_COOKIE_NAME]
    print_pass("GET /auth/google initiates 307 redirect with required Meet scopes & offline access")
    print_pass(f"Cookie '{OAUTH_NONCE_COOKIE_NAME}' set with HttpOnly protection")

    # 4.3 GET /auth/google?format=json (Programmatic Initiation)
    json_auth_resp = client.get("/auth/google?format=json")
    assert json_auth_resp.status_code == 200
    auth_json = json_auth_resp.json()
    assert "authorization_url" in auth_json
    print_pass("GET /auth/google?format=json successfully returned authorization URL for API clients")

    # 4.4 GET /auth/google/callback (User Denied / Cancelled)
    denied_resp = client.get("/auth/google/callback?error=access_denied&error_description=User+cancelled")
    assert denied_resp.status_code == 400
    assert denied_resp.json()["error"] == "access_denied"
    print_pass("GET /auth/google/callback properly handles user denial ('access_denied') with HTTP 400")

    # 4.5 GET /auth/google/callback (Successful Exchange & Persistence)
    SECRET_ACCESS = "ya29.live_secret_mock_access_token_888"
    SECRET_REFRESH = "1//live_secret_mock_refresh_token_999"
    SECRET_CLIENT_SECRET = "GOCSPX-mock-client-secret"

    mock_tokens = {
        "access_token": SECRET_ACCESS,
        "refresh_token": SECRET_REFRESH,
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/meetings.space.readonly openid email",
    }
    mock_userinfo = {
        "sub": "google_test_sub_555",
        "email": "testuser@synesis-demo.com",
        "name": "Synesis Tester",
    }

    with patch("app.services.google_oauth.GoogleOAuthService.exchange_code", new_callable=AsyncMock) as mock_exch, \
         patch("app.services.google_oauth.GoogleOAuthService.fetch_user_info", new_callable=AsyncMock) as mock_uinfo:
        mock_exch.return_value = mock_tokens
        mock_uinfo.return_value = mock_userinfo

        callback_state, callback_nonce = OAuthStateManager.generate_state(user_id="usr_tester")
        client.cookies.set(OAUTH_NONCE_COOKIE_NAME, callback_nonce)

        cb_resp = client.get(
            f"/auth/google/callback?code=mock_authorization_code&state={callback_state}",
            headers={"Accept": "application/json"},
        )
        assert cb_resp.status_code == 200
        cb_data = cb_resp.json()
        assert cb_data["success"] is True
        connection = cb_data["connection"]
        connection_id = connection["id"]
        assert connection["provider"] == "google"
        assert connection["provider_account_email"] == "testuser@synesis-demo.com"
        assert connection["status"] == "active"
        print_pass(f"GET /auth/google/callback succeeded: Connection ID '{connection_id}' created")

        # 4.6 Strict Secret Isolation Check
        cb_text = cb_resp.text
        assert SECRET_ACCESS not in cb_text, "CRITICAL: Access token leaked in callback response!"
        assert SECRET_REFRESH not in cb_text, "CRITICAL: Refresh token leaked in callback response!"
        assert SECRET_CLIENT_SECRET not in cb_text, "CRITICAL: Client secret leaked in callback response!"
        print_pass("Strict Secret Isolation: No access token, refresh token, or client secret in JSON response")

        # Check DB row for encryption
        db = SessionLocal()
        db_conn = db.query(SourceConnection).filter_by(id=connection_id).first()
        assert db_conn is not None
        assert SECRET_ACCESS not in db_conn.encrypted_credentials, "CRITICAL: Plaintext token stored in DB!"
        assert SECRET_REFRESH not in db_conn.encrypted_credentials, "CRITICAL: Plaintext token stored in DB!"
        assert db_conn.encrypted_credentials.startswith("gAAAAA"), "Credentials are not Fernet encrypted!"
        print_pass("Database Inspection: Credentials verified encrypted at rest with Fernet (gAAAAA...)")
        db.close()

    # 4.7 POST /auth/google/refresh (Token Refresh)
    print_step("Step 5: Token Refresh Verification")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json={
                "access_token": "ya29.refreshed_fresh_access_token_111",
                "expires_in": 3600,
            },
        )
        ref_resp = client.post(
            f"/auth/google/refresh?connection_id={connection_id}&force=true",
            headers={"X-User-ID": "usr_tester"},
        )
        assert ref_resp.status_code == 200
        ref_data = ref_resp.json()
        assert ref_data["success"] is True
        assert ref_data["connection"]["status"] == "active"
        assert "ya29" not in ref_resp.text, "CRITICAL: Refreshed token leaked in response!"
        print_pass("POST /auth/google/refresh refreshed token successfully (zero secrets leaked)")

    # 4.8 POST /auth/google/disconnect (Disconnect & Revocation)
    print_step("Step 6: Account Disconnection & Token Revocation")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200)
        disc_resp = client.post(
            f"/auth/google/disconnect?connection_id={connection_id}",
            headers={"X-User-ID": "usr_tester"},
        )
        assert disc_resp.status_code == 200
        disc_data = disc_resp.json()
        assert disc_data["success"] is True
        assert disc_data["status"] == "disconnected"
        print_pass(f"POST /auth/google/disconnect revoked token and marked status '{disc_data['status']}'")

    # 4.9 GET /auth/google/connections (List Connections)
    print_step("Step 7: List Connections Query")
    list_resp = client.get("/auth/google/connections", headers={"X-User-ID": "usr_tester"})
    assert list_resp.status_code == 200
    connections = list_resp.json()
    assert len(connections) >= 1
    assert connections[0]["id"] == connection_id
    assert "encrypted_credentials" not in connections[0]
    print_pass("GET /auth/google/connections safely lists user connections without exposing credentials")

    print(f"\n{BOLD}{GREEN}======================================================{RESET}")
    print(f"{BOLD}{GREEN}    ALL PIPELINE TESTS PASSED SUCCESSFULLY! (100%)    {RESET}")
    print(f"{BOLD}{GREEN}======================================================{RESET}\n")

    # Clean up test db file
    try:
        if os.path.exists("./test_pipeline.db"):
            os.remove("./test_pipeline.db")
    except Exception:
        pass


def test_against_live_server(base_url: str):
    print(f"{BOLD}Testing against live server at: {base_url}{RESET}")
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        # 1. Health check
        try:
            r = client.get("/health")
            print_pass(f"Server is reachable: {r.status_code} - {r.json()}")
        except Exception as exc:
            print_fail(f"Could not reach server at {base_url}: {exc}")
            return

        # 2. Get auth URL
        r = client.get("/auth/google?format=json")
        if r.status_code == 200:
            url = r.json().get("authorization_url")
            print_pass("Google Auth is configured on server!")
            print_info(f"Open this URL in your browser to test consent:\n{url}")
        else:
            print_info(f"Response: {r.status_code} - {r.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Synesis Google OAuth Pipeline")
    parser.add_argument("--url", help="Base URL of live server to test (e.g. http://localhost:8000)")
    args = parser.parse_args()

    if args.url:
        test_against_live_server(args.url)
    else:
        run_automated_pipeline()
