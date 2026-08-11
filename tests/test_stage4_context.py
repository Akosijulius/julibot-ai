"""
Stage 4 tests: context management — token-aware pruning.

Verifies:
- Count-based pruning keeps only the most recent N messages.
- Token-aware pruning removes oldest messages until the total estimated tokens
  fit within the configured budget.
- ``build_context`` subtracts system prompt overhead from the token budget.
"""

from types import SimpleNamespace

from app.services.context_manager import ContextManager


def _msg(role: str, content: str) -> SimpleNamespace:
    """Lightweight stand-in for an ORM Message (only .role/.content are used)."""
    return SimpleNamespace(role=role, content=content)


def test_prune_by_count():
    """Pruning by count limits to the most recent N messages."""
    cm = ContextManager(max_messages=3)
    messages = [
        _msg("user", "m1"),
        _msg("assistant", "m2"),
        _msg("user", "m3"),
        _msg("assistant", "m4"),
    ]

    kept, excluded = cm.prune_messages(messages)
    assert len(kept) == 3
    assert [m.content for m in kept] == ["m2", "m3", "m4"]
    assert len(excluded) == 1
    assert excluded[0].content == "m1"


def test_prune_by_token_budget():
    """Pruning by tokens continues pruning oldest messages to fit budget."""
    cm = ContextManager(max_messages=10)
    messages = [
        _msg("user", "aaaa"),  # estimate ~11 tokens (2 chars//4 + 1 + 10 overhead)
        _msg("assistant", "bbbb"),
        _msg("user", "cccc"),
        _msg("assistant", "dddd"),
    ]

    # Each message is ~11 formatted tokens. Total ~44.
    # Budget of 25 should force keeping only the 2 most recent.
    kept, excluded = cm.prune_messages(messages, token_budget=25)
    assert len(kept) == 2
    assert [m.content for m in kept] == ["cccc", "dddd"]
    assert {m.content for m in excluded} == {"aaaa", "bbbb"}


def test_build_context_accounts_for_system_overhead():
    """build_context subtracts system prompt and summary from token budget."""
    cm = ContextManager(max_messages=10, max_tokens=50)
    messages = [
        _msg("user", "aaaa"),
        _msg("assistant", "bbbb"),
        _msg("user", "cccc"),
    ]

    # Without overhead: 3 messages ~33 tokens, fits within 50.
    window = cm.build_context(messages)
    assert not window.was_truncated

    # With a massive system prompt (~30 tokens), only ~20 tokens remain for
    # conversation, forcing pruning of the oldest messages.
    system_prompt = "x" * 120  # ~30 tokens
    window_overloaded = cm.build_context(messages, system_prompt=system_prompt)
    assert window_overloaded.was_truncated
    # Only the most recent conversation message should survive
    conv_msgs = [m for m in window_overloaded.messages if m.role != "system"]
    assert len(conv_msgs) == 1
    assert conv_msgs[0].content == "cccc"


def test_prune_small_messages_fit_with_no_exclusions():
    """When messages are small, nothing is pruned regardless of count or budget."""
    cm = ContextManager(max_messages=20, max_tokens=5000)
    messages = [_msg("user", "hi"), _msg("assistant", "hello")]
    kept, excluded = cm.prune_messages(messages)
    assert len(kept) == 2
    assert len(excluded) == 0
