"""
Request logging middleware for JULIBOT.

Logs one structured line per request: method, path, status code, latency, and
(when authenticated) the calling user id. Every request also gets a
``X-Request-ID`` so errors can be correlated back to the request that caused
them. Sensitive fields are redacted by the SafeFormatter in app/core/logging.py.
"""

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.errors import internal_error_response
from app.core.logging import get_logger
from app.middleware.rate_limit import get_user_id_or_ip

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log a structured line for every request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except BaseExceptionGroup as exc:
            # Last line of defense. Starlette's BaseHTTPMiddleware wraps route
            # exceptions in a task-group that surfaces as a BaseExceptionGroup —
            # a BaseException, NOT an Exception — so the app-level
            # @app.exception_handler(Exception) misses it and it would otherwise
            # escape as an unhandled 500 (no safe body, no error_id). Unwrap and
            # produce the safe response here.
            inner = exc.exceptions[0] if len(exc.exceptions) == 1 else exc
            duration = (time.perf_counter() - start) * 1000
            logger.warning(
                "Request %s %s escaped as %s after %.1fms — returning safe 500",
                request.method,
                request.url.path,
                type(inner).__name__,
                duration,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            return internal_error_response(request, inner)
        except Exception as exc:
            # A truly unhandled error escaped the app's handlers. Log and return
            # a safe 500 rather than letting it crash the connection.
            return internal_error_response(request, exc)

        duration = (time.perf_counter() - start) * 1000
        status = response.status_code
        response.headers.setdefault("X-Request-ID", request_id)

        log = logger.warning if status >= 400 else logger.info
        log(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.url.path,
            status,
            duration,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status,
                "duration_ms": round(duration, 1),
                "user": get_user_id_or_ip(request),
            },
        )

        return response


def setup_request_logging(app) -> None:
    """Add request logging middleware to the app."""
    app.add_middleware(RequestLoggingMiddleware)
