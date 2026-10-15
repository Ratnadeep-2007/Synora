"""Authentication must not prevent health probes or CORS preflight responses."""
import asyncio
import threading

import httpx
from fastapi.responses import JSONResponse

from app import main
from app.core.config import settings


def test_blocking_auth_keeps_public_requests_responsive(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)

    def blocked_auth(request, path):
        started.set()
        release.wait(timeout=5)
        return JSONResponse(status_code=401, content={"detail": "Sign in required."})

    monkeypatch.setattr(main, "_resolve_authenticated_request", blocked_auth)

    async def check():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            protected = asyncio.create_task(client.get("/projects", headers={"Origin": settings.FRONTEND_URL}))
            try:
                assert await asyncio.to_thread(started.wait, 2), "Auth worker never started"
                heartbeat = await asyncio.wait_for(client.get("/"), timeout=1)
                assert heartbeat.status_code == 200
                preflight = await asyncio.wait_for(client.options("/projects", headers={
                    "Origin": settings.FRONTEND_URL,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization,content-type",
                }), timeout=1)
                assert preflight.status_code == 200
                assert preflight.headers["Access-Control-Allow-Origin"] == settings.FRONTEND_URL
            finally:
                release.set()
                denied = await protected
            assert denied.status_code == 401
            assert denied.headers["Access-Control-Allow-Origin"] == settings.FRONTEND_URL

    asyncio.run(check())
