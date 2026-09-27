from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import OAUTH_NONCE_COOKIE_NAME, OAuthStateManager
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.services.encryption_service import EncryptionService


def test_initiate_oauth_flow_redirects(client: TestClient):
    response = client.get("/auth/google", follow_redirects=False)

    assert response.status_code == 307
    location = response.headers.get("location")
    assert location is not None
    assert "accounts.google.com/o/oauth2/v2/auth" in location
    assert "mock-google-client-id" in location
    assert "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fmeetings.space.readonly" in location or "meetings.space.readonly" in location
    assert "meetings.conference.readonly" not in location
    assert "conference.readonly" not in location
    assert "access_type=offline" in location
    assert "prompt=consent" in location

    # Check CSRF nonce cookie
    assert OAUTH_NONCE_COOKIE_NAME in response.cookies
    nonce_val = response.cookies[OAUTH_NONCE_COOKIE_NAME]
    assert len(nonce_val) > 20


def test_initiate_oauth_flow_json(client: TestClient):
    response = client.get("/auth/google?format=json")

    assert response.status_code == 200
    data = response.json()
    assert "authorization_url" in data
    auth_url = data["authorization_url"]
    assert "accounts.google.com" in auth_url
    assert "meetings.space.readonly" in auth_url
    assert "meetings.conference.readonly" not in auth_url
    assert "conference.readonly" not in auth_url
    assert OAUTH_NONCE_COOKIE_NAME in response.cookies


def test_callback_success_json(client: TestClient, test_user: User):
    state, nonce = OAuthStateManager.generate_state(user_id=test_user.id)

    mock_tokens = {
        "access_token": "mock_access_token_abc",
        "refresh_token": "mock_refresh_token_xyz",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/meetings.space.readonly",
        "id_token": "header.payload.signature",
    }
    mock_userinfo = {
        "sub": "google_account_12345",
        "email": "user@gmail.com",
        "name": "Jane Doe",
    }

    with patch("app.services.google_oauth.GoogleOAuthService.exchange_code", new_callable=AsyncMock) as mock_exchange, \
         patch("app.services.google_oauth.GoogleOAuthService.fetch_user_info", new_callable=AsyncMock) as mock_user_fetch:
        mock_exchange.return_value = mock_tokens
        mock_user_fetch.return_value = mock_userinfo

        # Pass nonce in cookie
        client.cookies.set(OAUTH_NONCE_COOKIE_NAME, nonce)

        response = client.get(
            f"/auth/google/callback?code=mock_auth_code_123&state={state}",
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        connection = data["connection"]
        assert connection["user_id"] == test_user.id
        assert connection["provider"] == "google"
        assert connection["provider_account_id"] == "google_account_12345"
        assert connection["provider_account_email"] == "user@gmail.com"
        assert connection["status"] == "active"


def test_callback_success_html(client: TestClient, test_user: User):
    state, nonce = OAuthStateManager.generate_state(user_id=test_user.id)

    with patch("app.services.google_oauth.GoogleOAuthService.exchange_code", new_callable=AsyncMock) as mock_exchange, \
         patch("app.services.google_oauth.GoogleOAuthService.fetch_user_info", new_callable=AsyncMock) as mock_user_fetch:
        mock_exchange.return_value = {
            "access_token": "token",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }
        mock_user_fetch.return_value = {"sub": "123", "email": "test@gmail.com"}

        client.cookies.set(OAUTH_NONCE_COOKIE_NAME, nonce)
        response = client.get(
            f"/auth/google/callback?code=code_123&state={state}",
            headers={"Accept": "text/html"},
        )

        assert response.status_code == 200
        assert "Google Meet Connected" in response.text
        assert "Google Account Linked" in response.text


def test_callback_with_return_to_redirect(client: TestClient, test_user: User):
    return_target = "http://localhost:3000/dashboard/integrations"
    state, nonce = OAuthStateManager.generate_state(
        user_id=test_user.id,
        return_to=return_target,
    )

    with patch("app.services.google_oauth.GoogleOAuthService.exchange_code", new_callable=AsyncMock) as mock_exchange, \
         patch("app.services.google_oauth.GoogleOAuthService.fetch_user_info", new_callable=AsyncMock) as mock_user_fetch:
        mock_exchange.return_value = {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_in": 3600,
        }
        mock_user_fetch.return_value = {"sub": "456", "email": "user@google.com"}

        client.cookies.set(OAUTH_NONCE_COOKIE_NAME, nonce)
        response = client.get(
            f"/auth/google/callback?code=code_123&state={state}",
            follow_redirects=False,
        )

        assert response.status_code == 307
        loc = response.headers.get("location")
        assert loc.startswith(return_target)
        assert "status=success" in loc
        assert "provider=google" in loc


def test_callback_denied_authorization(client: TestClient):
    response = client.get(
        "/auth/google/callback?error=access_denied&error_description=User+cancelled+request"
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "access_denied"
    assert "denied or cancelled" in data["message"].lower()


def test_callback_invalid_state(client: TestClient):
    response = client.get(
        "/auth/google/callback?code=some_code&state=tampered_or_invalid_state"
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "invalid_state"


def test_callback_missing_code_and_state(client: TestClient):
    response = client.get("/auth/google/callback")
    assert response.status_code == 400


def test_refresh_endpoint(
    client: TestClient,
    db_session: Session,
    test_user: User,
    encryption_service: EncryptionService,
):
    # Seed connection
    creds = {"access_token": "old_token", "refresh_token": "valid_refresh"}
    conn = SourceConnection(
        user_id=test_user.id,
        provider="google",
        provider_account_id="google_sub_999",
        provider_account_email="refresh_test@example.com",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict(creds),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(conn)
    db_session.commit()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json={
                "access_token": "brand_new_refreshed_token",
                "expires_in": 3600,
            },
        )

        response = client.post(
            f"/auth/google/refresh?connection_id={conn.id}&force=true",
            headers={"X-User-ID": test_user.id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["connection"]["id"] == conn.id
        assert data["connection"]["status"] == "active"


def test_disconnect_endpoint(
    client: TestClient,
    db_session: Session,
    test_user: User,
    encryption_service: EncryptionService,
):
    conn = SourceConnection(
        user_id=test_user.id,
        provider="google",
        provider_account_id="google_sub_888",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict({"refresh_token": "tok"}),
    )
    db_session.add(conn)
    db_session.commit()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200)

        response = client.post(
            f"/auth/google/disconnect?connection_id={conn.id}",
            headers={"X-User-ID": test_user.id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["status"] == "disconnected"


def test_list_connections(
    client: TestClient,
    db_session: Session,
    test_user: User,
    encryption_service: EncryptionService,
):
    conn = SourceConnection(
        user_id=test_user.id,
        provider="google",
        provider_account_id="google_sub_777",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict({"access_token": "xyz"}),
    )
    db_session.add(conn)
    db_session.commit()

    response = client.get(
        "/auth/google/connections",
        headers={"X-User-ID": test_user.id},
    )

    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 1
    assert items[0]["provider"] == "google"
    assert items[0]["user_id"] == test_user.id
