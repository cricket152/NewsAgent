"""DeepSeek LLM client module for the news-agent project.

Uses the ``openai`` SDK pointed at DeepSeek's OpenAI-compatible endpoint
(``https://api.deepseek.com``).  The model name ``deepseek-v4-flash`` is
hardcoded — ``deepseek-chat`` retires 2026-07-24 and MUST NOT be used.

Key behaviours:

- Thinking mode is **disabled** on every request via
  ``extra_body={"thinking": {"type": "disabled"}}`` — TTFB ~30 s otherwise.
- Exponential backoff retry on transient errors (429, connection, timeout, 5xx)
  with a 1s / 2s / 4s / 8s / 16s schedule (max 5 attempts).  Non-transient
  errors (400, 401, 403, 404) fail fast.
- Per-request timeout of 30 seconds.
- Daily token cost ceiling (default 50 000) enforced via SQLite — calls are
  refused when the ceiling is reached.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from news_agent.api_key import get_api_key, load_env_files
from news_agent.db import (
    add_token_usage,
    get_read_only_connection,
    get_today_token_usage,
    get_write_connection,
)

MODEL_NAME = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"
DEFAULT_TIMEOUT = 30
DAILY_TOKEN_CEILING = 50_000
MAX_RETRIES = 5

_logger = logging.getLogger("news_agent.llm")


class CostCeilingExceeded(Exception):
    """Raised when daily token usage has reached or exceeded the configured ceiling."""


def _get_api_key() -> str:
    """Return the DeepSeek API key, or raise ``RuntimeError`` if not configured."""
    key = get_api_key()
    if not key:
        raise RuntimeError("OpenAI-compatible API key not configured")
    return key


def _get_provider_settings() -> tuple[str, str]:
    """Return ``(base_url, model)`` from ``.env`` with legacy defaults."""
    load_env_files()
    base_url = os.environ.get("OPENAI_BASE_URL", BASE_URL).strip() or BASE_URL
    model = os.environ.get("OPENAI_MODEL", MODEL_NAME).strip() or MODEL_NAME
    return base_url.rstrip("/"), model


def _provider_kwargs(base_url: str) -> dict:
    """Return provider-specific options without breaking Grok/OpenAI APIs."""
    if "deepseek.com" in base_url.lower():
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


# Tenacity retry decorator — applied to inner API-call functions so that
# transient errors (429 / connection / timeout / 5xx) trigger retries while
# non-transient errors (400 / 401 / 403 / 404) fail fast.
#
# Schedule: 1 s → 2 s → 4 s → 8 s → 16 s (max 5 attempts total).
_RETRY_DECORATOR = retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(
        (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)
    ),
)


def chat(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
    db_path: Path | None = None,
) -> str:
    """Send a chat-completion request to DeepSeek and return the response text.

    Args:
        messages: Conversation messages.  DeepSeek's auto-caching requires the
            first message to have ``role="system"`` for 98 % cost reduction;
            a warning is logged if this convention is not followed.
        temperature: Sampling temperature (0.0–2.0).
        max_tokens: Maximum tokens in the response.
        db_path: If provided, cost ceiling is checked before the call and token
            usage is recorded afterward.

    Returns:
        The text content of the first choice.

    Raises:
        RuntimeError: If the API key is not configured.
        CostCeilingExceeded: If today's token usage already meets or exceeds the
            daily ceiling.
    """
    api_key = _get_api_key()
    base_url, model = _get_provider_settings()
    client = OpenAI(api_key=api_key, base_url=base_url)

    # ── cost ceiling guard ───────────────────────────────────────────
    if db_path is not None:
        ro_conn = get_read_only_connection(db_path)
        try:
            if get_today_token_usage(ro_conn) >= DAILY_TOKEN_CEILING:
                raise CostCeilingExceeded("Daily token ceiling reached")
        finally:
            ro_conn.close()

    # ── system prompt advisory ───────────────────────────────────────
    if not messages or messages[0].get("role") != "system":
        _logger.warning(
            "messages[0] is not a system prompt — DeepSeek auto-caching "
            "(98 %% cost reduction) may not apply"
        )

    @_RETRY_DECORATOR
    def _call() -> str:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=DEFAULT_TIMEOUT,
            **_provider_kwargs(base_url),
        )
        content = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0

        if db_path is not None and tokens > 0:
            try:
                w_conn = get_write_connection(db_path)
                try:
                    add_token_usage(w_conn, tokens)
                    w_conn.commit()
                finally:
                    w_conn.close()
            except Exception:
                _logger.warning("Failed to record token usage", exc_info=True)

        return content

    return _call()


def stream_chat(
    messages: list[dict],
    temperature: float = 0.7,
    db_path: Path | None = None,
) -> Iterator[str]:
    """Stream a chat-completion response from DeepSeek, yielding content deltas.

    Args:
        messages: See ``chat()``.
        temperature: Sampling temperature.
        db_path: If provided, cost ceiling is checked before the call and token
            usage is recorded from the final stream event.

    Yields:
        Content deltas as they arrive from the API.

    Raises:
        RuntimeError: If the API key is not configured.
        CostCeilingExceeded: If today's token usage already meets or exceeds the
            daily ceiling.
    """
    api_key = _get_api_key()
    base_url, model = _get_provider_settings()
    client = OpenAI(api_key=api_key, base_url=base_url)

    if db_path is not None:
        ro_conn = get_read_only_connection(db_path)
        try:
            if get_today_token_usage(ro_conn) >= DAILY_TOKEN_CEILING:
                raise CostCeilingExceeded("Daily token ceiling reached")
        finally:
            ro_conn.close()

    if not messages or messages[0].get("role") != "system":
        _logger.warning(
            "messages[0] is not a system prompt — DeepSeek auto-caching "
            "(98 %% cost reduction) may not apply"
        )

    @_RETRY_DECORATOR
    def _create_stream():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            timeout=DEFAULT_TIMEOUT,
            stream=True,
            stream_options={"include_usage": True},
            **_provider_kwargs(base_url),
        )

    stream = _create_stream()
    total_tokens = 0

    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content
        if chunk.usage and chunk.usage.total_tokens:
            total_tokens = chunk.usage.total_tokens

    if db_path is not None and total_tokens > 0:
        try:
            w_conn = get_write_connection(db_path)
            try:
                add_token_usage(w_conn, total_tokens)
                w_conn.commit()
            finally:
                w_conn.close()
        except Exception:
            _logger.warning("Failed to record token usage", exc_info=True)


def check_cost_ceiling(db_path: Path) -> bool:
    """Return ``True`` if remaining daily token budget > 0, ``False`` if exhausted.

    Args:
        db_path: Path to the SQLite state database.
    """
    conn = get_read_only_connection(db_path)
    try:
        return get_today_token_usage(conn) < DAILY_TOKEN_CEILING
    finally:
        conn.close()


def record_usage(tokens: int, db_path: Path) -> None:
    """Persist *tokens* to today's daily usage counter.

    Args:
        tokens: Number of tokens consumed.
        db_path: Path to the SQLite state database.
    """
    conn = get_write_connection(db_path)
    try:
        add_token_usage(conn, tokens)
        conn.commit()
    finally:
        conn.close()


def get_today_remaining_tokens(db_path: Path) -> int:
    """Return the remaining token budget for today (minimum 0).

    Args:
        db_path: Path to the SQLite state database.
    """
    conn = get_read_only_connection(db_path)
    try:
        return max(DAILY_TOKEN_CEILING - get_today_token_usage(conn), 0)
    finally:
        conn.close()


# ── ad-hoc info block ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"MODEL_NAME = {MODEL_NAME}")
    print(f"BASE_URL = {BASE_URL}")
    print(f"DAILY_TOKEN_CEILING = {DAILY_TOKEN_CEILING}")
    print("Test: pytest tests/test_llm.py -v")
