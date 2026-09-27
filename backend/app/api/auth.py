from datetime import datetime, timezone
import logging
from typing import List, Optional

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_db,
    get_google_oauth_service,
)
from app.core.config import settings
from app.core.exceptions import (
    ConfigurationError,
    CredentialsExpiredError,
    GoogleOAuthError,
    InvalidOAuthStateException,
    OAuthAccessDeniedError,
)
from app.core.security import OAUTH_NONCE_COOKIE_NAME
from app.models.source_connection import ConnectionStatus, SourceConnection
from app.models.user import User
from app.schemas.auth import (
    OAuthCallbackResponse,
    OAuthDisconnectResponse,
    OAuthInitResponse,
    OAuthRefreshResponse,
)
from app.schemas.source_connection import SourceConnectionRead
from app.services.google_oauth import GoogleOAuthService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["OAuth & Connections"])


@router.get(
    "/google",
    summary="Initiate Google OAuth Flow",
    description="Generates CSRF-protected state, sets verification cookie, and redirects user to Google OAuth consent screen.",
    responses={
        307: {"description": "Redirects to Google authorization page"},
        200: {"model": OAuthInitResponse, "description": "Returns authorization URL for programmatic clients"},
        500: {"description": "OAuth configuration is missing or invalid"},
    },
)
async def initiate_google_oauth(
    request: Request,
    response: Response,
    user_id: Optional[str] = Query(None, description="Optional Synesis User ID"),
    return_to: Optional[str] = Query(None, description="Optional URL to redirect after authorization completes"),
    format: Optional[str] = Query(None, description="Set to 'json' to get authorization URL without 307 redirect"),
    google_service: GoogleOAuthService = Depends(get_google_oauth_service),
    db: Session = Depends(get_db),
):
    """
    Step 1 of Google OAuth: Initiates OAuth authorization flow.
    Generates a CSRF-safe state token containing user_id and expiration, sets a secure nonce cookie,
    and redirects the user's browser to Google's consent screen.
    The user record is resolved at callback time, so no account needs to exist yet.
    """
    try:
        # Determine target Synesis user (created or linked at callback time)
        from app.models.user import User as UserModel
        target_user_id = user_id
        if not target_user_id:
            x_user_id = request.headers.get("X-User-ID")
            if x_user_id:
                existing = db.query(UserModel).filter(UserModel.id == x_user_id).first()
                if existing:
                    target_user_id = existing.id
        if not target_user_id:
            import uuid as _uuid
            target_user_id = f"usr_{_uuid.uuid4().hex[:12]}"

        logger.info(
            "google_oauth_started: user_id=%s return_to=%s",
            target_user_id,
            return_to,
        )

        # Generate Google authorization URL and cryptographic nonce
        auth_url, nonce = google_service.get_authorization_url(
            user_id=target_user_id,
            return_to=return_to,
        )

        # If JSON response requested
        accept_header = request.headers.get("accept", "")
        if format == "json" or ("application/json" in accept_header and "text/html" not in accept_header):
            json_resp = JSONResponse(
                content={"authorization_url": auth_url, "provider": "google"}
            )
            json_resp.set_cookie(
                key=OAUTH_NONCE_COOKIE_NAME,
                value=nonce,
                httponly=True,
                max_age=settings.OAUTH_STATE_EXPIRE_SECONDS,
                samesite=settings.COOKIE_SAMESITE,
                secure=settings.COOKIE_SECURE,
            )
            return json_resp

        # Default browser flow: 307 Temporary Redirect
        redirect_resp = RedirectResponse(url=auth_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        redirect_resp.set_cookie(
            key=OAUTH_NONCE_COOKIE_NAME,
            value=nonce,
            httponly=True,
            max_age=settings.OAUTH_STATE_EXPIRE_SECONDS,
            samesite=settings.COOKIE_SAMESITE,
            secure=settings.COOKIE_SECURE,
        )
        return redirect_resp

    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "configuration_error",
                "message": str(exc),
                "hint": "Check that GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are configured in .env",
            },
        )


@router.get(
    "/google/callback",
    summary="Google OAuth Callback",
    description="Validates state, exchanges authorization code, encrypts credentials, and associates connection with user.",
    responses={
        200: {"model": OAuthCallbackResponse, "description": "Connection established successfully"},
        307: {"description": "Redirects to return_to URL if configured"},
        400: {"description": "Invalid state, denied authorization, or exchange failure"},
    },
)
async def google_oauth_callback(
    request: Request,
    response: Response,
    code: Optional[str] = Query(None, description="Authorization code from Google"),
    state: Optional[str] = Query(None, description="CSRF state parameter"),
    error: Optional[str] = Query(None, description="OAuth error code (e.g. access_denied)"),
    error_description: Optional[str] = Query(None, description="Detailed error description"),
    synesis_oauth_nonce: Optional[str] = Cookie(None, alias=OAUTH_NONCE_COOKIE_NAME),
    google_service: GoogleOAuthService = Depends(get_google_oauth_service),
    db: Session = Depends(get_db),
):
    """
    Step 2 of Google OAuth: Validates state, exchanges code for credentials, persists them securely,
    and associates the connection with the authenticated Synesis user.
    """
    # Clear the CSRF nonce cookie on response
    def clear_nonce_cookie(resp: Response):
        resp.delete_cookie(
            key=OAUTH_NONCE_COOKIE_NAME,
            httponly=True,
            samesite=settings.COOKIE_SAMESITE,
            secure=settings.COOKIE_SECURE,
        )

    try:
        connection, return_to = await google_service.handle_callback(
            code=code,
            state=state,
            error=error,
            error_description=error_description,
            cookie_nonce=synesis_oauth_nonce,
            db=db,
        )

        safe_conn = SourceConnectionRead.model_validate(connection)
        logger.info(
            "google_oauth_completed: user_id=%s connection_id=%s provider_account=%s",
            connection.user_id,
            connection.id,
            connection.provider_account_email or connection.provider_account_id,
        )

        # If a return_to URL was embedded in state, redirect with status
        if return_to:
            delim = "&" if "?" in return_to else "?"
            redirect_target = f"{return_to}{delim}status=success&connection_id={connection.id}&provider=google"
            resp = RedirectResponse(url=redirect_target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
            clear_nonce_cookie(resp)
            return resp

        # Check if browser requested HTML
        accept_header = request.headers.get("accept", "")
        if "text/html" in accept_header:
            html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Synesis — Google Connection Established</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #F8FAFC;
      color: #0F172A;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      padding: 20px;
    }}
    .card {{
      background: #FFFFFF;
      border: 1px solid #E2E8F0;
      border-radius: 12px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
      padding: 32px;
      max-width: 520px;
      width: 100%;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      background: #DCFCE7;
      color: #166534;
      font-size: 13px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 9999px;
      margin-bottom: 16px;
    }}
    h1 {{
      font-size: 22px;
      margin: 0 0 8px 0;
      font-weight: 600;
    }}
    p {{
      color: #64748B;
      font-size: 14px;
      line-height: 1.5;
      margin: 0 0 24px 0;
    }}
    .details {{
      background: #F1F5F9;
      border-radius: 8px;
      padding: 16px;
      font-size: 13px;
      margin-bottom: 24px;
    }}
    .row {{
      display: flex;
      justify-content: space-between;
      padding: 6px 0;
      border-bottom: 1px solid #E2E8F0;
    }}
    .row:last-child {{
      border-bottom: none;
    }}
    .label {{
      color: #64748B;
      font-weight: 500;
    }}
    .val {{
      font-family: monospace;
      color: #0F172A;
      font-weight: 600;
    }}
    .note {{
      font-size: 12px;
      color: #94A3B8;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">● Google Meet Connected</div>
    <h1>Google Account Linked</h1>
    <p>Your Google account has been authorized for Synesis. Credentials have been encrypted and stored securely server-side.</p>
    <div class="details">
      <div class="row"><span class="label">Connection ID</span><span class="val">{safe_conn.id}</span></div>
      <div class="row"><span class="label">User ID</span><span class="val">{safe_conn.user_id}</span></div>
      <div class="row"><span class="label">Account</span><span class="val">{safe_conn.provider_account_email or safe_conn.provider_account_id}</span></div>
      <div class="row"><span class="label">Status</span><span class="val" style="color: #16A34A;">{safe_conn.status.upper()}</span></div>
    </div>
    <div class="note">You can safely close this window and return to your application.</div>
  </div>
</body>
</html>"""
            html_resp = HTMLResponse(content=html_content, status_code=status.HTTP_200_OK)
            clear_nonce_cookie(html_resp)
            return html_resp

        # Default JSON response
        json_resp = JSONResponse(
            content={
                "success": True,
                "message": "Google account connected successfully",
                "connection": safe_conn.model_dump(mode="json"),
            }
        )
        clear_nonce_cookie(json_resp)
        return json_resp

    except OAuthAccessDeniedError as exc:
        err_resp = JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "access_denied",
                "message": "Google OAuth authorization was denied or cancelled.",
                "detail": str(exc),
            },
        )
        clear_nonce_cookie(err_resp)
        return err_resp

    except InvalidOAuthStateException as exc:
        err_resp = JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "invalid_state",
                "message": "OAuth CSRF state validation failed.",
                "detail": str(exc),
            },
        )
        clear_nonce_cookie(err_resp)
        return err_resp

    except GoogleOAuthError as exc:
        err_resp = JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST if exc.status_code < 500 else status.HTTP_502_BAD_GATEWAY,
            content={
                "error": exc.error_code or "oauth_error",
                "message": "Google OAuth authorization exchange failed.",
                "detail": exc.message,
            },
        )
        clear_nonce_cookie(err_resp)
        return err_resp

    except Exception as exc:
        logger.exception("Unexpected error during Google OAuth callback")
        err_resp = JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "server_error",
                "message": "An unexpected server error occurred during OAuth processing.",
                "detail": str(exc),
            },
        )
        clear_nonce_cookie(err_resp)
        return err_resp


@router.post(
    "/google/refresh",
    response_model=OAuthRefreshResponse,
    summary="Refresh Google OAuth Tokens",
    description="Refreshes access token using stored encrypted refresh token. Never exposes tokens in response.",
)
async def refresh_google_tokens(
    connection_id: Optional[str] = Query(None, description="Optional connection ID to refresh"),
    force: bool = Query(False, description="Force refresh even if token not expired yet"),
    google_service: GoogleOAuthService = Depends(get_google_oauth_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Refreshes access token for a Google connection using server-side encrypted refresh token.
    Updates the encrypted credentials in the database and returns safe connection metadata.
    """
    query = db.query(SourceConnection).filter(
        SourceConnection.user_id == current_user.id,
        SourceConnection.provider == "google",
    )
    if connection_id:
        query = query.filter(SourceConnection.id == connection_id)

    connection = query.first()
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Google connection found for user '{current_user.id}'.",
        )

    try:
        refreshed_connection = await google_service.refresh_credentials(
            connection=connection,
            db=db,
            force=force,
        )
        safe_conn = SourceConnectionRead.model_validate(refreshed_connection)
        return OAuthRefreshResponse(
            success=True,
            message="Google access token refreshed successfully.",
            connection=safe_conn,
        )
    except CredentialsExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "credentials_expired",
                "message": str(exc),
                "hint": "Please re-authenticate via GET /auth/google",
            },
        )
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": exc.error_code or "refresh_failed",
                "message": str(exc),
            },
        )


@router.post(
    "/google/disconnect",
    response_model=OAuthDisconnectResponse,
    summary="Disconnect Google Account & Revoke Credentials",
    description="Revokes credentials with Google, marks connection as disconnected, and updates database.",
)
async def disconnect_google(
    connection_id: Optional[str] = Query(None, description="Optional connection ID to disconnect"),
    google_service: GoogleOAuthService = Depends(get_google_oauth_service),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Disconnects Google Meet connection, calls Google revocation API, and marks connection as disconnected.
    """
    query = db.query(SourceConnection).filter(
        SourceConnection.user_id == current_user.id,
        SourceConnection.provider == "google",
    )
    if connection_id:
        query = query.filter(SourceConnection.id == connection_id)

    connection = query.first()
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Google connection found for user '{current_user.id}'.",
        )

    await google_service.revoke_connection(connection=connection, db=db)

    return OAuthDisconnectResponse(
        success=True,
        message="Google account disconnected and tokens revoked.",
        connection_id=connection.id,
        status=connection.status,
    )


@router.get(
    "/connections",
    response_model=List[SourceConnectionRead],
    include_in_schema=False,
)
@router.get(
    "/google/connections",
    response_model=List[SourceConnectionRead],
    summary="List User Google Connections",
    description="Returns list of all connections for the authenticated user. Excludes all secrets and tokens.",
)
async def list_google_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lists all source connections for the current user.
    Strictly excludes sensitive tokens and secrets.
    """
    connections = (
        db.query(SourceConnection)
        .filter(SourceConnection.user_id == current_user.id)
        .order_by(SourceConnection.created_at.desc())
        .all()
    )
    return [SourceConnectionRead.model_validate(c) for c in connections]
