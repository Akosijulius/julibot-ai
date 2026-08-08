"""
LLM provider package.

Exports the base interfaces and provider implementations.
"""

from app.services.llm.base import (
    ChatMessage,
    GenerateRequest,
    GenerateResponse,
    LLMProvider,
    MockProvider,
    ModelCapability,
    ModelInfo,
    ModelTier,
    StreamChunk,
)
from app.services.llm.gemini_new import GeminiProvider
from app.services.llm.groq import GroqProvider

__all__ = [
    # Base types
    "ChatMessage",
    "GenerateRequest",
    "GenerateResponse",
    "StreamChunk",
    "LLMProvider",
    "MockProvider",
    "ModelCapability",
    "ModelInfo",
    "ModelTier",
    # Providers
    "GeminiProvider",
    "GroqProvider",
]


def get_default_provider() -> LLMProvider:
    """Get the default LLM provider based on configuration."""
    from app.core.config import get_settings

    settings = get_settings()

    if settings.google_api_key:
        return GeminiProvider(settings.google_api_key)

    if settings.groq_api_key:
        return GroqProvider(settings.groq_api_key)

    # No provider configured — return mock for offline mode
    return MockProvider()
