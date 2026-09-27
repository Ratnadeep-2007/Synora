import base64
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, Optional, Tuple
import urllib.parse

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings, settings as default_settings
from app.core.exceptions import (
    ConfigurationError,
    CredentialsExpiredError,
    GoogleOAuthError,
    InvalidOAuthStateException,
    OAuthAccessDeniedError,
)
from app.core.security import OAuthStateManager
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.services.encryption_service import EncryptionService

logger = logging.getLogger(__name__)


class GoogleOAuthService:
    """
    Encapsulates all Google OAuth 2.0 operations for Synesis.
    Prevents OAuth details from leaking into unrelated business modules.
    """

    GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
    GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        encryption_service: Optional[EncryptionService] = None,
    ):
        self.settings = settings or default_settings
        self.encryption = encryption_service or EncryptionService(self.settings.ENCRYPTION_KEY)

    def is_configured(self) -> bool:
        """Check if required Google OAuth credentials are set."""
        return self.settings.is_google_oauth_configured

    def _ensure_configured(self) -> None:
        """Validate that Google OAuth credentials are fully provided."""
        if not self.settings.GOOGLE_CLIENT_ID or not self.settings.GOOGLE_CLIENT_SECRET:
            raise ConfigurationError(
                "Google OAuth credentials are not configured. "
                "Ensure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set in environment or .env."
            )
        if not self.settings.GOOGLE_REDIRECT_URI:
            raise ConfigurationError(
                "GOOGLE_REDIRECT_URI is not set. Please specify the authorized redirect URI."
            )

    def get_authorization_url(
        self,
        user_id: str,
        return_to: Optional[str] = None,
        extra_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]:
        """
        Generate the Google OAuth consent URL and CSRF state token.
        
        Returns:
            Tuple of (authorization_url, state_nonce)
        """
        self._ensure_configured()

        state, nonce = OAuthStateManager.generate_state(
            user_id=user_id,
            return_to=return_to,
            extra=extra_state,
        )

        params = {
            "client_id": self.settings.GOOGLE_CLIENT_ID,
            "redirect_uri": self.settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(self.settings.GOOGLE_OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # Ensures refresh_token is always returned
            "include_granted_scopes": "true",
            "state": state,
        }

        url = f"{self.GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return url, nonce

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """
        Exchange an OAuth authorization code for access and refresh tokens with Google.
        """
        self._ensure_configured()

        data = {
            "code": code,
            "client_id": self.settings.GOOGLE_CLIENT_ID,
            "client_secret": self.settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": self.settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    self.GOOGLE_TOKEN_URL,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.RequestError as exc:
                logger.error(f"Network error during Google token exchange: {exc}")
                raise GoogleOAuthError(
                    f"Unable to reach Google OAuth service: {exc}",
                    status_code=502,
                ) from exc

        if response.status_code != 200:
            error_data = {}
            try:
                error_data = response.json()
            except Exception:
                pass
            err_code = error_data.get("error", "unknown_error")
            err_desc = error_data.get("error_description", response.text)
            logger.error(f"Google token exchange failed ({response.status_code}): {err_code} - {err_desc}")
            raise GoogleOAuthError(
                f"Failed to exchange authorization code: {err_desc}",
                error_code=err_code,
                status_code=response.status_code,
            )

        return response.json()

    async def fetch_user_info(
        self,
        access_token: str,
        id_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve Google user profile details (sub/id, email, etc.).
        Tries parsing id_token payload first, falls back to Google userinfo endpoint.
        """
        # Attempt to decode id_token JWT without extra network request
        if id_token:
            try:
                parts = id_token.split(".")
                if len(parts) >= 2:
                    padding = 4 - (len(parts[1]) % 4)
                    b64 = parts[1] + ("=" * padding if padding != 4 else "")
                    payload = json.loads(base64.urlsafe_b64decode(b64.encode("utf-8")).decode("utf-8"))
                    if payload.get("sub"):
                        return payload
            except Exception as exc:
                logger.warning(f"Could not parse id_token payload: {exc}. Falling back to userinfo endpoint.")

        # Fallback to userinfo API endpoint
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    self.GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code == 200:
                    return resp.json()
            except Exception as exc:
                logger.warning(f"Failed to fetch userinfo from Google: {exc}")

        return {}

    async def handle_callback(
        self,
        code: Optional[str],
        state: Optional[str],
        error: Optional[str] = None,
        error_description: Optional[str] = None,
        cookie_nonce: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Tuple[SourceConnection, Optional[str]]:
        """
        Validate OAuth callback response, exchange code for tokens, and persist encrypted credentials.
        
        Returns:
            Tuple of (SourceConnection, return_to_url)
        """
        # 1. Handle user-denied authorization or Google errors
        if error:
            logger.warning(f"OAuth authorization error received: {error} - {error_description}")
            if error in ("access_denied", "consent_required", "interaction_required"):
                raise OAuthAccessDeniedError(
                    f"Authorization was denied or cancelled: {error_description or error}"
                )
            raise GoogleOAuthError(
                f"OAuth authorization failed: {error_description or error}",
                error_code=error,
            )

        if not code:
            raise GoogleOAuthError("Missing authorization code from Google OAuth callback.")

        # 2. Validate CSRF state token and cookie nonce
        state_payload = OAuthStateManager.verify_state(state, cookie_nonce=cookie_nonce)
        user_id = state_payload.get("user_id")
        return_to = state_payload.get("return_to")

        if not user_id:
            raise InvalidOAuthStateException("State payload is missing required user_id.")

        # 3. Exchange authorization code for tokens
        token_data = await self.exchange_code(code)

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        scope = token_data.get("scope")
        token_type = token_data.get("token_type", "Bearer")
        id_token = token_data.get("id_token")

        if not access_token:
            raise GoogleOAuthError("Google token endpoint did not return an access token.")

        # 4. Fetch user details from Google (sub, email)
        user_info = await self.fetch_user_info(access_token, id_token)
        provider_account_id = user_info.get("sub") or user_info.get("id") or "google_account"
        provider_account_email = user_info.get("email")

        # Calculate expiration timestamp
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # 5. Persist credentials securely
        if db is None:
            raise ConfigurationError("Database session must be provided to handle_callback.")

        # Ensure user exists in database
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            user = User(
                id=user_id,
                email=provider_account_email or f"{user_id}@synesis.internal",
                name=user_info.get("name"),
            )
            db.add(user)
            db.flush()

        # Find existing connection for this user & account
        connection = (
            db.query(SourceConnection)
            .filter(
                SourceConnection.user_id == user_id,
                SourceConnection.provider == "google",
                SourceConnection.provider_account_id == provider_account_id,
            )
            .first()
        )

        existing_creds = {}
        if connection:
            try:
                existing_creds = self.encryption.decrypt_dict(connection.encrypted_credentials)
            except Exception:
                pass

        # If Google didn't return a new refresh_token, preserve existing one
        effective_refresh_token = refresh_token or existing_creds.get("refresh_token")

        credentials_payload = {
            "access_token": access_token,
            "refresh_token": effective_refresh_token,
            "token_type": token_type,
            "scope": scope,
            "id_token": id_token,
            "obtained_at": int(datetime.now(timezone.utc).timestamp()),
        }

        encrypted_creds = self.encryption.encrypt_dict(credentials_payload)

        if connection:
            connection.status = ConnectionStatus.ACTIVE.value
            connection.encrypted_credentials = encrypted_creds
            connection.provider_account_email = provider_account_email or connection.provider_account_email
            connection.scopes = scope or connection.scopes
            connection.expires_at = expires_at
            connection.updated_at = datetime.now(timezone.utc)
        else:
            connection = SourceConnection(
                user_id=user_id,
                provider="google",
                provider_account_id=provider_account_id,
                provider_account_email=provider_account_email,
                status=ConnectionStatus.ACTIVE.value,
                encrypted_credentials=encrypted_creds,
                scopes=scope,
                expires_at=expires_at,
            )
            db.add(connection)

        db.commit()
        db.refresh(connection)

        return connection, return_to

    async def refresh_credentials(
        self,
        connection: SourceConnection,
        db: Session,
        force: bool = False,
    ) -> SourceConnection:
        """
        Refresh an access token using the stored refresh token.
        
        Args:
            connection: The SourceConnection to refresh.
            db: Database session.
            force: If True, refresh even if token is not expired yet.
        """
        self._ensure_configured()

        # Decrypt current credentials
        try:
            creds = self.encryption.decrypt_dict(connection.encrypted_credentials)
        except Exception as exc:
            connection.status = ConnectionStatus.ERROR.value
            db.commit()
            raise CredentialsExpiredError(f"Corrupted or invalid encrypted credentials: {exc}") from exc

        refresh_token = creds.get("refresh_token")
        if not refresh_token:
            connection.status = ConnectionStatus.EXPIRED.value
            db.commit()
            raise CredentialsExpiredError(
                "No refresh token available. The user must re-authenticate with Google."
            )

        # Check if already fresh (has more than 5 minutes remaining)
        now_utc = datetime.now(timezone.utc)
        if not force and connection.expires_at:
            # Handle tz-aware and tz-naive safely
            expires_at = connection.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > now_utc + timedelta(minutes=5):
                return connection

        # Request new access token from Google
        data = {
            "client_id": self.settings.GOOGLE_CLIENT_ID,
            "client_secret": self.settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    self.GOOGLE_TOKEN_URL,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.RequestError as exc:
                raise GoogleOAuthError(f"Network error refreshing Google token: {exc}", status_code=502) from exc

        if response.status_code != 200:
            error_data = {}
            try:
                error_data = response.json()
            except Exception:
                pass
            err_code = error_data.get("error", "unknown_error")
            err_desc = error_data.get("error_description", response.text)

            # If token was revoked at Google, update status to revoked/expired
            if err_code in ("invalid_grant", "unauthorized_client"):
                connection.status = ConnectionStatus.REVOKED.value
                db.commit()
                raise CredentialsExpiredError(
                    f"Google credentials have expired or been revoked ({err_code}): {err_desc}"
                )

            raise GoogleOAuthError(
                f"Failed to refresh token: {err_desc}",
                error_code=err_code,
                status_code=response.status_code,
            )

        refreshed_data = response.json()
        new_access_token = refreshed_data.get("access_token")
        expires_in = refreshed_data.get("expires_in", 3600)
        new_refresh_token = refreshed_data.get("refresh_token") or refresh_token

        # Update stored credentials
        creds["access_token"] = new_access_token
        creds["refresh_token"] = new_refresh_token
        creds["refreshed_at"] = int(datetime.now(timezone.utc).timestamp())

        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        connection.encrypted_credentials = self.encryption.encrypt_dict(creds)
        connection.expires_at = new_expires_at
        connection.status = ConnectionStatus.ACTIVE.value
        connection.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(connection)
        return connection

    async def revoke_connection(
        self,
        connection: SourceConnection,
        db: Session,
    ) -> SourceConnection:
        """
        Revoke credentials with Google and mark connection as disconnected/revoked.
        """
        try:
            creds = self.encryption.decrypt_dict(connection.encrypted_credentials)
            token_to_revoke = creds.get("refresh_token") or creds.get("access_token")
            if token_to_revoke:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        self.GOOGLE_REVOKE_URL,
                        params={"token": token_to_revoke},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
        except Exception as exc:
            logger.warning(f"Revocation request to Google returned error (ignoring to finish disconnect): {exc}")

        connection.status = ConnectionStatus.DISCONNECTED.value
        connection.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(connection)
        return connection

    def get_decrypted_credentials(self, connection: SourceConnection) -> Dict[str, Any]:
        """
        Retrieve decrypted credentials for backend-internal usage only (e.g. Google Meet REST API).
        NEVER expose the result of this method to HTTP responses or frontend clients.
        """
        return self.encryption.decrypt_dict(connection.encrypted_credentials)
