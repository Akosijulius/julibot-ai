"""
Stage 5 tests: reliability & observability.

Verifies:
- Request logging middleware emits a per-request log line and a X-Request-ID.
- /api/health (liveness) always returns 200.
- /api/health/ready returns 200 when the DB is reachable and 503 when down.
- Unhandled exceptions return a safe body tagged with an error_id.
- Circuit breaker + provider router expose status() for observability.
"""

import logging
from types import SimpleNamespace

from app.main import app
from app.services.llm.router import CircuitBreaker, ProviderRouter


async def test_liveness_returns_ok(client):
    """Liveness probe is always 200 while the process is up."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


async def test_readiness_ok_when_db_reachable(client):
    """Readiness is 200 when the database answers SELECT 1."""
    resp = await client.get("/api/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"


async def test_readiness_503_when_db_down(client, monkeypatch):
    """Readiness is 503 when the database is unreachable."""
    import app.api.health as health

    class _BrokenEngine:
        async def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(health, "engine", _BrokenEngine())

    resp = await client.get("/api/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] == "down"


async def test_request_logging_emits_line(client, caplog):
    """Every request logs a structured line and gets a X-Request-ID."""
    logger = logging.getLogger("app.middleware.request_logging")
    logger.setLevel(logging.INFO)

    with caplog.at_level(logging.INFO, logger="app.middleware.request_logging"):
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers and resp.headers["X-Request-ID"]

    records = [r for r in caplog.records if r.name == "app.middleware.request_logging"]
    assert any("GET /api/health -> 200" in r.getMessage() for r in records)


async def test_unhandled_exception_returns_safe_error_id(client):
    """A 500 returns a generic body with a stable error_id (no stack leak)."""
    async def _boom():
        raise ValueError("secret internal detail: password=x")

    app.add_api_route("/test-boom-stage5", _boom, methods=["GET"])
    try:
        resp = await client.get("/test-boom-stage5")
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/test-boom-stage5"
        ]

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "INTERNAL_SERVER_ERROR"
    assert "error_id" in body and body["error_id"]
    # The internal detail must not leak to the client.
    assert "password" not in resp.text


def test_circuit_breaker_status():
    """Circuit breaker status reflects state and failure count."""
    cb = CircuitBreaker(failure_threshold=2, recovery_seconds=1)
    assert cb.status()["state"] == "closed"
    assert cb.status()["failure_count"] == 0

    cb.record_failure()
    assert cb.status()["state"] == "closed"
    cb.record_failure()
    assert cb.status()["state"] == "open"
    assert cb.status()["failure_count"] == 2

    cb.record_success()
    assert cb.status()["state"] == "closed"


def test_provider_router_status_shape():
    """Provider router status exposes per-provider circuit state."""
    router = ProviderRouter()
    router._primary = SimpleNamespace(name="gemini")
    router._fallback = SimpleNamespace(name="groq")

    status = router.status()
    assert status["primary"]["name"] == "gemini"
    assert status["primary"]["circuit"]["state"] == "closed"
    assert status["fallback"]["name"] == "groq"
    assert status["fallback"]["circuit"]["failure_threshold"] >= 1
