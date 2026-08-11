"""
Google Gemini provider implementation (google-genai SDK).

Uses the official ``google-genai`` client (successor to google-generativeai,
which was deprecated Nov 2025). Primary AI provider for JULIBOT.
"""

from typing import AsyncIterator, List, Optional

from google import genai
from google.genai import types

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


class GeminiProvider(LLMProvider):
    """Google Gemini provider — primary AI provider for JULIBOT.

    Uses the ``google-genai`` SDK with Gemini 3.5 Flash as the default model.
    """

    name = "gemini"

    DEFAULT_MODEL = "gemini-3.5-flash"
    TIMEOUT_SECONDS = 60

    supported_models = [
        ModelInfo(
            id="gemini-3.5-flash",
            name="Gemini 3.5 Flash",
            provider="gemini",
            tier=ModelTier.BALANCED,
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            max_context_tokens=1_000_000,
            max_output_tokens=65_536,
            supports_system_prompt=True,
            supports_vision=True,
        ),
        ModelInfo(
            id="gemini-2.0-flash",
            name="Gemini 2.0 Flash",
            provider="gemini",
            tier=ModelTier.FAST,
            capabilities=[
                ModelCapability.CHAT,
                ModelCapability.STREAMING,
                ModelCapability.CODE,
                ModelCapability.LONG_CONTEXT,
            ],
            max_context_tokens=1_000_000,
            max_output_tokens=8_192,
            supports_system_prompt=True,
            supports_vision=True,
        ),
    ]

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key or settings.google_api_key or "").strip()
        self.configured = bool(self.api_key)

        if self.configured:
            self._client = genai.Client(api_key=self.api_key)
            logger.info("Gemini provider configured")
        else:
            self._client = None
            logger.warning("Gemini provider not configured — missing API key")

    async def is_available(self) -> bool:
        return self.configured

    def _convert_messages(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
    ) -> tuple[Optional[str], List[types.Content], Optional[str]]:
        """
        Convert generic messages to google-genai format.

        Returns:
            (system_instruction, contents, last_user_message)
        """
        contents: List[types.Content] = []
        system_instruction: Optional[str] = system_prompt
        last_user_message: Optional[str] = None

        for i, msg in enumerate(messages):
            if msg.role == "system":
                # Multiple system messages are concatenated.
                if system_instruction:
                    system_instruction += "\n\n" + msg.content
                else:
                    system_instruction = msg.content
            elif msg.role == "user":
                if i == len(messages) - 1:
                    # The SDK accepts a plain string for the final user
                    # message; we handle this in generate() directly.
                    last_user_message = msg.content
                else:
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[types.Part(text=msg.content)],
                        )
                    )
            elif msg.role == "assistant":
                contents.append(
                    types.Content(
                        role="model",
                        parts=[types.Part(text=msg.content)],
                    )
                )

        return system_instruction, contents, last_user_message

    def _map_error(self, error: Exception, model: str) -> AIException:
        """Map google-genai errors to JULIBOT exceptions."""
        error_str = str(error).lower()

        if "api_key" in error_str or "permission" in error_str or "401" in error_str:
            return AIAuthenticationError(
                "Gemini authentication failed. Please check GOOGLE_API_KEY.",
                provider=self.name,
            )

        if "quota" in error_str or "429" in error_str or "rate" in error_str:
            return AIRateLimitError(
                "Gemini rate limit exceeded. Please try again in a moment.",
                provider=self.name,
            )

        if "not found" in error_str or "404" in error_str:
            return AIModelNotFoundError(model=model, provider=self.name)

        if "blocked" in error_str or "safety" in error_str:
            return AIContentFilterError(
                "Response was blocked by safety filters. Please rephrase your request."
            )

        if "timeout" in error_str or "timed out" in error_str:
            return AIException(
                "Gemini request timed out.",
                code="AI_TIMEOUT",
                provider=self.name,
                recoverable=True,
            )

        if "connection" in error_str or "connect" in error_str:
            return AIException(
                "Could not connect to Gemini.",
                code="AI_CONNECTION_ERROR",
                provider=self.name,
                recoverable=True,
            )

        logger.exception("Unmapped Gemini error", extra={"model": model})
        return AIException(
            "Gemini encountered an error generating a response.",
            code="GEMINI_ERROR",
            provider=self.name,
            recoverable=True,
        )

    def _build_config(
        self,
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> types.GenerateContentConfig:
        kwargs: dict = {}
        if system_instruction:
            kwargs["system_instruction"] = system_instruction
        if max_tokens:
            kwargs["max_output_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        return types.GenerateContentConfig(**kwargs)

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Generate a non-streaming response."""
        if not self.configured or not self._client:
            raise AIOfflineError(
                "JULIBOT is running in offline mode. Set GOOGLE_API_KEY to enable AI responses."
            )

        model_id = request.model or self.DEFAULT_MODEL
        system_instruction, history, last_user_msg = self._convert_messages(
            request.messages, request.system_prompt
        )

        if not last_user_msg:
            raise AIException("No user message provided", code="AI_INVALID_REQUEST")

        try:
            config = self._build_config(
                system_instruction=system_instruction,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )

            # The SDK accepts a list of Content for history + a string for
            # the final user message when the second positional argument is
            # a string. We pass history as contents and the final message
            # separately.
            contents: list = history + [last_user_msg]

            response = self._client.models.generate_content(
                model=model_id,
                contents=contents,
                config=config,
            )

            content = response.text or ""

            usage = None
            if response.usage_metadata:
                usage = {
                    "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                    "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                    "total_tokens": response.usage_metadata.total_token_count or 0,
                }

            return GenerateResponse(
                content=content,
                model=model_id,
                provider=self.name,
                usage=usage,
                finish_reason="stop",
            )

        except AIException:
            raise
        except Exception as e:
            raise self._map_error(e, model_id) from e

    async def generate_stream(
        self,
        request: GenerateRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response."""
        if not self.configured or not self._client:
            raise AIOfflineError(
                "JULIBOT is running in offline mode. Set GOOGLE_API_KEY to enable AI responses."
            )

        model_id = request.model or self.DEFAULT_MODEL
        system_instruction, history, last_user_msg = self._convert_messages(
            request.messages, request.system_prompt
        )

        if not last_user_msg:
            raise AIException("No user message provided", code="AI_INVALID_REQUEST")

        try:
            config = self._build_config(
                system_instruction=system_instruction,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )

            contents: list = history + [last_user_msg]

            async for chunk in self._client.aio.models.generate_content_stream(
                model=model_id,
                contents=contents,
                config=config,
            ):
                text = chunk.text or ""
                if text:
                    yield StreamChunk(
                        content=text,
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

        except AIException:
            raise
        except Exception as e:
            raise self._map_error(e, model_id) from e
