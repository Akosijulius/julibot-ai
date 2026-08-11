# JULIBOT — Production Deployment Guide

Everything you need to take JULIBOT from local development to a stable,
secure, production deployment. This document is the operational companion to
[README.md](README.md) (feature guide) and [SECURITY.md](SECURITY.md) (security
model).

---

## Architecture overview

JULIBOT is a single FastAPI application that serves both the JSON API and the
static frontend from `src/`. Key components:

- **FastAPI + SQLAlchemy (async)** — API layer, ORM, migrations (Alembic).
- **Database** — SQLite for local dev; PostgreSQL for production (asyncpg).
- **AI routing** — Gemini (primary) with Groq (fallback) behind a circuit
  breaker + per-model router (`app/services/llm/`).
- **Auth** — session cookies (not bearer tokens), Google OAuth optional,
  refreshable sessions, server-side session store + revocation.
- **Quota & rate limiting** — per-user daily AI usage quotas and per-endpoint
  request limits, stored in the DB.
- **Retention** — a background task prunes stale sessions/usage rows.
- **Observability** — `/api/health`, `/api/health/ready`, `/api/status`,
  structured request logging with `X-Request-ID` + `error_id` correlation.

```
Internet → reverse proxy/TLS → uvicorn (N workers) → FastAPI app
                                      ├─ middleware: request logging, rate limit,
                                      │   body-size, security headers, CORS
                                      ├─ routers: /api/auth /api/conversations
                                      │            /api/health /api/models /api/config
                                      └─ DB (PostgreSQL) ← Alembic migrations
                                            └─ AI providers (Gemini → Groq)
```

---

## Configuration

All settings come from environment variables (see `.env.example` for the full,
documented list). The production non-negotiables:

| Variable | Production value | Why |
|----------|-----------------|-----|
| `ENVIRONMENT` | `production` | Disables API docs, turns on HSTS, applies Alembic migrations |
| `SECRET_KEY` | 32+ random bytes | Signs sessions/tokens. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/julibot` | Real persistence |
| `ALLOWED_ORIGINS` | your real frontend domain(s) | CORS allow-list; prevents cross-origin reads |
| `DEBUG` | `false` | Disables SQL echo |
| `TRUST_PROXY_HEADERS` | `true` only behind a trusted proxy | Rate limiting reads `X-Forwarded-For` |

Never commit a real `SECRET_KEY`, API keys, or DB credentials. Use the
platform's secret store or set them at deploy time.

---

## Database & migrations

In production, JULIBOT applies Alembic migrations on startup (see `lifespan` in
`app/main.py` and `docker-entrypoint.sh`). A migration failure is logged and
the app still boots so health checks work — you'll see it in `/api/status` and
the logs. The release process is:

1. Create/revision the schema: `alembic revision --autogenerate -m "desc"`.
2. Review the generated file, then commit it.
3. Deploy. On startup the migration runs automatically against `DATABASE_URL`.

For zero-downtime, point the new release at the DB, let its migration run
*first* (it's non-destructive), then swap traffic. Keep `alembic/` in the image.

### PostgreSQL notes

- The app enables `pool_pre_ping` and bounded pool sizing (`DB_POOL_SIZE`,
  `DB_MAX_OVERFLOW`).
- Migrate from a single Postgres instance to a managed service (RDS /
  Cloud SQL / Supabase / Neon) for backups, failover, and point-in-time recovery.
- Health/readiness probe issues `SELECT 1`; a 503 from `/api/health/ready`
  tells a load balancer to stop routing to that node.

---

## Deployment options

### 1. Docker (self-hosted)

```bash
# Production image
docker build -t julibot .

# Local orchestration with a named volume (SQLite by default)
docker compose up --build

# Real deployment: point DATABASE_URL at PostgreSQL in .env, then:
docker compose up -d
```

`docker-compose.yml` already wires the healthcheck against `/api/health`. For
more than one worker, use a managed Postgres (not the SQLite volume) so workers
share state — see Scaling below.

### 2. Render (Procfile)

`Procfile` runs `uvicorn` directly:

```
web: uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WORKERS:-1}"
```

Steps: new Web Service → point at repo → set `ENVIRONMENT=production` + the env
vars above → attach a managed PostgreSQL → add a health check on
`/api/health`. Set `TRUST_PROXY_HEADERS=true` (Render terminates TLS) so client
IPs are correct for rate limiting.

### 3. Vercel (serverless)

`vercel.json` configures the Python function. Serverless works but note the
constraints:

- Use a managed, externally-reachable PostgreSQL (`DATABASE_URL`); SQLite files
  are ephemeral in serverless.
- `ENABLE_STREAMING` should be `false` (no long-lived SSE across cold starts).
- Migrations run in a worker thread at boot; if the platform calls the function
  infrequently, run `alembic upgrade head` from CI instead.
- Rate limiting / sessions rely on the DB, so they work across invocations.

---

## Security checklist (before go-live)

- [ ] `ENVIRONMENT=production` (hides `/docs`, enables HSTS).
- [ ] `SECRET_KEY` is a fresh random secret, rotated on rotation schedule.
- [ ] `DEBUG=false`.
- [ ] `DATABASE_URL` is PostgreSQL, not SQLite.
- [ ] `ALLOWED_ORIGINS` set to exactly the real origin(s); no `*`.
- [ ] `TRUST_PROXY_HEADERS=true` only when behind your own TLS proxy; otherwise
      leave false to prevent IP spoofing.
- [ ] A real reverse proxy / TLS termination is in front (Caddy, Nginx, Render
      edge, Cloudflare).
- [ ] `GOOGLE_API_KEY` / `GROQ_API_KEY` are set and not committed.
- [ ] AI usage quotas enabled (`QUOTA_ENABLED=true`).
- [ ] Data retention windows are what you want (see `.env.example`).
- [ ] Verify `/api/health/ready` returns 200 before routing traffic.
- [ ] Monitor `/api/status` for circuit-breaker state (Gemini open → Groq used).

See [SECURITY.md](SECURITY.md) for the full threat model.

---

## Operations

### Health & observability endpoints

| Endpoint | Use |
|----------|-----|
| `GET /api/health` | Liveness — 200 while the process is up |
| `GET /api/health/ready` | Readiness — 200 when the DB answers `SELECT 1`, else 503 |
| `GET /api/status` | Operator view — env + per-provider circuit state |
| `GET /api/models` | Live model list from the provider router |
| `GET /api/config` | Public client config (no secrets) |

Every response carries `X-Request-ID`; every 500 carries an `error_id`. Logs
include both, so a user-reported `error_id` maps straight to the server
traceback.

### Logs & error correlation

- Structured request lines: `METHOD /path -> status (duration_ms)` with
  `request_id`, `user`, `path`, `status_code`, `duration_ms`.
- Unhandled exceptions log the full traceback with `error_id` and `request_id`;
  the client only ever sees a generic 500 body (no stack / secrets leaked).

### Scaling

- **Add workers**: `WORKERS=N` (uvicorn). Requires a shared DB (Postgres), not
  the SQLite file volume.
- **Horizontal (multi-instance)**: stateless app + Postgres means you can add
  replicas. All mutable state (sessions, usage, quotas) is in the DB, so no
  sticky sessions are needed.
- **Biggest levers**: move the DB to a managed Postgres with autoscaling, put a
  CDN in front of static assets, and tune quotas/rate limits to your traffic.
- **Watch**: `/api/status` circuit state, readiness 503s, and DB connection
  pool saturation.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `localhost refuses to connect` | Port in use / old process | `python run.py --force`, or use `docker compose down` |
| Readiness 503 | DB unreachable | Check `DATABASE_URL` + network; check the DB status in logs |
| All AI calls fail | Both providers' circuits open | Check `GOOGLE_API_KEY` / `GROQ_API_KEY`; `/api/status` shows state |
| Rate-limit errors for real users | `TRUST_PROXY_HEADERS=false` behind proxy | Set `true` so real client IPs are used |
| Migrations not applied | `ENVIRONMENT` not `production` | Set `ENVIRONMENT=production`, or run `alembic upgrade head` |
