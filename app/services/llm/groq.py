"""
Groq provider implementation.

Groq provides an OpenAI-compatible API with extremely fast inference
via custom LPU hardware. Used as the fallback provider for JULIBOT.
"""

from typing import AsyncIterator, Optional

from openai import AsyncOpenAI, APIStatusError, APIConnectionError, APITimeoutError

from app.core.config import get_settings
from app.core.exceptions import (
    AIAuthenticationError,
    AIContentFilterError,
    AIException,
    AIModelNotFoundError,
    AIOfflineError,
    AIRateLimitError,
)
from app.core.logging import get_logger
from app.services.llm.base import (
    ChatMessage,
    GenerateRequest,
    GenerateResponse,
    LLMProvider,
    ModelCapability,
    ModelInfo,
    ModelTier,
    StreamChunk,
)

logger = get_logger(__name__)
settings = get_settings()


class GroqProvider(LLMProvider):
    """Groq provider — fallback AI provider for JULIBOT.

    Uses OpenAI-compatible API via the openai SDK.
    """

    name = "groq"

    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    TIMEOUT_SECONDS = 60

    supported_models = [
        ModelInfo(
            id="llama-3.3-70b-versatile",
            name="Llama 3.3 70B",
            provider="groq",
            tier=ModelTier.BALANCED,
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            max_context_tokens=128_000,
            max_output_tokens=32_768,
            supports_system_prompt=True,
        ),
        ModelInfo(
            id="llama-3.1-8b-instant",
            name="Llama 3.1 8B Instant",
            provider="groq",
            tier=ModelTier.FAST,
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
            ],
            max_context_tokens=128_000,
            max_output_tokens=8_192,
            supports_system_prompt=True,
        ),
    ]

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key or settings.groq_api_key or "").strip()
        self.configured = bool(self.api_key)

        if self.configured:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.DEFAULT_BASE_URL,
                timeout=self.TIMEOUT_SECONDS,
            )
            logger.info("Groq provider configured")
        else:
            self.client = None
            logger.warning("Groq provider not configured — missing API key")

    async def is_available(self) -> bool:
        """Check if Groq is configured."""
        return self.configured

    def _convert_messages(
        self,
        messages: list[ChatMessage],
        system_prompt: Optional[str] = None,
    ) -> list[dict]:
        """Convert generic messages to OpenAI chat format."""
        openai_messages = []

        if system_prompt:
            openai_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.role == "system":
                if not system_prompt:
                    openai_messages.append({"role": "system", "content": msg.content})
            else:
                openai_messages.append({"role": msg.role, "content": msg.content})

        return openai_messages

    def _map_error(self, error: Exception, model: str) -> AIException:
        """Map OpenAI SDK errors to JULIBOT exceptions."""
        if isinstance(error, APIStatusError):
            status = getattr(error, "status_code", 0)
            msg = str(error.message).lower() if hasattr(error, "message") else str(error).lower()

            if status == 401:
                return AIAuthenticationError(
                    "Groq authentication failed. Check GROQ_API_KEY.",
                    provider=self.name,
                )
            if status == 429:
                return AIRateLimitError(
                    "Groq rate limit exceeded. Please try again shortly.",
                    provider=self.name,
                )
            if status == 404:
                return AIModelNotFoundError(model=model, provider=self.name)
            if "blocked" in msg or "safety" in msg:
                return AIContentFilterError(
                    "Response blocked by safety filters. Please rephrase."
                )

        if isinstance(error, APITimeoutError):
            return AIException(
                "Groq request timed out.",
                code="AI_TIMEOUT",
                provider=self.name,
                recoverable=True,
            )

        if isinstance(error, APIConnectionError):
            return AIException(
                "Could not connect to Groq.",
                code="AI_CONNECTION_ERROR",
                provider=self.name,
                recoverable=True,
            )

        logger.exception("Unmapped Groq error", extra={"model": model})
        return AIException(
            "Groq encountered an error.",
            code="GROQ_ERROR",
            provider=self.name,
            recoverable=True,
        )

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Generate a non-streaming response."""
        if not self.configured or not self.client:
            raise AIOfflineError(
                "Groq provider not configured. Set GROQ_API_KEY."
            )

        model_id = request.model or self.DEFAULT_MODEL
        messages = self._convert_messages(request.messages, request.system_prompt)

        try:
            response = await self.client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )

            choice = response.choices[0]
            content = choice.message.content or ""

            return GenerateResponse(
                content=content,
                model=model_id,
                provider=self.name,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
                finish_reason=choice.finish_reason,
            )

        except Exception as e:
            raise self._map_error(e, model_id) from e

    async def generate_stream(
        self,
        request: GenerateRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response."""
        if not self.configured or not self.client:
            raise AIOfflineError(
                "Groq provider not configured. Set GROQ_API_KEY."
            )

        model_id = request.model or self.DEFAULT_MODEL
        messages = self._convert_messages(request.messages, request.system_prompt)

        try:
            stream = await self.client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield StreamChunk(
                        content=chunk.choices[0].delta.content,
                        model=model_id,
                        provider=self.name,
                        is_final=False,
                    )

            yield StreamChunk(
                content="",
                model=model_id,
                provider=self.name,
                is_final=True,
                finish_reason="stop",
            )

        except Exception as e:
            raise self._map_error(e, model_id) from e
