from unittest.mock import AsyncMock, patch
import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import OAUTH_NONCE_COOKIE_NAME, OAuthStateManager
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.schemas.source_connection import SourceConnectionRead
from app.services.encryption_service import EncryptionService


def test_schema_excludes_sensitive_fields():
    """Verify that the public DTO schema contains no secret or credential fields."""
    fields = SourceConnectionRead.model_fields.keys()

    assert "encrypted_credentials" not in fields
    assert "access_token" not in fields
    assert "refresh_token" not in fields
    assert "client_secret" not in fields
    assert "id_token" not in fields


def test_callback_never_exposes_tokens_or_secrets(
    client: TestClient,
    test_user: User,
    db_session: Session,
):
    SECRET_ACCESS_TOKEN = "SUPER_SECRET_ACCESS_TOKEN_DO_NOT_LEAK"
    SECRET_REFRESH_TOKEN = "SUPER_SECRET_REFRESH_TOKEN_DO_NOT_LEAK"
    SECRET_CLIENT_SECRET = "GOCSPX-mock-client-secret-value"

    state, nonce = OAuthStateManager.generate_state(user_id=test_user.id)

    mock_tokens = {
        "access_token": SECRET_ACCESS_TOKEN,
        "refresh_token": SECRET_REFRESH_TOKEN,
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/meetings.space.readonly",
    }
    mock_userinfo = {"sub": "google_123", "email": "test@domain.com"}

    with patch("app.services.google_oauth.GoogleOAuthService.exchange_code", new_callable=AsyncMock) as mock_exchange, \
         patch("app.services.google_oauth.GoogleOAuthService.fetch_user_info", new_callable=AsyncMock) as mock_user_fetch:
        mock_exchange.return_value = mock_tokens
        mock_user_fetch.return_value = mock_userinfo

        client.cookies.set(OAUTH_NONCE_COOKIE_NAME, nonce)
        response = client.get(
            f"/auth/google/callback?code=mock_code&state={state}",
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        raw_response_text = response.text

        # Strict security assertions: NO SECRETS IN RESPONSE
        assert SECRET_ACCESS_TOKEN not in raw_response_text
        assert SECRET_REFRESH_TOKEN not in raw_response_text
        assert SECRET_CLIENT_SECRET not in raw_response_text

        # Verify DB stores it encrypted
        conn = db_session.query(SourceConnection).filter_by(user_id=test_user.id).first()
        assert conn is not None
        assert SECRET_ACCESS_TOKEN not in conn.encrypted_credentials
        assert SECRET_REFRESH_TOKEN not in conn.encrypted_credentials


def test_refresh_never_exposes_tokens_or_secrets(
    client: TestClient,
    test_user: User,
    db_session: Session,
    encryption_service: EncryptionService,
):
    SECRET_ACCESS_TOKEN = "SUPER_NEW_SECRET_ACCESS_TOKEN"
    SECRET_REFRESH_TOKEN = "SUPER_SECRET_REFRESH_TOKEN"
    SECRET_CLIENT_SECRET = "GOCSPX-mock-client-secret-value"

    creds = {
        "access_token": "old_token",
        "refresh_token": SECRET_REFRESH_TOKEN,
    }
    conn = SourceConnection(
        user_id=test_user.id,
        provider="google",
        provider_account_id="sec_test_sub",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict(creds),
    )
    db_session.add(conn)
    db_session.commit()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json={
                "access_token": SECRET_ACCESS_TOKEN,
                "expires_in": 3600,
            },
        )

        response = client.post(
            f"/auth/google/refresh?connection_id={conn.id}&force=true",
            headers={"X-User-ID": test_user.id},
        )

        assert response.status_code == 200
        raw_text = response.text

        # Strict security assertions
        assert SECRET_ACCESS_TOKEN not in raw_text
        assert SECRET_REFRESH_TOKEN not in raw_text
        assert SECRET_CLIENT_SECRET not in raw_text
