# JULIBOT — production image
# Multi-stage not needed (pure Python); keep it lean and explicit.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for bcrypt/asyncpg wheels if prebuilt wheels are unavailable.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer caching).
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the application.
COPY . .

EXPOSE 8000

# Run migrations on startup, then serve. Override via `docker run ... CMD`.
ENTRYPOINT ["sh", "./docker-entrypoint.sh"]
