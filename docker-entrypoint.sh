#!/bin/sh
# JULIBOT container entrypoint.
#  1. Runs Alembic migrations against the configured DATABASE_URL.
#  2. Starts uvicorn with production-safe settings.
#
# All values come from environment variables (docker-compose / platform env).

set -e

echo "==> Applying database migrations..."
alembic upgrade head

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"

echo "==> Starting uvicorn on ${HOST}:${PORT} with ${WORKERS} worker(s)..."
exec uvicorn app.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS"
