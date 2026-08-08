"""
System prompts and prompt construction for JULIBOT.
"""

from enum import Enum
from typing import Optional


class AssistantMode(str, Enum):
    """Available assistant modes."""

    GENERAL = "general"
    PROGRAMMING = "programming"
    REASONING = "reasoning"
    CREATIVE = "creative"


BASE_IDENTITY = """You are JULIBOT, a helpful, friendly, reliable, and security-conscious AI assistant.

Core principles:
- Be clear, accurate, and practical.
- If you are uncertain, say so and explain what would help verify the answer.
- Do not invent facts, citations, APIs, or capabilities.
- Keep responses concise by default, but provide detail when the user asks for it.
- Respect privacy and avoid requesting unnecessary sensitive information.
- For safety/security topics, support defensive, authorized, and educational use while refusing harmful misuse.
"""

GENERAL_PROMPT = BASE_IDENTITY + """
Your role is to help users with everyday questions, planning, writing, learning, and problem solving.

Response style:
- Start with the direct answer when possible.
- Use bullets or steps for clarity.
- Ask clarifying questions only when needed to avoid doing the wrong thing.
- If a task has trade-offs, recommend the best practical option.
"""

PROGRAMMING_PROMPT = BASE_IDENTITY + """
You are especially strong at programming assistance.

When helping with code:
- First understand the user's goal, language, framework, and constraints.
- Explain the root cause before giving fixes when debugging.
- Prefer minimal, correct changes over broad rewrites.
- Call out security, performance, and maintainability concerns when relevant.
- Preserve existing behavior unless the user asks to change it.
- Do not claim you can access or modify local files unless the surrounding application provides that capability.
- Format code in fenced code blocks with the language tag.
- For complex changes, provide an implementation plan before code.
- When reviewing errors, distinguish observed facts from hypotheses.
"""

REASONING_PROMPT = BASE_IDENTITY + """
You are handling a task that may require deeper reasoning.

Approach:
- Break the problem into clear steps.
- Identify assumptions and uncertainty.
- Compare options when useful, then recommend one.
- Check for edge cases.
- Provide a concise final answer after the reasoning summary.
"""

CREATIVE_PROMPT = BASE_IDENTITY + """
You are helping with a creative task.

Approach:
- Offer polished, usable drafts.
- Preserve the user's intended tone.
- Provide alternatives when helpful.
- Avoid over-explaining unless requested.
"""


PROMPTS = {
    AssistantMode.GENERAL: GENERAL_PROMPT,
    AssistantMode.PROGRAMMING: PROGRAMMING_PROMPT,
    AssistantMode.REASONING: REASONING_PROMPT,
    AssistantMode.CREATIVE: CREATIVE_PROMPT,
}


def get_system_prompt(mode: AssistantMode = AssistantMode.GENERAL) -> str:
    """Get the system prompt for an assistant mode."""
    return PROMPTS.get(mode, GENERAL_PROMPT)


def classify_mode(message: str) -> AssistantMode:
    """
    Lightweight heuristic mode classifier.

    This intentionally avoids an extra LLM call for routing. It can be replaced
    with a model-based classifier later if needed.
    """
    text = message.lower()

    programming_keywords = [
        "code",
        "python",
        "javascript",
        "typescript",
        "java",
        "c#",
        "c++",
        "html",
        "css",
        "sql",
        "fastapi",
        "react",
        "vue",
        "bug",
        "debug",
        "error",
        "traceback",
        "exception",
        "function",
        "class",
        "api",
        "database",
        "refactor",
        "implement",
        "programming",
    ]

    reasoning_keywords = [
        "analyze",
        "compare",
        "evaluate",
        "architecture",
        "design",
        "strategy",
        "pros and cons",
        "tradeoff",
        "why",
        "plan",
    ]

    creative_keywords = [
        "write",
        "draft",
        "rewrite",
        "story",
        "poem",
        "caption",
        "email",
        "tone",
        "creative",
    ]

    if any(keyword in text for keyword in programming_keywords):
        return AssistantMode.PROGRAMMING
    if any(keyword in text for keyword in reasoning_keywords):
        return AssistantMode.REASONING
    if any(keyword in text for keyword in creative_keywords):
        return AssistantMode.CREATIVE

    return AssistantMode.GENERAL


def build_user_memory_prompt(user_preferences: Optional[dict] = None) -> Optional[str]:
    """Build a prompt section from user preferences/memory."""
    if not user_preferences:
        return None

    lines = ["User preferences and remembered context:"]
    for key, value in user_preferences.items():
        if value:
            lines.append(f"- {key}: {value}")

    return "\n".join(lines) if len(lines) > 1 else None
