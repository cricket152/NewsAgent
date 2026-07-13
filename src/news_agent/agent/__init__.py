"""Agent subpackage — conversation engine, prompt skills, and MCP hooks."""

from news_agent.agent.conversation import (
    MAX_CONTEXT_CHARS,
    MAX_HISTORY,
    SYSTEM_PROMPT,
    TRUNCATE_BELOW_DAYS,
    TRUNCATION_MARKER,
    clear_history,
    get_history,
    send_message,
)

__all__ = [
    "send_message",
    "clear_history",
    "get_history",
    "SYSTEM_PROMPT",
    "MAX_HISTORY",
    "MAX_CONTEXT_CHARS",
    "TRUNCATE_BELOW_DAYS",
    "TRUNCATION_MARKER",
]
