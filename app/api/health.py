"""
Health and status endpoints for JULIBOT.

- ``GET /api/health``        — liveness: always 200 while the process is up.
- ``GET /api/health/ready``  — readiness: 200 when dependencies (database) are
  reachable, 503 otherwise. Lets a load balancer / orchestrator stop routing
  traffic to a node that cannot serve requests.
- ``GET /api/status``        — operator view: environment + provider circuit
  state so degradation is visible without digging through logs.

These endpoints perform no auth and leak no secrets. They intentionally sit
outside the auth middleware so a node can report readiness even while
authenticated endpoints are failing.
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.db.database import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness():
    """Liveness probe — always 200 while the process is running."""
    settings = get_settings()
    return {"status": "ok", "version": settings.app_version}


@router.get("/health/ready")
async def readiness():
    """Readiness probe — verifies the database is reachable."""
    db_status = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness check failed: database unreachable")
        db_status = "down"

    healthy = db_status == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ready" if healthy else "unavailable",
            "checks": {"database": db_status},
            "version": get_settings().app_version,
        },
    )


@router.get("/status")
async def system_status():
    """Operator status — environment and per-provider circuit state."""
    from app.services.llm.router import get_provider_router

    router = get_provider_router()
    await router.initialize()

    settings = get_settings()
    return {
        "environment": settings.environment,
        "version": settings.app_version,
        "streaming_enabled": settings.enable_streaming,
        "quota_enabled": settings.quota_enabled,
        "providers": router.status(),
        "models": router.list_models(),
    }
