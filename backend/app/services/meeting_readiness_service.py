"""Bounded, read-only capture checks. Never starts a bot or calls an AI provider."""

import asyncio
from datetime import datetime, timezone

import httpx

from app.core.config import settings


async def get_meeting_readiness() -> dict:
    providers = []
    if settings.SARVAM_API_KEY.strip():
        providers.append("Sarvam")
    if settings.GROQ_STT_ENABLED and settings.groq_api_keys:
        providers.append("Hosted Whisper")
    if settings.WHISPER_ENABLED:
        providers.append("Local Whisper")

    capture = {"status": "disabled", "message": "Meeting capture is disabled on this server. Ask the workspace operator to enable it."}
    if settings.VEXA_ENABLED:
        if not settings.VEXA_API_KEY.strip() or not settings.VEXA_BASE_URL.strip():
            capture = {"status": "not_configured", "message": "The capture connection is incomplete. Ask the workspace operator to configure it."}
        else:
            try:
                async def probe():
                    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                        return await client.get(
                            settings.VEXA_BASE_URL.rstrip("/") + "/bots/status",
                            headers={"X-API-Key": settings.VEXA_API_KEY.strip()},
                        )

                response = await asyncio.wait_for(probe(), timeout=6.0)
                if response.status_code in (401, 403):
                    capture = {"status": "authentication_failed", "message": "The capture service rejected its credentials. Ask the workspace operator to reconnect it."}
                elif not response.is_success:
                    capture = {"status": "unavailable", "message": "The capture service is not ready. Start the local agent and check its connection, then retry."}
                else:
                    data = response.json()
                    if not isinstance(data, dict) or not any(isinstance(data.get(key), list) for key in ("running", "running_bots")):
                        raise ValueError("Unexpected capture response")
                    capture = {"status": "reachable", "message": "Capture service is reachable. Admit the bot when you start the meeting."}
            except (httpx.RequestError, httpx.InvalidURL, asyncio.TimeoutError, ValueError):
                # Never expose URLs, credentials, or provider response bodies.
                capture = {"status": "unavailable", "message": "Cannot reach the capture service. Start the local agent, keep the computer awake, and check its connection."}

    transcription = {
        "status": "configured" if providers else "not_configured",
        "providers": providers,
        "message": (
            "Configured: " + ", ".join(providers) + ". Credits, model availability, and speaker recognition have not been checked."
            if providers else "No transcription provider is configured. Ask the workspace operator to configure one before recording."
        ),
    }
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "can_start": capture["status"] == "reachable" and bool(providers),
        "capture": capture,
        "transcription": transcription,
    }
