"""
Structured logging configuration for JULIBOT.

Provides safe logging that avoids exposing secrets or sensitive user content.
"""

import logging
import sys
from typing import Any, Dict

from app.core.config import get_settings


SENSITIVE_KEYS = {
    "password",
    "token",
    "access_token",
    "authorization",
    "secret",
    "secret_key",
    "api_key",
    "google_api_key",
    "id_token",
    "hashed_password",
}


def redact_sensitive(data: Any) -> Any:
    """Recursively redact sensitive values from dictionaries/lists."""
    if isinstance(data, dict):
        redacted: Dict[str, Any] = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive(value)
        return redacted
    if isinstance(data, list):
        return [redact_sensitive(item) for item in data]
    return data


class SafeFormatter(logging.Formatter):
    """Formatter that redacts sensitive values from log records."""

    def format(self, record: logging.LogRecord) -> str:
        # Redact sensitive data from extra fields
        for key, value in list(record.__dict__.items()):
            if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
                setattr(record, key, "[REDACTED]")
            elif isinstance(value, (dict, list)):
                setattr(record, key, redact_sensitive(value))
        return super().format(record)


def setup_logging() -> None:
    """Configure application logging."""
    settings = get_settings()

    level = logging.DEBUG if settings.debug else logging.INFO

    # Use a structured-ish format that works well in terminals and log collectors
    formatter = SafeFormatter(
        fmt=(
            "%(asctime)s | %(levelname)-8s | %(name)s | "
            "%(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Keep noisy libraries quieter unless debugging
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.debug else logging.WARNING
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    logging.getLogger(__name__).info(
        "Logging configured",
        extra={"environment": settings.environment, "debug": settings.debug},
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given module name."""
    return logging.getLogger(name)
