from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    ConfigurationError,
    CredentialsExpiredError,
    GoogleOAuthError,
    OAuthAccessDeniedError,
)
from app.core.security import OAuthStateManager
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.services.encryption_service import EncryptionService
from app.services.google_oauth import GoogleOAuthService


@pytest.mark.asyncio
async def test_get_authorization_url(google_service: GoogleOAuthService):
    user_id = "usr_test_user_001"
    url, nonce = google_service.get_authorization_url(user_id=user_id)

    assert "accounts.google.com/o/oauth2/v2/auth" in url
    assert "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fmeetings.space.readonly" in url or "meetings.space.readonly" in url
    assert "meetings.conference.readonly" not in url
    assert "conference.readonly" not in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "mock-google-client-id" in url
    assert nonce is not None


@pytest.mark.asyncio
async def test_authorization_scopes_strictly_valid(google_service: GoogleOAuthService):
    import urllib.parse
    url, _ = google_service.get_authorization_url(user_id="usr_scope_check")
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    assert "scope" in query
    requested_scopes = set(query["scope"][0].split())

    expected_scopes = {
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/meetings.space.readonly",
    }
    assert requested_scopes == expected_scopes
    assert "https://www.googleapis.com/auth/meetings.conference.readonly" not in requested_scopes
    assert "meetings.conference.readonly" not in requested_scopes
    # Prohibited replacement scopes per task #5
    assert "https://www.googleapis.com/auth/meetings.space.settings" not in requested_scopes
    assert "https://www.googleapis.com/auth/meetings.space.created" not in requested_scopes
    assert "https://www.googleapis.com/auth/drive.readonly" not in requested_scopes
    assert "https://www.googleapis.com/auth/drive.meet.readonly" not in requested_scopes


@pytest.mark.asyncio
async def test_get_authorization_url_unconfigured():
    bad_settings = Settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
    svc = GoogleOAuthService(settings=bad_settings)

    with pytest.raises(ConfigurationError):
        svc.get_authorization_url(user_id="usr_test")


@pytest.mark.asyncio
async def test_exchange_code_success(google_service: GoogleOAuthService):
    mock_token_response = {
        "access_token": "mock_access_token_123",
        "refresh_token": "mock_refresh_token_456",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/meetings.space.readonly",
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200, json=mock_token_response)

        tokens = await google_service.exchange_code("mock_auth_code_789")
        assert tokens["access_token"] == "mock_access_token_123"
        assert tokens["refresh_token"] == "mock_refresh_token_456"


@pytest.mark.asyncio
async def test_exchange_code_failure(google_service: GoogleOAuthService):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "Code has expired or already used.",
            },
        )

        with pytest.raises(GoogleOAuthError) as exc_info:
            await google_service.exchange_code("expired_code")
        assert "invalid_grant" in str(exc_info.value.error_code)


@pytest.mark.asyncio
async def test_handle_callback_success(
    google_service: GoogleOAuthService,
    db_session: Session,
    test_user: User,
):
    state, nonce = OAuthStateManager.generate_state(
        user_id=test_user.id,
        return_to="http://localhost:3000/app",
    )

    mock_tokens = {
        "access_token": "mock_fresh_access_token",
        "refresh_token": "mock_fresh_refresh_token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "https://www.googleapis.com/auth/meetings.space.readonly openid email",
    }
    mock_userinfo = {
        "sub": "google_sub_987654321",
        "email": "user@google-domain.com",
        "name": "Google User",
    }

    with patch.object(google_service, "exchange_code", new_callable=AsyncMock) as mock_exchange, \
         patch.object(google_service, "fetch_user_info", new_callable=AsyncMock) as mock_user_fetch:
        mock_exchange.return_value = mock_tokens
        mock_user_fetch.return_value = mock_userinfo

        connection, return_to = await google_service.handle_callback(
            code="valid_google_code",
            state=state,
            cookie_nonce=nonce,
            db=db_session,
        )

        assert connection.id is not None
        assert connection.user_id == test_user.id
        assert connection.provider == "google"
        assert connection.provider_account_id == "google_sub_987654321"
        assert connection.provider_account_email == "user@google-domain.com"
        assert connection.status == ConnectionStatus.ACTIVE.value
        assert return_to == "http://localhost:3000/app"

        # Verify credentials can be decrypted internally by backend
        decrypted = google_service.get_decrypted_credentials(connection)
        assert decrypted["access_token"] == "mock_fresh_access_token"
        assert decrypted["refresh_token"] == "mock_fresh_refresh_token"


@pytest.mark.asyncio
async def test_handle_callback_denied(google_service: GoogleOAuthService, db_session: Session):
    with pytest.raises(OAuthAccessDeniedError, match="denied or cancelled"):
        await google_service.handle_callback(
            code=None,
            state="any-state",
            error="access_denied",
            error_description="The user denied the request",
            db=db_session,
        )


@pytest.mark.asyncio
async def test_refresh_credentials_success(
    google_service: GoogleOAuthService,
    encryption_service: EncryptionService,
    db_session: Session,
    test_user: User,
):
    # Create existing connection with expired token
    initial_creds = {
        "access_token": "expired_access_token",
        "refresh_token": "valid_refresh_token_123",
        "token_type": "Bearer",
    }
    conn = SourceConnection(
        user_id=test_user.id,
        provider="google",
        provider_account_id="google_sub_123",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict(initial_creds),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(conn)
    db_session.commit()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            200,
            json={
                "access_token": "brand_new_access_token",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

        refreshed = await google_service.refresh_credentials(conn, db=db_session, force=True)
        assert refreshed.status == ConnectionStatus.ACTIVE.value

        # Decrypt to ensure updated token is stored
        decrypted = google_service.get_decrypted_credentials(refreshed)
        assert decrypted["access_token"] == "brand_new_access_token"
        assert decrypted["refresh_token"] == "valid_refresh_token_123"


@pytest.mark.asyncio
async def test_refresh_credentials_revoked_at_google(
    google_service: GoogleOAuthService,
    encryption_service: EncryptionService,
    db_session: Session,
    test_user: User,
):
    conn = SourceConnection(
        user_id=test_user.id,
        provider="google",
        provider_account_id="google_sub_123",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict({"refresh_token": "revoked_token"}),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(conn)
    db_session.commit()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            },
        )

        with pytest.raises(CredentialsExpiredError):
            await google_service.refresh_credentials(conn, db=db_session, force=True)

        assert conn.status == ConnectionStatus.REVOKED.value


@pytest.mark.asyncio
async def test_revoke_connection(
    google_service: GoogleOAuthService,
    encryption_service: EncryptionService,
    db_session: Session,
    test_user: User,
):
    conn = SourceConnection(
        user_id=test_user.id,
        provider="google",
        provider_account_id="google_sub_123",
        status=ConnectionStatus.ACTIVE.value,
        encrypted_credentials=encryption_service.encrypt_dict({"refresh_token": "token_to_revoke"}),
    )
    db_session.add(conn)
    db_session.commit()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200)

        revoked = await google_service.revoke_connection(conn, db=db_session)
        assert revoked.status == ConnectionStatus.DISCONNECTED.value
