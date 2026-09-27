import logging
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("synesis.access")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies production security headers to all HTTP responses.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; object-src 'none';"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Extracts or generates an X-Correlation-ID for distributed tracing and structured logging.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        if not correlation_id:
            correlation_id = f"req_{uuid.uuid4().hex[:12]}"

        # Attach to request state
        request.state.correlation_id = correlation_id
        start_time = time.time()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000.0
            logger.error(
                f"Request failed: method={request.method} path={request.url.path} "
                f"correlation_id={correlation_id} duration_ms={duration_ms:.2f} error={exc}"
            )
            raise

        duration_ms = (time.time() - start_time) * 1000.0
        response.headers["X-Correlation-ID"] = correlation_id

        # Log structured request line (without secrets)
        logger.info(
            f"Request finished: method={request.method} path={request.url.path} "
            f"status={response.status_code} correlation_id={correlation_id} duration_ms={duration_ms:.2f}"
        )
        return response
