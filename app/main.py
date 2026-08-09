#JULIBOT AI

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, conversations
from app.core.config import get_settings
from app.core.exceptions import JulibotException
from app.core.logging import get_logger, setup_logging
from app.db.database import Base, engine

# Import models so SQLAlchemy metadata is populated before create_all
from app.models import Conversation, Message, User  # noqa: F401

# Initialize logging first
setup_logging()

settings = get_settings()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "src"


def _run_migrations() -> None:
    """Apply Alembic migrations to head.

    Runs synchronously inside a worker thread (see lifespan) because
    alembic/env.py starts its own event loop via ``asyncio.run``.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup and dispose the engine on shutdown.

    - Development: create missing tables directly (fast iteration).
    - Production: apply Alembic migrations. Runs in a worker thread so the
      event loop is not blocked and no nested-loop error occurs. A migration
      failure is logged but does NOT take the whole serverless function down —
      the app still starts so health checks and error responses work.
    """
    from app.core.logging import get_logger
    logger = get_logger(__name__)

    logger.info("JULIBOT starting up...")

    if settings.environment == "production":
        try:
            await asyncio.to_thread(_run_migrations)
            logger.info("Database migrations applied (production)")
        except Exception as exc:  # pragma: no cover - depends on the DB
            logger.exception("Database migration failed: %s", exc)
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized (development mode)")

    yield

    logger.info("JULIBOT shutting down...")
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="Your Everyday AI Assistant - Faster, Smarter, More Versatile",
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS — allow local frontend origins during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup rate limiting
from app.middleware.rate_limit import setup_rate_limiting
setup_rate_limiting(app)


# ── Global exception handlers ────────────────────────────────────────────
# These guarantee that an unhandled error in a route returns a clean JSON
# response instead of taking the whole server down (a common cause of
# "localhost suddenly refuses to connect").


@app.exception_handler(JulibotException)
async def julibot_exception_handler(request: Request, exc: JulibotException):
    """Handle the app's typed exceptions (AI errors, auth, etc.)."""
    logger = get_logger(__name__)
    logger.warning(
        "Handled %s on %s",
        type(exc).__name__,
        request.url.path,
        extra={"code": exc.code, "path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all: never let an unhandled exception crash the server."""
    logger = get_logger(__name__)
    logger.exception("Unhandled exception on %s", request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred. Please try again.",
            "error": "INTERNAL_SERVER_ERROR",
        },
    )

# API routers
app.include_router(auth.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")


@app.get("/api")
async def api_root():
    """API root — health/info check."""
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.app_version,
        "status": "running",
        "features": {
            "streaming": settings.enable_streaming,
            "context_management": True,
            "model_routing": True,
        },
    }


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.app_version}


@app.get("/api/config")
async def public_config():
    """
    Public client-side configuration (no secrets).

    Exposes whether Google Sign-In is configured so the frontend can decide
    whether to show/load the Google button. The Google OAuth client ID is
    intentionally public — it is not a secret.
    """
    return {
        "google_client_id": settings.google_client_id,
        "google_enabled": bool(settings.google_client_id),
        "streaming_enabled": settings.enable_streaming,
        "version": settings.app_version,
    }


@app.get("/api/models")
async def list_models():
    """List available AI models from the provider router."""
    from app.services.llm.router import get_provider_router

    router = get_provider_router()
    await router.initialize()

    return {
        "primary": router._primary.name if router._primary else None,
        "fallback": router._fallback.name if router._fallback else None,
        "models": router.list_models(),
    }


@app.get("/")
async def serve_frontend():
    """Serve the main chat UI."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        response = FileResponse(index)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs",
        "note": "Frontend not found at src/index.html",
    }


# Mount static assets if present (css/, js/, assets/)
if FRONTEND_DIR.exists():
    for sub in ("css", "js", "assets"):
        static_path = FRONTEND_DIR / sub
        if static_path.exists():
            app.mount(f"/{sub}", StaticFiles(directory=str(static_path)), name=sub)
