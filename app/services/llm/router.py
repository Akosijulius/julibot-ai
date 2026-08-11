"""
Model Router for JULIBOT.

Routes AI requests between providers:

- Gemini  (primary)   — handles all task types
- Groq    (secondary) — fallback when Gemini is unavailable

The router owns the routing strategy so the rest of the application stays
provider-agnostic. Adding a new provider later only means registering it here.
"""

import logging
import time
from typing import AsyncIterator, Optional

from app.core.config import get_settings
from app.core.exceptions import AIException, AIOfflineError
from app.services.llm.base import (
    GenerateRequest,
    GenerateResponse,
    LLMProvider,
    StreamChunk,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class CircuitBreaker:
    """Simple circuit breaker to avoid hammering a failing provider.

    States: CLOSED (normal) → OPEN (failing, skip) → HALF_OPEN (testing)
    """

    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._state = "closed"  # closed | open | half_open

    @property
    def state(self) -> str:
        if self._state == "open":
            if time.monotonic() - self._last_failure_time >= self.recovery_seconds:
                self._state = "half_open"
        return self._state

    def allow_request(self) -> bool:
        """Return True if a request should be attempted."""
        state = self.state
        return state in ("closed", "half_open")

    def record_success(self) -> None:
        """Record a successful request — close the circuit."""
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed request — potentially trip the circuit."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                "Circuit breaker OPEN — skipping provider for %.0fs",
                self.recovery_seconds,
            )

    def reset(self) -> None:
        """Reset the circuit breaker."""
        self._failure_count = 0
        self._state = "closed"
        self._last_failure_time = 0

    def status(self) -> dict:
        """Return a snapshot of the breaker for observability."""
        return {
            "state": self.state,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_seconds": self.recovery_seconds,
        }


class ProviderRouter:
    """
    Routes LLM requests to the primary (Gemini) or fallback (Groq) provider.

    Responsibilities:
    - Initialize configured providers
    - Route requests to the primary provider
    - Retry the same provider once on transient failures
    - Fall back to the secondary provider on persistent failures
    - Track provider health via circuit breakers
    - Expose a provider-agnostic generate/generate_stream surface
    """

    # Error codes that should NOT trigger a fallback — they are content-specific
    # or environment-specific and would fail on both providers.
    NON_FALLBACK_CODES = {
        "AI_CONTENT_FILTERED",
        "AI_CONTEXT_TOO_LONG",
        "AI_OFFLINE",
        "AI_AUTH_ERROR",
        "AI_MODEL_NOT_FOUND",
    }

    def __init__(self):
        self._primary: Optional[LLMProvider] = None
        self._fallback: Optional[LLMProvider] = None
        self._primary_breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=60)
        self._fallback_breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=60)
        self._initialized = False

    async def initialize(self) -> None:
        """Instantiate all configured providers."""
        if self._initialized:
            return

        # Lazily import here to avoid circular imports at module level
        from app.services.llm.gemini_new import GeminiProvider
        from app.services.llm.groq import GroqProvider

        # Primary: Gemini
        if settings.google_api_key:
            self._primary = GeminiProvider(settings.google_api_key)
            logger.info("Router: Gemini registered as primary provider")

        # Fallback: Groq
        if settings.groq_api_key:
            self._fallback = GroqProvider(settings.groq_api_key)
            logger.info("Router: Groq registered as fallback provider")

        # If only the fallback is configured, promote it to primary so the
        # application still works with a single provider.
        if not self._primary and self._fallback:
            self._primary = self._fallback
            self._fallback = None
            logger.warning("Router: no primary provider configured, promoting Groq")

        self._initialized = True

    async def is_available(self) -> bool:
        """Check if at least one provider is configured."""
        await self.initialize()
        return self._primary is not None

    def list_models(self) -> list[dict]:
        """List all available models across configured providers."""
        models = []
        seen_ids = set()
        for provider in (self._primary, self._fallback):
            if provider is None:
                continue
            for model in provider.supported_models:
                if model.id in seen_ids:
                    continue
                seen_ids.add(model.id)
                models.append(
                    {
                        "id": model.id,
                        "name": model.name,
                        "provider": model.provider,
                        "tier": model.tier.value,
                    }
                )
        return models

    def status(self) -> dict:
        """Return provider + circuit state for observability."""
        return {
            "primary": {
                "name": self._primary.name if self._primary else None,
                "circuit": (
                    self._primary_breaker.status() if self._primary else None
                ),
            },
            "fallback": {
                "name": self._fallback.name if self._fallback else None,
                "circuit": (
                    self._fallback_breaker.status() if self._fallback else None
                ),
            },
        }

    def _build_fallback_request(self, request: GenerateRequest) -> GenerateRequest:
        """Rebuild a request pointed at the fallback provider's model."""
        return GenerateRequest(
            messages=request.messages,
            model=settings.llm_fallback_model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stream=request.stream,
            system_prompt=request.system_prompt,
            tools=request.tools,
            metadata=request.metadata,
        )

    def _should_fallback(self, error: AIException) -> bool:
        """Return True when the error is worth retrying on the fallback provider."""
        return error.code not in self.NON_FALLBACK_CODES

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """Generate a response with retry and fallback.

        Strategy:
        1. Try primary (with circuit breaker check)
        2. If primary fails transiently, retry once on primary
        3. If retry fails, fall back to secondary
        4. Track failures via circuit breaker
        """
        await self.initialize()

        if not self._primary:
            raise AIOfflineError(
                "No AI provider configured. Set GOOGLE_API_KEY or GROQ_API_KEY "
                "in your .env file."
            )

        # ── Attempt primary (with retry) ──────────────────────────────────
        if self._primary_breaker.allow_request():
            try:
                result = await self._primary.generate(request)
                self._primary_breaker.record_success()
                return result
            except AIException as exc:
                self._primary_breaker.record_failure()
                logger.warning("Primary provider attempt 1 failed (%s)", exc.code)

                # Retry same provider once for transient errors
                if exc.code in ("AI_TIMEOUT", "AI_CONNECTION_ERROR"):
                    try:
                        result = await self._primary.generate(request)
                        self._primary_breaker.record_success()
                        return result
                    except AIException as retry_exc:
                        self._primary_breaker.record_failure()
                        logger.warning("Primary provider retry failed (%s)", retry_exc.code)

                # Decide whether to fall back
                if not self._fallback or not self._should_fallback(exc):
                    raise

        # ── Fallback to secondary ─────────────────────────────────────────
        if self._fallback and self._fallback_breaker.allow_request():
            logger.info("Falling back to %s", self._fallback.name)
            try:
                result = await self._fallback.generate(self._build_fallback_request(request))
                self._fallback_breaker.record_success()
                return result
            except AIException as fallback_exc:
                self._fallback_breaker.record_failure()
                logger.error("Fallback provider also failed (%s)", fallback_exc.code)
                raise

        # All providers exhausted
        raise AIOfflineError(
            "All AI providers are currently unavailable. Please try again later."
        )

    async def generate_stream(
        self,
        request: GenerateRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a response with retry and fallback.

        Falls back only if no content has been sent yet — switching providers
        mid-stream would mix partial output from two models.
        """
        await self.initialize()

        if not self._primary:
            raise AIOfflineError(
                "No AI provider configured. Set GOOGLE_API_KEY or GROQ_API_KEY "
                "in your .env file."
            )

        # ── Stream from primary ───────────────────────────────────────────
        chunks_sent = 0
        if self._primary_breaker.allow_request():
            try:
                async for chunk in self._primary.generate_stream(request):
                    chunks_sent += 1
                    yield chunk
                self._primary_breaker.record_success()
                return
            except AIException as exc:
                self._primary_breaker.record_failure()

                # Only fall back if nothing was streamed yet
                if not self._fallback or not self._should_fallback(exc) or chunks_sent > 0:
                    raise

                # Retry primary once for transient errors if nothing sent
                if chunks_sent == 0 and exc.code in ("AI_TIMEOUT", "AI_CONNECTION_ERROR"):
                    try:
                        async for chunk in self._primary.generate_stream(request):
                            chunks_sent += 1
                            yield chunk
                        self._primary_breaker.record_success()
                        return
                    except AIException:
                        self._primary_breaker.record_failure()

        # ── Fallback to secondary (only if no content sent) ───────────────
        if chunks_sent == 0 and self._fallback and self._fallback_breaker.allow_request():
            logger.info("Streaming fallback to %s", self._fallback.name)
            try:
                async for chunk in self._fallback.generate_stream(
                    self._build_fallback_request(request)
                ):
                    yield chunk
                self._fallback_breaker.record_success()
                return
            except AIException as fallback_exc:
                self._fallback_breaker.record_failure()
                logger.error("Streaming fallback failed (%s)", fallback_exc.code)
                raise

        if chunks_sent == 0:
            raise AIOfflineError(
                "All AI providers are currently unavailable. Please try again later."
            )


# Singleton
_router: Optional[ProviderRouter] = None


def get_provider_router() -> ProviderRouter:
    """Get the global provider router instance."""
    global _router
    if _router is None:
        _router = ProviderRouter()
    return _router
