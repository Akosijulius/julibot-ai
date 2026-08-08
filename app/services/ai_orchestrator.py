"""
AI Orchestrator for JULIBOT.

Coordinates between:
- Model routing
- Context management
- Prompt construction
- Streaming and non-streaming responses
- Error handling
"""

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from app.core.config import get_settings
from app.core.exceptions import AIException, AIOfflineError
from app.models.conversation import Message
from app.services.context_manager import ContextManager, ContextWindow, get_context_manager
from app.services.llm import ChatMessage, GenerateRequest, StreamChunk
from app.services.llm.router import ProviderRouter, get_provider_router
from app.services.prompts import AssistantMode, classify_mode, get_system_prompt

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ChatContext:
    """Context for a single chat interaction."""

    user_message: str
    conversation_id: Optional[int] = None
    conversation_history: List[Message] = field(default_factory=list)
    mode: Optional[Union[AssistantMode, str]] = None
    user_preferences: Optional[Dict[str, Any]] = None
    stream: bool = False
    model_override: Optional[str] = None


@dataclass
class ChatResult:
    """Result of a chat interaction."""

    content: str
    model: str
    provider: str
    mode: AssistantMode
    context_window: ContextWindow
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
    error: Optional[str] = None


class AIOrchestrator:
    """
    Central orchestrator for AI operations.

    Responsibilities:
    - Normalize and classify assistant mode
    - Select the requested model for the router
    - Build provider-agnostic context windows
    - Delegate generation to the model router
    - Return provider/model metadata to the API layer
    """

    def __init__(
        self,
        context_manager: Optional[ContextManager] = None,
        provider_router: Optional[ProviderRouter] = None,
    ):
        self.provider_router = provider_router or get_provider_router()
        self.context_manager = context_manager or get_context_manager()
        self._is_available: Optional[bool] = None

    async def is_available(self) -> bool:
        """Check if at least one AI provider is available."""
        if self._is_available is None:
            self._is_available = await self.provider_router.is_available()
        return self._is_available

    def determine_mode(
        self,
        user_message: str,
        explicit_mode: Optional[Union[AssistantMode, str]] = None,
    ) -> AssistantMode:
        """Return a valid AssistantMode from an explicit value or classifier."""
        if isinstance(explicit_mode, AssistantMode):
            return explicit_mode

        if isinstance(explicit_mode, str) and explicit_mode:
            try:
                return AssistantMode(explicit_mode)
            except ValueError:
                logger.warning("Unknown assistant mode '%s'; classifying instead", explicit_mode)

        return classify_mode(user_message)

    def select_model(
        self,
        mode: AssistantMode,
        model_override: Optional[str] = None,
    ) -> str:
        """
        Select the initial model for a task.

        Gemini is the primary model for all interactive chat modes. The router
        may transparently switch to the fallback model if the primary provider
        fails.
        """
        if model_override:
            return model_override

        return settings.llm_primary_model

    def _build_request(
        self,
        context: ChatContext,
        stream: bool = False,
    ) -> tuple[GenerateRequest, AssistantMode, ContextWindow]:
        """Build a provider-agnostic generation request from chat context."""
        mode = self.determine_mode(context.user_message, context.mode)
        model = self.select_model(mode, context.model_override)
        system_prompt = get_system_prompt(mode)

        context_window = self.context_manager.build_context(
            messages=context.conversation_history,
            system_prompt=system_prompt,
        )
        context_window.messages.append(
            ChatMessage(role="user", content=context.user_message)
        )

        request = GenerateRequest(
            messages=context_window.messages,
            model=model,
            system_prompt=system_prompt,
            stream=stream,
            temperature=0.7,
        )
        return request, mode, context_window

    async def chat(self, context: ChatContext) -> ChatResult:
        """Process a chat interaction (non-streaming)."""
        if not await self.is_available():
            raise AIOfflineError(
                "JULIBOT is running in offline mode. Set GOOGLE_API_KEY or "
                "GROQ_API_KEY in your .env file and restart the server."
            )

        request, mode, context_window = self._build_request(context, stream=False)

        try:
            response = await self.provider_router.generate(request)
            logger.info(
                "Chat response generated",
                extra={
                    "model": response.model,
                    "provider": response.provider,
                    "mode": mode.value,
                    "context_messages": len(context_window.messages),
                    "truncated": context_window.was_truncated,
                },
            )
            return ChatResult(
                content=response.content,
                model=response.model,
                provider=response.provider,
                mode=mode,
                context_window=context_window,
                usage=response.usage,
                finish_reason=response.finish_reason,
            )
        except AIException:
            raise
        except Exception as e:
            logger.exception("Unexpected error in chat")
            raise AIException(
                f"An unexpected error occurred: {str(e)}",
                code="AI_UNEXPECTED_ERROR",
                recoverable=True,
            )

    async def chat_stream(self, context: ChatContext) -> AsyncIterator[StreamChunk]:
        """Process a chat interaction with streaming."""
        if not await self.is_available():
            raise AIOfflineError(
                "JULIBOT is running in offline mode. Set GOOGLE_API_KEY or "
                "GROQ_API_KEY in your .env file and restart the server."
            )

        request, mode, context_window = self._build_request(context, stream=True)

        try:
            chunk_count = 0
            last_provider = "router"
            last_model = request.model or settings.llm_primary_model

            async for chunk in self.provider_router.generate_stream(request):
                chunk_count += 1
                last_provider = chunk.provider
                last_model = chunk.model
                yield chunk

            logger.info(
                "Streaming response completed",
                extra={
                    "model": last_model,
                    "provider": last_provider,
                    "mode": mode.value,
                    "chunks": chunk_count,
                    "context_messages": len(context_window.messages),
                    "truncated": context_window.was_truncated,
                },
            )
        except AIException:
            raise
        except Exception as e:
            logger.exception("Unexpected error in streaming chat")
            raise AIException(
                f"An unexpected error occurred: {str(e)}",
                code="AI_UNEXPECTED_ERROR",
                recoverable=True,
            )

    async def generate_title(self, first_message: str) -> str:
        """Generate a short title for a conversation."""
        fallback = first_message[:30] + ("..." if len(first_message) > 30 else "")
        if not await self.is_available():
            return fallback

        try:
            request = GenerateRequest(
                messages=[ChatMessage(role="user", content=first_message)],
                model=settings.llm_fallback_model,
                system_prompt=(
                    "Generate a very short title (max 5 words) for a conversation "
                    "that starts with this message. Reply only with the title, nothing else."
                ),
                temperature=0.3,
                max_tokens=20,
            )
            response = await self.provider_router.generate(request)
            title = response.content.strip()
            if not title:
                return fallback
            return title[:47] + "..." if len(title) > 50 else title
        except Exception as e:
            logger.warning("Title generation failed: %s", e)
            return fallback

    async def generate_summary(self, messages: List[Message]) -> Optional[str]:
        """Generate a concise summary of older conversation messages."""
        if not messages or not await self.is_available():
            return None

        try:
            content_parts = []
            for msg in messages[-20:]:
                role = "User" if msg.role == "user" else "Assistant"
                content_parts.append(f"{role}: {msg.content}")

            request = GenerateRequest(
                messages=[
                    ChatMessage(
                        role="user",
                        content=(
                            "Summarize this conversation in 2-3 sentences:\n\n"
                            + "\n".join(content_parts)
                        ),
                    )
                ],
                model=settings.llm_fallback_model,
                system_prompt=(
                    "You summarize conversations. Provide a concise 2-3 sentence "
                    "summary capturing main topics and important decisions."
                ),
                temperature=0.3,
                max_tokens=150,
            )
            response = await self.provider_router.generate(request)
            return response.content.strip()
        except Exception as e:
            logger.warning("Summarization failed: %s", e)
            return None


# Singleton orchestrator
_orchestrator: Optional[AIOrchestrator] = None


def get_orchestrator() -> AIOrchestrator:
    """Get the global AI orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AIOrchestrator()
    return _orchestrator
