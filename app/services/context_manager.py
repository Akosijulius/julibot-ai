"""
Context management for conversations.

Handles token counting, history pruning, and summarization to keep
conversations within model context limits.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from app.core.config import get_settings
from app.models.conversation import Message
from app.services.llm import ChatMessage

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ContextWindow:
    """Represents a prepared context window for a model."""

    messages: List[ChatMessage] = field(default_factory=list)
    token_count: int = 0
    was_truncated: bool = False
    was_summarized: bool = False
    summary: Optional[str] = None
    excluded_message_count: int = 0


class ContextManager:
    """
    Manages conversation context for AI models.

    Responsibilities:
    - Count approximate tokens in messages
    - Prune old messages when context is too long
    - Generate summaries of excluded context
    - Build properly formatted context windows
    """

    def __init__(
        self,
        max_messages: Optional[int] = None,
        max_tokens: Optional[int] = None,
        enable_summarization: Optional[bool] = None,
    ):
        self.max_messages = max_messages or settings.max_history_messages
        self.max_tokens = max_tokens or settings.max_context_tokens
        self.enable_summarization = (
            enable_summarization
            if enable_summarization is not None
            else settings.enable_summarization
        )

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        Uses a simple heuristic: ~4 characters per token for English text.
        This is approximate and model-dependent, but sufficient for limits.
        """
        if not text:
            return 0
        # Conservative estimate: 1 token per 4 characters
        return len(text) // 4 + 1

    def estimate_messages_tokens(self, messages: List[Message]) -> int:
        """Estimate total tokens for a list of messages."""
        total = 0
        for msg in messages:
            total += self.estimate_tokens(msg.content)
            # Add overhead for message formatting
            total += 10
        return total

    def prune_messages(
        self,
        messages: List[Message],
        keep_last_n: Optional[int] = None,
    ) -> Tuple[List[Message], List[Message]]:
        """
        Prune messages to fit within limits.

        Args:
            messages: Full message history
            keep_last_n: Number of recent messages to keep (default from config)

        Returns:
            (kept_messages, excluded_messages)
        """
        keep_last_n = keep_last_n or self.max_messages

        if len(messages) <= keep_last_n:
            return messages, []

        # Keep the most recent messages
        kept = messages[-keep_last_n:]
        excluded = messages[:-keep_last_n]

        logger.debug(
            f"Pruned {len(excluded)} messages from context",
            extra={"kept": len(kept), "excluded": len(excluded)},
        )

        return kept, excluded

    def build_context(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        include_summary: Optional[str] = None,
    ) -> ContextWindow:
        """
        Build a context window for the model.

        Args:
            messages: Full message history
            system_prompt: Optional system prompt to prepend
            include_summary: Summary of earlier context to include

        Returns:
            ContextWindow with properly formatted messages
        """
        # Prune if needed
        kept_messages, excluded = self.prune_messages(messages)

        # Build chat messages
        chat_messages: List[ChatMessage] = []

        # Add system prompt first
        if system_prompt:
            chat_messages.append(ChatMessage(role="system", content=system_prompt))

        # Add summary of excluded context
        if include_summary and excluded:
            summary_content = f"[Earlier conversation summary: {include_summary}]"
            chat_messages.append(ChatMessage(role="system", content=summary_content))

        # Add conversation messages
        for msg in kept_messages:
            chat_messages.append(
                ChatMessage(role=msg.role, content=msg.content)
            )

        # Calculate token estimate
        token_count = self.estimate_messages_tokens(kept_messages)
        if system_prompt:
            token_count += self.estimate_tokens(system_prompt)
        if include_summary:
            token_count += self.estimate_tokens(include_summary)

        return ContextWindow(
            messages=chat_messages,
            token_count=token_count,
            was_truncated=len(excluded) > 0,
            was_summarized=bool(include_summary),
            summary=include_summary,
            excluded_message_count=len(excluded),
        )

    def should_summarize(self, message_count: int) -> bool:
        """Check if conversation should be summarized."""
        return (
            self.enable_summarization
            and message_count >= settings.summarization_threshold
        )

    def get_messages_for_summary(self, messages: List[Message]) -> List[Message]:
        """
        Get messages that should be summarized (older messages, not recent ones).

        Returns messages that would be excluded from the context window.
        """
        kept, excluded = self.prune_messages(messages)
        return excluded


# Singleton context manager
_context_manager: Optional[ContextManager] = None


def get_context_manager() -> ContextManager:
    """Get the global context manager instance."""
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager
