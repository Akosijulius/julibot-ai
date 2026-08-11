"""
Centralized safe-error response helpers for JULIBOT.

Every unhandled path ultimately returns a generic 500 body that never leaks
stack traces, passwords, or internal details. The ``error_id`` in each response
is a random12-char hex token; the same id is logged server-side so support can
correlate a user-reported error to the full traceback.

Why this file exists:
- The app-level ``@app.exception_handler(Exception)`` covers routes that are NOT
  wrapped in a ``BaseHTTPMiddleware`` task group.
- ``request_logging`` middleware covers the ``BaseExceptionGroup`` case (where
  Starlette's ``BaseHTTPMiddleware`` wraps the exception in a task group that is
  a ``BaseException``, not an ``Exception``, so the app-level handler misses it).

Both paths call ``internal_error_response`` to keep the logic DRY and consistent.
"""

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger


def internal_error_response(
    request: Request,
    exc: BaseException,
) -> JSONResponse:
    """Return a safe 500 JSONResponse with a stable ``error_id``.

    Logs the full traceback server-side with the ``error_id`` and (if the
    request-logging middleware already ran) the ``request_id`` so support can
    correlate user reports to logs. Never leaks internals to the client.
    """
    logger = get_logger(__name__)
    error_id = uuid.uuid4().hex[:12]
    request_id = getattr(request.state, "request_id", None)

    logger.exception(
        "Unhandled %s on %s (error_id=%s)",
        type(exc).__name__,
        request.url.path,
        error_id,
        exc_info=exc,
        extra={
            "error_id": error_id,
            "request_id": request_id,
            "path": request.url.path,
        },
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred. Please try again.",
            "error": "INTERNAL_SERVER_ERROR",
            "error_id": error_id,
        },
    )
