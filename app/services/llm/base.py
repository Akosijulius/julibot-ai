"""
LLM Provider abstraction layer for JULIBOT.

Enables model routing, fallbacks, and provider-agnostic AI operations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Union


class ModelCapability(str, Enum):
    """Capabilities that different models may support."""

    CHAT = "chat"
    STREAMING = "streaming"
    REASONING = "reasoning"
    CODE = "code"
    VISION = "vision"
    LONG_CONTEXT = "long_context"


class ModelTier(str, Enum):
    """Model tiers for routing decisions."""

    FAST = "fast"  # Quick, cheap responses
    BALANCED = "balanced"  # Good balance of speed and quality
    REASONING = "reasoning"  # Complex reasoning, coding, analysis


@dataclass
class ModelInfo:
    """Information about an available model."""

    id: str
    name: str
    provider: str
    tier: ModelTier
    capabilities: List[ModelCapability] = field(default_factory=list)
    max_context_tokens: int = 32000
    max_output_tokens: int = 8192
    supports_system_prompt: bool = True
    supports_tools: bool = False
    supports_vision: bool = False


@dataclass
class ChatMessage:
    """A single message in a conversation."""

    role: str  # "user", "assistant", or "system"
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class GenerateRequest:
    """Request to generate a response."""

    messages: List[ChatMessage]
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: float = 0.7
    stream: bool = False
    system_prompt: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerateResponse:
    """Response from generation."""

    content: str
    model: str
    provider: str
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamChunk:
    """A chunk of a streaming response."""

    content: str
    model: str
    provider: str
    is_final: bool = False
    finish_reason: Optional[str] = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str = "base"
    supported_models: List[ModelInfo] = []

    @abstractmethod
    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Generate a response (non-streaming)."""
        pass

    @abstractmethod
    async def generate_stream(
        self, request: GenerateRequest
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response."""
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is configured and available."""
        pass

    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        """Get information about a specific model."""
        for model in self.supported_models:
            if model.id == model_id:
                return model
        return None

    def list_models(self) -> List[ModelInfo]:
        """List all supported models."""
        return self.supported_models

    def supports_capability(self, model_id: str, capability: ModelCapability) -> bool:
        """Check if a model supports a specific capability."""
        model = self.get_model_info(model_id)
        if model:
            return capability in model.capabilities
        return False


class MockProvider(LLMProvider):
    """Mock provider for testing."""

    name = "mock"
    supported_models = [
        ModelInfo(
            id="mock-model",
            name="Mock Model",
            provider="mock",
            tier=ModelTier.FAST,
            capabilities=[ModelCapability.CHAT, ModelCapability.STREAMING],
        )
    ]

    def __init__(self, response: str = "Mock response"):
        self.response = response
        self._call_count = 0

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self._call_count += 1
        return GenerateResponse(
            content=self.response,
            model="mock-model",
            provider="mock",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    async def generate_stream(
        self, request: GenerateRequest
    ) -> AsyncIterator[StreamChunk]:
        words = self.response.split()
        for i, word in enumerate(words):
            is_final = i == len(words) - 1
            yield StreamChunk(
                content=word + " " if not is_final else word,
                model="mock-model",
                provider="mock",
                is_final=is_final,
                finish_reason="stop" if is_final else None,
            )

    async def is_available(self) -> bool:
        return True
