"""
Google Gemini provider implementation (updated for 2.5 Flash).

Uses the google-generativeai SDK (current version).
Primary AI provider for JULIBOT — handles all task types.

NOTE: google-generativeai was marked inactive Nov 2025 in favor of
google-genai. Migration to the new SDK should be done when stability
is confirmed. For now this works with the existing dependency.
"""

from typing import AsyncIterator, List, Optional

import google.generativeai as genai

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

    Uses google-generativeai SDK with Gemini 2.5 Flash as the default model.
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
            genai.configure(api_key=self.api_key)
            logger.info("Gemini provider configured")
        else:
            logger.warning("Gemini provider not configured — missing API key")

    async def is_available(self) -> bool:
        """Check if Gemini is configured."""
        return self.configured

    def _convert_messages(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
    ) -> tuple[Optional[str], List[dict], Optional[str]]:
        """
        Convert generic messages to Gemini chat format.

        Returns:
            (system_prompt, history, current_user_message)
        """
        system_parts = []
        history = []
        current_user_message = None

        for i, msg in enumerate(messages):
            if msg.role == "system":
                system_parts.append(msg.content)
            elif msg.role == "user":
                if i == len(messages) - 1:
                    current_user_message = msg.content
                else:
                    history.append({"role": "user", "parts": [msg.content]})
            elif msg.role == "assistant":
                history.append({"role": "model", "parts": [msg.content]})

        combined_system = "\n\n".join(system_parts) if system_parts else None
        if system_prompt:
            combined_system = system_prompt

        return combined_system, history, current_user_message

    def _get_model(self, model_id: str, system_prompt: Optional[str] = None):
        """Create Gemini model instance."""
        return genai.GenerativeModel(
            model_name=model_id,
            system_instruction=system_prompt,
        )

    def _map_error(self, error: Exception, model: str) -> AIException:
        """Map Gemini errors to JULIBOT exceptions."""
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

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Generate a non-streaming response."""
        if not self.configured:
            raise AIOfflineError(
                "JULIBOT is running in offline mode. Set GOOGLE_API_KEY to enable AI responses."
            )

        model_id = request.model or self.DEFAULT_MODEL
        system_prompt, history, current_message = self._convert_messages(
            request.messages, request.system_prompt
        )

        if not current_message:
            raise AIException("No user message provided", code="AI_INVALID_REQUEST")

        try:
            model = self._get_model(model_id, system_prompt)
            chat = model.start_chat(history=history)

            generation_config = {}
            if request.max_tokens:
                generation_config["max_output_tokens"] = request.max_tokens
            if request.temperature is not None:
                generation_config["temperature"] = request.temperature

            response = await chat.send_message_async(
                current_message,
                generation_config=generation_config or None,
            )

            content = response.text if hasattr(response, "text") else ""

            usage = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = {
                    "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                    "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) or 0,
                    "total_tokens": getattr(response.usage_metadata, "total_token_count", 0) or 0,
                }

            return GenerateResponse(
                content=content,
                model=model_id,
                provider=self.name,
                usage=usage,
                finish_reason="stop",
            )

        except Exception as e:
            raise self._map_error(e, model_id) from e

    async def generate_stream(
        self,
        request: GenerateRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Generate a streaming response."""
        if not self.configured:
            raise AIOfflineError(
                "JULIBOT is running in offline mode. Set GOOGLE_API_KEY to enable AI responses."
            )

        model_id = request.model or self.DEFAULT_MODEL
        system_prompt, history, current_message = self._convert_messages(
            request.messages, request.system_prompt
        )

        if not current_message:
            raise AIException("No user message provided", code="AI_INVALID_REQUEST")

        try:
            model = self._get_model(model_id, system_prompt)
            chat = model.start_chat(history=history)

            generation_config = {}
            if request.max_tokens:
                generation_config["max_output_tokens"] = request.max_tokens
            if request.temperature is not None:
                generation_config["temperature"] = request.temperature

            response_stream = await chat.send_message_async(
                current_message,
                stream=True,
                generation_config=generation_config or None,
            )

            async for chunk in response_stream:
                text = ""
                try:
                    text = chunk.text
                except Exception:
                    continue

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

        except Exception as e:
            raise self._map_error(e, model_id) from e
