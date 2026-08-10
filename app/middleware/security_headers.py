"""
Security headers middleware for JULIBOT.

Adds standard hardening headers (HSTS, X-Content-Type-Options, frame
protection, referrer policy, and a Content-Security-Policy) to every response.

HSTS is only set in production — a local http:// dev server must never send it
or browsers will permanently force https:// for localhost.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# The app still uses a few self-controlled inline handlers (e.g. image
# `onerror` fallbacks, the retry button in app.js), so script-src includes
# 'unsafe-inline'. None of them process user-supplied data. The remaining
# directives (frame-ancestors, object-src, base-uri, form-action, connect-src,
# img-src) still provide meaningful hardening on top of the app's HTML escaping.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://accounts.google.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' https://accounts.google.com; "
    "frame-src https://accounts.google.com; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security hardening headers to all responses."""

    def __init__(self, app, enable_hsts: bool = False):
        super().__init__(app)
        self._hsts = "max-age=31536000; includeSubDomains" if enable_hsts else None

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = response.headers

        if self._hsts:
            headers.setdefault("Strict-Transport-Security", self._hsts)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Content-Security-Policy", CSP)
        headers.setdefault("X-XSS-Protection", "0")

        return response
