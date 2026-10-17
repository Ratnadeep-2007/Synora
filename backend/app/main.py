import os

# faster-whisper (via ctranslate2/ONNX/MKL) trips on duplicate OpenMP
# runtimes on Windows unless this is set before those libraries load.
# The server process is started bare (no launcher env), so the backend
# must guarantee it itself — otherwise the Whisper fallback crashes
# with OMP Error #15 exactly when it is needed most.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import asyncio
import hashlib
import time
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.connectors import router as connectors_router
from app.api.meet_events import router as meet_events_router
from app.api.meet_events import pubsub_router, subscriptions_router
from app.api.meetings import router as meetings_router
from app.api.projects import router as projects_router, workspace_router
from app.api.system import router as system_router
from app.api.unknown_context import router as unknown_context_router
from app.api.vexa_meetings import router as vexa_meetings_router
from app.api.workspace_atlas import router as workspace_atlas_router
from app.api.memory import router as memory_router
from app.connectors import registry  # Auto-initializes default connectors
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.exceptions import SynesisException
from app.core.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware
from app.core.neon_auth import verify_neon_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("synesis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("Starting Synesis Backend...")
    if settings.ENVIRONMENT == "production" and settings.DATABASE_URL.startswith("sqlite"):
        raise RuntimeError("DATABASE_URL must point to Neon Postgres in production")
    if settings.AUTH_REQUIRED and not all((settings.NEON_AUTH_BASE_URL, settings.NEON_AUTH_JWKS_URL)):
        raise RuntimeError("Neon Auth base and JWKS URLs must be set")
    # Initialize database tables
    try:
        init_db()
        logger.info("Database initialized successfully.")
    except Exception as exc:
        logger.error(f"Database initialization failed: {exc}")

    # Check OAuth configuration
    if settings.is_google_oauth_configured:
        logger.info("Google OAuth is CONFIGURED and ready.")
    else:
        logger.warning(
            "Google OAuth is NOT fully configured. "
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env."
        )

    # Start WhatsApp background batch worker
    stop_event = asyncio.Event()

    def _process_whatsapp_batches():
        from app.services.whatsapp_batch_service import WhatsAppBatchService
        with SessionLocal() as db:
            WhatsAppBatchService().process_due_batches(db=db, tenant_id="default_tenant", force=False)

    async def _batch_worker():
        while not stop_event.is_set():
            try:
                await asyncio.sleep(settings.WHATSAPP_BATCH_POLL_SECONDS or 5)
                await run_in_threadpool(_process_whatsapp_batches)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"WhatsApp background batch worker error: {exc}")

    worker_task = asyncio.create_task(_batch_worker())

    # Resume any Vexa captures left unfinished by a previous run: their
    # recordings are transcribed and pushed through the pipeline here.
    if settings.VEXA_ENABLED:
        try:
            from app.services.vexa_sarvam_service import reconcile_captures_on_startup

            asyncio.create_task(reconcile_captures_on_startup())
        except Exception as exc:
            logger.warning(f"Vexa capture reconciliation not started: {exc}")

    # Visual memory reconciliation runs in the dedicated
    # visual_sync_worker process so API worker count cannot multiply it.
    # Hosts without a separate worker service (Render free tier) opt in via
    # VISUAL_SYNC_IN_PROCESS; the deployment runs a single API worker, so
    # the loop still runs exactly once.
    visual_sync_task = None
    if settings.VISUAL_SYNC_IN_PROCESS:
        from app.services.visual_sync_worker import run as _run_visual_sync

        visual_sync_task = asyncio.create_task(_run_visual_sync())
        logger.info("Visual sync + memory job loop running in-process.")

    yield

    logger.info("Shutting down Synesis Backend...")
    # Bots must not stay stranded inside live Meets when the server goes
    # down: ask Vexa to pull them out (which finalizes the recordings).
    # Transcription of those recordings happens on the next startup via
    # reconcile_captures_on_startup above.
    if settings.VEXA_ENABLED:
        try:
            from app.services.vexa_sarvam_service import stop_active_captures_on_shutdown

            await asyncio.wait_for(stop_active_captures_on_shutdown(), timeout=25)
        except Exception as exc:
            logger.warning(f"Vexa shutdown bot stop incomplete: {exc}")
    stop_event.set()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    if visual_sync_task is not None:
        visual_sync_task.cancel()
        try:
            await visual_sync_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Synesis — Project Intelligence and AI Workforce Platform Backend API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.include_router(memory_router)

# Security and Observability Middlewares
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


# Successful auth resolutions are cached briefly per token: the JWT
# signature is still verified on every request (cheap, JWKS cached), but
# the Neon user lookup + workspace provisioning queries are skipped.
# Without this, every API call paid several cross-region DB round-trips
# and page-load bursts took 9-30s per request on the free instance.
_AUTH_RESOLUTION_CACHE: dict = {}
_AUTH_RESOLUTION_TTL_SECONDS = 60


@app.middleware("http")
async def require_session(request: Request, call_next):
    if not settings.AUTH_REQUIRED or request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if path.startswith(settings.API_V1_STR + "/"):
        path = path[len(settings.API_V1_STR):]
    public_paths = {"/", "/health", "/health/ready", "/auth/google/callback", "/auth/google"}
    if path in public_paths:
        return await call_next(request)
    # These callbacks have their own provider verification. Never accept an
    # unauthenticated WhatsApp webhook unless its shared secret is configured.
    if (path == "/meet-events" and settings.PUBSUB_VERIFICATION_TOKEN) or (path == "/connectors/slack/events" and settings.SLACK_SIGNING_SECRET):
        return await call_next(request)
    if path in {"/connectors/whatsapp/webhook", "/connectors/whatsapp/session-status"} and settings.WHATSAPP_WEBHOOK_SECRET:
        return await call_next(request)

    rejection = await run_in_threadpool(_resolve_authenticated_request, request, path)
    if rejection is not None:
        return rejection
    return await call_next(request)


def _resolve_authenticated_request(request: Request, path: str):
    """Resolve identity using blocking DB/JWKS clients outside the event loop."""
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return JSONResponse(status_code=401, content={"detail": "Sign in required."})

    access_path = path in {"/auth/workspace-access", "/auth/workspace/members"} or path.startswith("/auth/workspace/members/")
    cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not access_path:
        cached = _AUTH_RESOLUTION_CACHE.get(cache_key)
        if cached and cached["expires_at"] > time.time():
            # Still verify the token cryptographically on every request.
            try:
                verify_neon_token(token)
            except Exception:
                try:
                    from app.core.neon_auth import verify_session_token

                    with SessionLocal() as db:
                        if not verify_session_token(token, db):
                            return JSONResponse(status_code=401, content={"detail": "Invalid or expired session."})
                except Exception:
                    return JSONResponse(status_code=401, content={"detail": "Invalid or expired session."})
            request.state.auth_claims = cached["claims"]
            request.state.synora_user_id = cached["user_id"]
            request.state.workspace_membership_status = cached["status"]
            request.state.workspace_membership_role = cached["role"]
            if cached["status"] != "active":
                return JSONResponse(status_code=403, content={"detail": "Workspace owner approval is pending.", "code": "workspace_membership_pending"})
            return None
    prefetched_user = None
    try:
        request.state.auth_claims = verify_neon_token(token)
    except Exception:
        # Browsers may block the cross-domain auth cookie on XHR, which makes
        # the SPA's /token call fail; it then sends the opaque session token.
        # Validate that against the Neon Auth session table instead.
        try:
            from app.core.neon_auth import verify_session_token

            with SessionLocal() as db:
                prefetched_user = verify_session_token(token, db)
        except Exception:
            logger.exception("Neon Auth session token lookup failed")
            prefetched_user = None
        if not prefetched_user:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired session."})
        request.state.auth_claims = prefetched_user
    try:
        if prefetched_user is not None:
            auth_user = prefetched_user
        else:
            with SessionLocal() as db:
                auth_user = db.execute(
                    text('SELECT email, "emailVerified", banned, name FROM neon_auth."user" WHERE id = :id'),
                    {"id": request.state.auth_claims["sub"]},
                ).mappings().first()
    except Exception:
        logger.exception("Neon Auth user lookup failed")
        return JSONResponse(status_code=503, content={"detail": "Authentication database unavailable."})
    if not auth_user or not auth_user["emailVerified"] or auth_user["banned"]:
        return JSONResponse(status_code=403, content={"detail": "Verify your email before accessing Synora."})
    request.state.auth_claims["email"] = auth_user["email"]
    request.state.auth_claims["name"] = auth_user["name"]
    try:
        from app.models import User, Workspace, WorkspaceMembership
        subject = request.state.auth_claims["sub"]
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
        user_id = f"usr_neon_{digest}"
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                email = auth_user["email"].strip().lower()
                user = db.query(User).filter(User.email == email).first()
                if not user:
                    user = User(id=user_id, email=email, name=auth_user["name"] or email)
                    db.add(user)
                    db.flush()
                elif user.id != user_id:
                    user_id = user.id
            workspace = db.query(Workspace).filter(Workspace.id == "ws_default").first()
            if not workspace:
                workspace = Workspace(id="ws_default", name="Synora Workspace")
                db.add(workspace)
                db.flush()
            membership = db.query(WorkspaceMembership).filter_by(workspace_id="ws_default", user_id=user_id).first()
            if not membership:
                first_member = db.query(WorkspaceMembership).filter_by(workspace_id="ws_default", status="active").first() is None
                membership = WorkspaceMembership(workspace_id="ws_default", user_id=user_id,
                    role="owner" if first_member else "member", status="active" if first_member else "pending")
                db.add(membership)
            db.commit()
            request.state.workspace_membership_status = membership.status
            request.state.workspace_membership_role = membership.role
            request.state.synora_user_id = user_id
    except Exception:
        logger.exception("Workspace membership provisioning failed")
        return JSONResponse(status_code=503, content={"detail": "Could not provision workspace access."})
    access_path = path in {"/auth/workspace-access", "/auth/workspace/members"} or path.startswith("/auth/workspace/members/")
    if request.state.workspace_membership_status != "active" and not access_path:
        return JSONResponse(status_code=403, content={"detail": "Workspace owner approval is pending.", "code": "workspace_membership_pending"})
    return None

# CORS Configuration
origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3002",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SynesisException)
async def synesis_exception_handler(request: Request, exc: SynesisException):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": exc.__class__.__name__, "message": exc.message, "detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error: {exc}", exc_info=True)
    origin = request.headers.get("origin") or "*"
    headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "InternalServerError", "message": str(exc)},
        headers=headers,
    )


# Root status endpoint
@app.get("/", tags=["System"])
async def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "online",
        "docs": "/docs",
        "oauth_configured": settings.is_google_oauth_configured,
        "connectors": registry.list_providers(),
        "endpoints": {
            "google_auth_start": "/auth/google",
            "google_auth_callback": "/auth/google/callback",
            "connections": "/auth/google/connections",
            "meetings_sync": "/meetings/sync",
            "meetings_list": "/meetings",
            "vexa_capture_start": "/vexa/meetings/start",
            "connectors": "/connectors",
            "health": "/health",
            "metrics": "/metrics",
            "audit": "/audit",
        },
    }


# Mount System & Observability router
app.include_router(system_router)
app.include_router(system_router, prefix=settings.API_V1_STR)

# Mount Auth router at both `/auth` (for standard /auth/google) and `/api/v1/auth`
app.include_router(auth_router, prefix="/auth")
app.include_router(auth_router, prefix=f"{settings.API_V1_STR}/auth")

# Mount Meetings router at both `/meetings` and `/api/v1/meetings`
app.include_router(meetings_router, prefix="/meetings")
app.include_router(meetings_router, prefix=f"{settings.API_V1_STR}/meetings")

# Mount Meet event-driven pipeline routers (subscriptions, Pub/Sub, events, reconcile)
app.include_router(subscriptions_router)
app.include_router(subscriptions_router, prefix=settings.API_V1_STR)
app.include_router(pubsub_router)
app.include_router(pubsub_router, prefix=settings.API_V1_STR)
app.include_router(meet_events_router)
app.include_router(meet_events_router, prefix=settings.API_V1_STR)

# Mount Connectors router
app.include_router(connectors_router)
app.include_router(connectors_router, prefix=settings.API_V1_STR)

# Mount Projects router at both `/projects` and `/api/v1/projects`
app.include_router(projects_router, prefix="")
app.include_router(projects_router, prefix=f"{settings.API_V1_STR}")

# Mount Unknown Context triage router
app.include_router(unknown_context_router)
app.include_router(unknown_context_router, prefix=settings.API_V1_STR)

# Optional server-side Google Meet capture via self-hosted Vexa + Sarvam STT
app.include_router(vexa_meetings_router)
app.include_router(vexa_meetings_router, prefix=settings.API_V1_STR)

# Mount the single workspace Project Atlas router
app.include_router(workspace_atlas_router)
app.include_router(workspace_atlas_router, prefix=settings.API_V1_STR)

# Mount Central Workspace Agent router
app.include_router(workspace_router)
app.include_router(workspace_router, prefix=settings.API_V1_STR)

