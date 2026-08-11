"""
Request body size limit middleware.

Rejects request bodies larger than the configured limit with a 413 before they
are parsed. This is a hard guard against oversized JSON payloads and
unbounded imports, independent of any Pydantic field-length validation.
"""

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies exceeding the configured byte limit."""

    def __init__(self, app: FastAPI, max_bytes: int = 5_000_000):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": "Request body too large",
                            "error": "PAYLOAD_TOO_LARGE",
                        },
                    )
            except ValueError:
                pass

        response = await call_next(request)
        return response
