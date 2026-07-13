"""Tests for ``news_agent.agent.conversation`` — conversation history management."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from news_agent.agent.conversation import clear_history, get_history, send_message
from news_agent.db import get_write_connection, init_db, insert_conversation


def test_send_message_roundtrip(tmp_db_path: Path) -> None:
    """send_message persists user+assistant messages and returns AI reply."""
    init_db(tmp_db_path)

    with patch("news_agent.agent.conversation.llm.chat", return_value="AI reply"):
        with patch(
            "news_agent.agent.conversation.llm.get_today_remaining_tokens",
            return_value=50000,
        ):
            response = send_message("hello", db_path=tmp_db_path)

    assert response == "AI reply"

    history = get_history(db_path=tmp_db_path)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "hello"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "AI reply"


def test_send_message_4_messages_roundtrip(tmp_db_path: Path) -> None:
    """Insert 2 user + 2 assistant → get_history returns 4."""
    init_db(tmp_db_path)

    with patch("news_agent.agent.conversation.llm.chat", return_value="reply"):
        with patch(
            "news_agent.agent.conversation.llm.get_today_remaining_tokens",
            return_value=50000,
        ):
            send_message("msg1", db_path=tmp_db_path)
            send_message("msg2", db_path=tmp_db_path)

    history = get_history(db_path=tmp_db_path)
    assert len(history) == 4  # 2 user + 2 assistant


def test_clear_history(tmp_db_path: Path) -> None:
    """clear_history removes all messages."""
    init_db(tmp_db_path)
    conn = get_write_connection(tmp_db_path)
    try:
        insert_conversation(conn, "user", "test")
        conn.commit()
    finally:
        conn.close()

    deleted = clear_history(db_path=tmp_db_path)
    assert deleted >= 1

    history = get_history(db_path=tmp_db_path)
    assert len(history) == 0


def test_send_message_empty_input(tmp_db_path: Path) -> None:
    """Empty user input returns prompt message without LLM call."""
    init_db(tmp_db_path)
    response = send_message("   ", db_path=tmp_db_path)
    assert response == "请输入消息"
