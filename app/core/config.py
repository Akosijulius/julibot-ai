"""
Core configuration with validation and security improvements.

All sensitive values come from environment variables with validation.
"""

import json
import logging
from functools import lru_cache
from typing import List, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "JULIBOT"
    app_version: str = "0.2.0"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Database
    database_url: str = "sqlite:///./julibot.db"

    # PostgreSQL pool sizing (ignored when using SQLite). pool_pre_ping is
    # always enabled in app/db/database.py to discard stale connections.
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Security
    secret_key: str = Field(default="CHANGE-ME-IN-PRODUCTION")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # ── AI Provider: Google Gemini (primary) ───────────────────────────────────
    google_api_key: str = ""

    # ── AI Provider: Groq (fallback) ──────────────────────────────────────────
    groq_api_key: str = ""

    # ── Model Configuration ───────────────────────────────────────────────────
    # Primary model — handles all task types
    llm_primary_model: str = "gemini-3.5-flash"
    # Fallback model — used when primary is unavailable, plus titles & summaries
    llm_fallback_model: str = "llama-3.3-70b-versatile"
    # Default model sent to router when caller omits it
    llm_default_model: str = "gemini-3.5-flash"

    # Context Management
    max_history_messages: int = 20  # Max messages to send to model
    max_context_tokens: int = 30000  # Approximate token limit for context
    enable_summarization: bool = True
    summarization_threshold: int = 30  # Messages before summarizing

    # Streaming
    enable_streaming: bool = True

    # Google OAuth (Sign-In)
    google_client_id: str = ""

    # CORS — dev origins for serving the frontend (localhost/127.0.0.1) and
    # for file:// previews ("null") so the app can be tested without a server.
    # Stored as a plain string (pydantic-settings never JSON-decodes `str`,
    # which is what broke deploy with ALLOWED_ORIGINS=https://...). Use
    # `allowed_origins_list` for the parsed list.
    allowed_origins: str = (
        "http://localhost:3000,http://localhost:8000,"
        "http://127.0.0.1:8000,http://localhost:5500,"
        "http://127.0.0.1:5500,null"
    )

    # Rate Limiting (requests per minute)
    rate_limit_chat: int = 20
    rate_limit_auth: int = 10
    rate_limit_global: int = 100
    rate_limit_import: int = 10

    # Request limits
    # Reject request bodies larger than this (guards against oversized JSON
    # payloads / unbounded imports). Keep comfortably above the largest legit
    # body (profile photo data URLs, conversation imports).
    max_body_size_bytes: int = 5_000_000

    # AI generation cap — hard ceiling on per-response output tokens for a
    # single interactive turn, regardless of what a model advertises.
    max_output_tokens: int = 4096

    # Per-user daily AI usage quotas (quota foundation for guest/free/pro plans).
    quota_enabled: bool = True
    quota_daily_requests: int = 200          # registered user, requests/day
    quota_daily_output_tokens: int = 500_000 # registered user, output tokens/day
    quota_guest_daily_requests: int = 50     # guest, requests/day
    quota_guest_daily_output_tokens: int = 50_000

    # ── Data retention (privacy) ──────────────────────────────────────────────
    # How long to keep non-essential data before the background retention task
    # purges it. Sessions (login records) and daily usage aggregates are not
    # needed forever; conversation/message content is only removed on explicit
    # account deletion (DELETE /auth/me).
    session_retention_days: int = 30
    usage_retention_days: int = 365
    retention_interval_minutes: int = 60

    # Proxy trust. Set to True ONLY when deployed behind a trusted reverse
    # proxy (e.g. Render's load balancer). When True, rate limiting uses the
    # rightmost X-Forwarded-For entry (the address the trusted proxy appended
    # from the real TCP peer). Keep False when the app is exposed directly to
    # the internet — otherwise clients can spoof X-Forwarded-For to bypass
    # rate limits.
    trust_proxy_headers: bool = False

    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse ALLOWED_ORIGINS into a list (comma-separated or JSON array)."""
        if not self.allowed_origins:
            return []
        value = self.allowed_origins.strip()
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except (ValueError, TypeError):
                pass
        return [part.strip() for part in value.split(",") if part.strip()]

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str, info) -> str:
        """Ensure secret key is not the default in production."""
        if v == "CHANGE-ME-IN-PRODUCTION":
            if info.data.get("environment") == "production":
                raise ValueError(
                    "SECRET_KEY must be changed from default in production! "
                    "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            logger.warning(
                "Using default SECRET_KEY. Generate a secure key for production!"
            )
        return v

    @field_validator("google_api_key", mode="before")
    @classmethod
    def validate_google_api_key(cls, v: Optional[str]) -> str:
        """Validate and clean Google API key."""
        if not v:
            return ""
        return v.strip()

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def validate_groq_api_key(cls, v: Optional[str]) -> str:
        """Validate and clean Groq API key."""
        if not v:
            return ""
        return v.strip()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str, info) -> str:
        """Ensure database URL is configured in production."""
        if info.data.get("environment") == "production":
            if v.startswith("sqlite"):
                logger.warning(
                    "Using SQLite in production is not recommended. "
                    "Consider PostgreSQL for better performance and reliability."
                )
        return v

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to avoid re-reading environment variables on every call.
    """
    settings = Settings()

    # Log configuration on startup (without secrets)
    logger.info(f"JULIBOT {settings.app_version} starting in {settings.environment} mode")
    logger.info(f"Primary model: {settings.llm_primary_model}")
    logger.info(f"Fallback model: {settings.llm_fallback_model}")
    logger.info(f"Streaming enabled: {settings.enable_streaming}")
    logger.info(f"Max history messages: {settings.max_history_messages}")

    if not settings.google_api_key:
        logger.warning(
            "GOOGLE_API_KEY not configured. Gemini (primary provider) is disabled."
        )

    if not settings.groq_api_key:
        logger.warning(
            "GROQ_API_KEY not configured. Groq (fallback provider) is disabled."
        )

    if settings.environment == "production":
        dev_origins = {"null", "http://localhost", "http://127.0.0.1"}
        allowed = {o.rstrip("/") for o in settings.allowed_origins_list}
        if allowed & dev_origins:
            logger.warning(
                "ALLOWED_ORIGINS still contains development origins (localhost/null) "
                "in production. Set ALLOWED_ORIGINS to your real deployed domain."
            )

    return settings
