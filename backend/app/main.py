import asyncio
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from app.connectors import registry  # Auto-initializes default connectors
from app.core.config import settings
from app.core.database import init_db
from app.core.exceptions import SynesisException
from app.core.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("synesis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("Starting Synesis Backend...")
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

    async def _batch_worker():
        from app.core.database import SessionLocal
        from app.services.whatsapp_batch_service import WhatsAppBatchService
        service = WhatsAppBatchService()
        while not stop_event.is_set():
            try:
                await asyncio.sleep(settings.WHATSAPP_BATCH_POLL_SECONDS or 5)
                db = SessionLocal()
                try:
                    service.process_due_batches(db=db, tenant_id="default_tenant", force=False)
                finally:
                    db.close()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"WhatsApp background batch worker error: {exc}")

    worker_task = asyncio.create_task(_batch_worker())

    # Visual memory reconciliation runs in the dedicated
    # visual_sync_worker process so API worker count cannot multiply it.

    yield

    logger.info("Shutting down Synesis Backend...")
    stop_event.set()
    worker_task.cancel()
    try:
        await worker_task
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

# Security and Observability Middlewares
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

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

