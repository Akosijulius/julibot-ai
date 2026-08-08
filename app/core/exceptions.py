"""
Custom exceptions for JULIBOT.

Provides structured error handling for AI operations, authentication, and more.
"""

from typing import Any, Dict, Optional


class JulibotException(Exception):
    """Base exception for all JULIBOT errors."""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code or "UNKNOWN_ERROR"
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


# =============================================================================
# AI/LLM Exceptions
# =============================================================================


class AIException(JulibotException):
    """Base exception for AI-related errors."""

    def __init__(
        self,
        message: str,
        code: str = "AI_ERROR",
        provider: Optional[str] = None,
        recoverable: bool = True,
        **kwargs,
    ):
        details = kwargs.get("details", {})
        if provider:
            details["provider"] = provider
        details["recoverable"] = recoverable
        super().__init__(message, code, details)


class AIAuthenticationError(AIException):
    """API key authentication failed."""

    def __init__(self, message: str = "AI service authentication failed", provider: Optional[str] = None):
        super().__init__(
            message=message,
            code="AI_AUTH_ERROR",
            provider=provider,
            recoverable=False,
        )


class AIRateLimitError(AIException):
    """Rate limit exceeded."""

    def __init__(
        self,
        message: str = "AI service rate limit exceeded",
        provider: Optional[str] = None,
        retry_after: Optional[int] = None,
    ):
        details = {}
        if retry_after:
            details["retry_after"] = retry_after
        super().__init__(
            message=message,
            code="AI_RATE_LIMIT",
            provider=provider,
            recoverable=True,
            details=details,
        )


class AIModelNotFoundError(AIException):
    """Requested model not found."""

    def __init__(self, model: str, provider: Optional[str] = None):
        super().__init__(
            message=f"Model '{model}' is not available",
            code="AI_MODEL_NOT_FOUND",
            provider=provider,
            recoverable=False,
            model=model,
        )


class AIContextTooLongError(AIException):
    """Context exceeds model limits."""

    def __init__(
        self,
        message: str = "Conversation context is too long",
        token_count: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ):
        details = {}
        if token_count:
            details["token_count"] = token_count
        if max_tokens:
            details["max_tokens"] = max_tokens
        super().__init__(
            message=message,
            code="AI_CONTEXT_TOO_LONG",
            recoverable=True,
            details=details,
        )


class AIContentFilterError(AIException):
    """Content filtered by safety systems."""

    def __init__(self, message: str = "Content was filtered by safety systems"):
        super().__init__(
            message=message,
            code="AI_CONTENT_FILTERED",
            recoverable=False,
        )


class AIStreamInterruptedError(AIException):
    """Streaming response was interrupted."""

    def __init__(self, message: str = "Streaming response interrupted"):
        super().__init__(
            message=message,
            code="AI_STREAM_INTERRUPTED",
            recoverable=True,
        )


class AIOfflineError(AIException):
    """AI service is not configured or offline."""

    def __init__(self, message: str = "AI service is running in offline mode"):
        super().__init__(
            message=message,
            code="AI_OFFLINE",
            recoverable=False,
        )


# =============================================================================
# Authentication Exceptions
# =============================================================================


class AuthException(JulibotException):
    """Base exception for authentication errors."""

    def __init__(
        self,
        message: str,
        code: str = "AUTH_ERROR",
        **kwargs,
    ):
        super().__init__(message, code, **kwargs)


class InvalidTokenError(AuthException):
    """JWT token is invalid or expired."""

    def __init__(self, message: str = "Invalid or expired authentication token"):
        super().__init__(message, code="INVALID_TOKEN")


class GuestNotAllowedError(AuthException):
    """Action not allowed for guest users."""

    def __init__(self, message: str = "Please log in to perform this action"):
        super().__init__(message, code="GUEST_NOT_ALLOWED")


# =============================================================================
# Rate Limiting Exceptions
# =============================================================================


class RateLimitException(JulibotException):
    """Rate limit exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
        limit: Optional[int] = None,
    ):
        details = {}
        if retry_after:
            details["retry_after"] = retry_after
        if limit:
            details["limit"] = limit
        super().__init__(message, code="RATE_LIMIT_EXCEEDED", details=details)


# =============================================================================
# Conversation Exceptions
# =============================================================================


class ConversationException(JulibotException):
    """Base exception for conversation errors."""

    def __init__(self, message: str, code: str = "CONVERSATION_ERROR", **kwargs):
        super().__init__(message, code, **kwargs)


class ConversationNotFoundError(ConversationException):
    """Conversation not found."""

    def __init__(self, conversation_id: int):
        super().__init__(
            message=f"Conversation {conversation_id} not found",
            code="CONVERSATION_NOT_FOUND",
            conversation_id=conversation_id,
        )


class MessageTooLongError(ConversationException):
    """Message exceeds maximum length."""

    def __init__(self, length: int, max_length: int):
        super().__init__(
            message=f"Message exceeds maximum length of {max_length} characters",
            code="MESSAGE_TOO_LONG",
            length=length,
            max_length=max_length,
        )
