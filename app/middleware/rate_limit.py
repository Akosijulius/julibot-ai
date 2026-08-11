"""
Rate limiting middleware for JULIBOT.

Implements in-memory rate limiting for single-instance deployments.
For multi-instance production, replace with Redis-backed solution.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Tuple

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RateLimitEntry:
    """Track requests for a single client/endpoint."""

    count: int = 0
    window_start: float = field(default_factory=time.time)


@dataclass
class RateLimitConfig:
    """Configuration for a rate-limited endpoint."""

    requests_per_minute: int
    key_func: Callable[[Request], str]


class InMemoryRateLimiter:
    """
    Simple in-memory rate limiter using sliding window.

    Note: This is suitable for single-instance deployments.
    For production with multiple workers/instances, use Redis.
    """

    def __init__(self, cleanup_interval: int = 60):
        self._store: Dict[str, RateLimitEntry] = defaultdict(RateLimitEntry)
        self._last_cleanup = time.time()
        self._cleanup_interval = cleanup_interval

    def _cleanup_if_needed(self) -> None:
        """Periodically clean up old entries to prevent memory leaks."""
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            # Remove entries older than 2 minutes
            cutoff = now - 120
            keys_to_remove = [
                key for key, entry in self._store.items() if entry.window_start < cutoff
            ]
            for key in keys_to_remove:
                del self._store[key]
            self._last_cleanup = now
            logger.debug(f"Cleaned up {len(keys_to_remove)} rate limit entries")

    def check_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> Tuple[bool, int, int]:
        """
        Check if request is within rate limit.

        Returns:
            Tuple of (is_allowed, current_count, retry_after_seconds)
        """
        self._cleanup_if_needed()

        now = time.time()
        entry = self._store[key]

        # Reset window if expired
        if now - entry.window_start >= window_seconds:
            entry.count = 0
            entry.window_start = now

        entry.count += 1

        if entry.count > limit:
            retry_after = int(window_seconds - (now - entry.window_start))
            return False, entry.count, max(1, retry_after)

        return True, entry.count, 0

    def reset(self, key: str) -> None:
        """Reset rate limit for a specific key."""
        if key in self._store:
            del self._store[key]


# Global rate limiter instance
rate_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request.

    Proxy headers (X-Forwarded-For / X-Real-IP) are only trusted when
    TRUST_PROXY_HEADERS is enabled and the deployment is known to sit behind
    a trusted reverse proxy (e.g. Render). When enabled, the RIGHTMOST
    X-Forwarded-For entry is used — the value appended by the last trusted
    proxy from the real TCP peer. Any values a client prepends on the left
    are spoofable and therefore ignored.

    When disabled (default), proxy headers are ignored entirely so clients
    cannot spoof their apparent IP for rate limiting.
    """
    from app.core.config import get_settings

    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1]

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

    if request.client:
        return request.client.host

    return "unknown"


def get_user_id_or_ip(request: Request) -> str:
    """
    Get user ID if authenticated, otherwise fall back to IP.

    Allows per-user rate limiting for authenticated requests. The user id is
    decoded from the token (Authorization header or HttpOnly cookie) without
    a DB round-trip, so per-user limits are respected even though auth
    dependencies run later in the request lifecycle.
    """
    token = _token_from_request(request)
    if token:
        from app.core.security import decode_access_token

        payload = decode_access_token(token)
        if payload:
            raw = payload.get("sub")
            try:
                return f"user:{int(raw)}"
            except (TypeError, ValueError):
                pass

    return f"ip:{get_client_ip(request)}"


def _token_from_request(request: Request) -> str | None:
    """Read the access token from the Authorization header or HttpOnly cookie."""
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get("julibot_access")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting.

    Configures different limits for different endpoint patterns.
    """

    def __init__(
        self,
        app: FastAPI,
        chat_limit: int = 20,
        auth_limit: int = 10,
        global_limit: int = 100,
        import_limit: int = 10,
    ):
        super().__init__(app)
        self.chat_limit = chat_limit
        self.auth_limit = auth_limit
        self.global_limit = global_limit
        self.import_limit = import_limit

        # Define rate limit configs per endpoint pattern
        self.endpoint_limits: Dict[str, RateLimitConfig] = {
            "/api/conversations/chat": RateLimitConfig(
                requests_per_minute=chat_limit,
                key_func=get_user_id_or_ip,
            ),
            "/api/conversations/import": RateLimitConfig(
                requests_per_minute=import_limit,
                key_func=get_user_id_or_ip,
            ),
            "/api/auth/login": RateLimitConfig(
                requests_per_minute=auth_limit,
                key_func=lambda r: f"auth:{get_client_ip(r)}",
            ),
            "/api/auth/register": RateLimitConfig(
                requests_per_minute=auth_limit,
                key_func=lambda r: f"auth:{get_client_ip(r)}",
            ),
            "/api/auth/google": RateLimitConfig(
                requests_per_minute=auth_limit,
                key_func=lambda r: f"auth:{get_client_ip(r)}",
            ),
        }

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request through rate limiter."""

        # Get the path without query parameters
        path = request.url.path

        # Check endpoint-specific rate limits
        for pattern, config in self.endpoint_limits.items():
            if path.startswith(pattern):
                key = f"{pattern}:{config.key_func(request)}"
                is_allowed, count, retry_after = rate_limiter.check_rate_limit(
                    key, config.requests_per_minute
                )

                if not is_allowed:
                    logger.warning(
                        f"Rate limit exceeded for {key}",
                        extra={"path": path, "count": count},
                    )
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": "Rate limit exceeded. Please slow down.",
                            "error": "RATE_LIMIT_EXCEEDED",
                            "retry_after": retry_after,
                        },
                        headers={"Retry-After": str(retry_after)},
                    )

                break

        # Apply global rate limit
        global_key = f"global:{get_client_ip(request)}"
        is_allowed, count, retry_after = rate_limiter.check_rate_limit(
            global_key, self.global_limit
        )

        if not is_allowed:
            logger.warning(
                f"Global rate limit exceeded for {global_key}",
                extra={"path": path, "count": count},
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please try again later.",
                    "error": "RATE_LIMIT_EXCEEDED",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Continue to next middleware/handler
        response = await call_next(request)
        return response


def setup_rate_limiting(app: FastAPI) -> None:
    """Add rate limiting middleware to FastAPI app."""
    from app.core.config import get_settings

    settings = get_settings()

    app.add_middleware(
        RateLimitMiddleware,
        chat_limit=settings.rate_limit_chat,
        auth_limit=settings.rate_limit_auth,
        global_limit=settings.rate_limit_global,
        import_limit=settings.rate_limit_import,
    )

    logger.info(
        "Rate limiting configured",
        extra={
            "chat_limit": settings.rate_limit_chat,
            "auth_limit": settings.rate_limit_auth,
            "global_limit": settings.rate_limit_global,
            "import_limit": settings.rate_limit_import,
        },
    )
