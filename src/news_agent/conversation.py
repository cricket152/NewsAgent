# Main-process module — never import from worker.py
"""Conversation history management — SQLite persistence, context truncation, LLM delegation."""

from __future__ import annotations

from pathlib import Path

from news_agent import db, llm
from news_agent.llm import CostCeilingExceeded
from news_agent.logging_setup import get_logger

# ── Module-level constants ───────────────────────────────────────────

SYSTEM_PROMPT = "你是NewsAgent个人助手。基于今日新闻和上下文简洁回答用户问题。"
MAX_HISTORY = 50
MAX_CONTEXT_CHARS = 200_000
TRUNCATE_BELOW_DAYS = 14
TRUNCATION_MARKER = {"role": "system", "content": "[已省略早期对话]"}

_DEFAULT_DB = Path("data/state.db")

logger = get_logger()


def _resolve_db(db_path: Path | None) -> Path:
    """Resolve *db_path* to a concrete ``Path``, falling back to the default."""
    return Path(db_path) if db_path is not None else _DEFAULT_DB


# ── Public API ───────────────────────────────────────────────────────


def send_message(
    user_text: str,
    db_path: Path | None = None,
    system_prompt: str | None = None,
) -> str:
    """Send a user message through the conversational agent.

    Persists the message, builds a prompt from recent history, delegates to
    ``llm.chat()``, persists the response, and returns its text content.

    Args:
        user_text: The user's input message.
        db_path: Path to the SQLite state database (defaults to
            ``data/state.db``).
        system_prompt: Custom system prompt override; uses
            ``SYSTEM_PROMPT`` when *None*.

    Returns:
        The assistant's response text, or a graceful degradation message
        when input is empty or the LLM is unavailable.
    """
    # ── input validation ──────────────────────────────────────────
    if not user_text.strip():
        return "请输入消息"

    path = _resolve_db(db_path)
    prompt = system_prompt if system_prompt is not None else SYSTEM_PROMPT

    # ── persist user message ──────────────────────────────────────
    w_conn = db.get_write_connection(path)
    try:
        db.insert_conversation(w_conn, "user", user_text)
        w_conn.commit()
    finally:
        w_conn.close()

    # ── load recent history (newest-first from DB) ────────────────
    ro_conn = db.get_read_only_connection(path)
    try:
        rows = db.get_recent_conversations(ro_conn, limit=MAX_HISTORY)
    finally:
        ro_conn.close()

    # Reverse to chronological order (oldest → newest)
    rows.reverse()
    messages: list[dict] = [
        {"role": r["role"], "content": r["content"]} for r in rows
    ]

    # Prepend system prompt at index 0
    messages.insert(0, {"role": "system", "content": prompt})

    # ── context truncation (safety margin below 1 M context) ────
    total_chars = sum(len(m.get("content", "")) for m in messages)
    if total_chars > MAX_CONTEXT_CHARS:
        w_conn = db.get_write_connection(path)
        try:
            deleted = db.truncate_older_than_days(
                w_conn, days=TRUNCATE_BELOW_DAYS
            )
            w_conn.commit()
        finally:
            w_conn.close()
        logger.info(
            "truncated older than %d days (%d rows)",
            TRUNCATE_BELOW_DAYS,
            deleted,
        )

        # Re-load after truncation
        ro_conn = db.get_read_only_connection(path)
        try:
            rows = db.get_recent_conversations(ro_conn, limit=MAX_HISTORY)
        finally:
            ro_conn.close()
        rows.reverse()
        messages = [
            {"role": r["role"], "content": r["content"]} for r in rows
        ]
        messages.insert(0, {"role": "system", "content": prompt})
        messages.insert(1, dict(TRUNCATION_MARKER))

    # ── pre-check cost ceiling ────────────────────────────────────
    remaining = llm.get_today_remaining_tokens(path)
    if remaining <= 0:
        return "今日AI额度已用完，明天再来吧。"

    # ── delegate to LLM ───────────────────────────────────────────
    try:
        response_text = llm.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            db_path=path,
        )
    except CostCeilingExceeded:
        return "今日AI额度已用完"
    except Exception as e:
        logger.error("LLM call failed", exc_info=True)
        return f"AI 服务暂时不可用: {type(e).__name__}"

    # ── persist assistant response ────────────────────────────────
    w_conn = db.get_write_connection(path)
    try:
        db.insert_conversation(w_conn, "assistant", response_text)
        w_conn.commit()
    finally:
        w_conn.close()

    return response_text


def clear_history(db_path: Path | None = None) -> int:
    """Delete all conversation messages from the database.

    Uses ``db.truncate_older_than_days(days=0)`` which deletes every row
    whose ``created_at`` is before the current timestamp — effectively all
    rows in practice.

    Args:
        db_path: Path to the SQLite state database.

    Returns:
        Number of rows deleted.
    """
    path = _resolve_db(db_path)
    w_conn = db.get_write_connection(path)
    try:
        deleted = db.truncate_older_than_days(w_conn, days=0)
        w_conn.commit()
    finally:
        w_conn.close()
    logger.info("cleared %d rows", deleted)
    return deleted


def get_history(
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict]:
    """Return recent conversation messages, ordered oldest → newest.

    Args:
        limit: Maximum number of rows to return.
        db_path: Path to the SQLite state database.

    Returns:
        A list of dicts with keys ``role``, ``content``, and ``created_at``.
    """
    path = _resolve_db(db_path)
    ro_conn = db.get_read_only_connection(path)
    try:
        rows = db.get_recent_conversations(ro_conn, limit=limit)
    finally:
        ro_conn.close()
    # DB returns newest first; reverse to oldest → newest
    rows.reverse()
    return [
        {
            "role": r["role"],
            "content": r["content"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ── Smoke test (no real API calls) ───────────────────────────────────

if __name__ == "__main__":
    from news_agent.db import init_db

    path = Path("data/state.db")
    init_db(path)
    remaining = llm.get_today_remaining_tokens(path)
    print(f"remaining tokens today: {remaining}")
    print("OK")
