"""Tests for ``news_agent.agent.conversation`` — conversation history management."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from news_agent.agent.conversation import clear_history, get_history, send_message
from news_agent.db import (
    create_conversation_session,
    get_recent_conversations,
    get_write_connection,
    init_db,
    insert_article,
    insert_conversation,
)


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


def test_conversation_sessions_keep_contexts_isolated(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    conn = get_write_connection(tmp_db_path)
    try:
        first = create_conversation_session(conn, "First")
        second = create_conversation_session(conn, "Second")
        insert_conversation(conn, "user", "first message", session_id=first["id"])
        insert_conversation(conn, "user", "second message", session_id=second["id"])
        conn.commit()
        first_rows = get_recent_conversations(conn, session_id=first["id"])
        second_rows = get_recent_conversations(conn, session_id=second["id"])
    finally:
        conn.close()

    assert [row["content"] for row in first_rows] == ["first message"]
    assert [row["content"] for row in second_rows] == ["second message"]


def test_send_message_empty_input(tmp_db_path: Path) -> None:
    """Empty user input returns prompt message without LLM call."""
    init_db(tmp_db_path)
    response = send_message("   ", db_path=tmp_db_path)
    assert response == "请输入消息"


def test_send_message_includes_latest_news_bundle(
    tmp_db_path: Path, sample_bundle: dict
) -> None:
    init_db(tmp_db_path)
    (tmp_db_path.parent / "latest_state.json").write_text(
        json.dumps(sample_bundle, ensure_ascii=False), encoding="utf-8"
    )
    chat = MagicMock(return_value="已读取新闻")

    with patch("news_agent.agent.conversation.llm.chat", chat):
        with patch(
            "news_agent.agent.conversation.llm.get_today_remaining_tokens",
            return_value=50000,
        ):
            response = send_message("今天有哪些新闻？", db_path=tmp_db_path)

    assert response == "已读取新闻"
    messages = chat.call_args.kwargs["messages"]
    system_content = messages[0]["content"]
    assert sample_bundle["daily_summary"] in system_content
    assert "github_trending article 0" in system_content
    assert "不可信外部内容" in system_content


def test_send_message_falls_back_to_recent_database_articles(
    tmp_db_path: Path,
) -> None:
    init_db(tmp_db_path)
    conn = get_write_connection(tmp_db_path)
    try:
        insert_article(
            conn,
            url="https://example.com/database-news",
            title="Database fallback news",
            summary="Fallback summary",
            source="https://example.com/feed",
            domain="programming",
            published_at=None,
            summary_ai="Fallback AI summary",
        )
        conn.commit()
    finally:
        conn.close()
    chat = MagicMock(return_value="已读取数据库新闻")

    with patch("news_agent.agent.conversation.llm.chat", chat):
        with patch(
            "news_agent.agent.conversation.llm.get_today_remaining_tokens",
            return_value=50000,
        ):
            send_message("最近有什么新闻？", db_path=tmp_db_path)

    system_content = chat.call_args.kwargs["messages"][0]["content"]
    assert "Database fallback news" in system_content
    assert "Fallback AI summary" in system_content
