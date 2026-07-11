"""Tests for ``news_agent.llm`` — DeepSeek LLM client (all mocked)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from openai import (
    BadRequestError,
    RateLimitError,
)

from news_agent.db import add_token_usage, get_today_token_usage, get_write_connection, init_db
from news_agent.llm import (
    DAILY_TOKEN_CEILING,
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    MODEL_NAME,
    CostCeilingExceeded,
    chat,
    get_today_remaining_tokens,
)

# ── constants ──────────────────────────────────────────────────────────────


def test_constants() -> None:
    assert MODEL_NAME == "deepseek-v4-flash"
    assert DAILY_TOKEN_CEILING == 50_000
    assert MAX_RETRIES == 5
    assert DEFAULT_TIMEOUT == 30


# ── chat behaviour ─────────────────────────────────────────────────────────


class TestChatErrors:
    def test_chat_no_api_key_raises(self) -> None:
        with patch("news_agent.llm.get_api_key", return_value=None):
            with pytest.raises(RuntimeError, match="API key not configured"):
                chat([{"role": "user", "content": "hello"}])

    def test_chat_cost_ceiling_exceeded(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            add_token_usage(conn, DAILY_TOKEN_CEILING)
            conn.commit()
        finally:
            conn.close()

        with patch("news_agent.llm.get_api_key", return_value="fake-key"):
            with pytest.raises(CostCeilingExceeded):
                chat(
                    [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
                    db_path=tmp_db_path,
                )


class TestChatSuccess:
    def test_chat_records_usage(self, tmp_db_path: Path, mock_openai_client: MagicMock) -> None:
        init_db(tmp_db_path)
        with patch("news_agent.llm.get_api_key", return_value="fake-key"):
            result = chat(
                [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
                db_path=tmp_db_path,
            )
        assert result == "mocked AI response"
        conn = get_write_connection(tmp_db_path)
        try:
            usage = get_today_token_usage(conn)
            assert usage == 100  # from mock response
        finally:
            conn.close()

    def test_chat_system_prompt_warning(
        self, mock_openai_client: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Warning logged when first message is not system role."""
        with patch("news_agent.llm.get_api_key", return_value="fake-key"):
            with caplog.at_level(logging.WARNING, logger="news_agent.llm"):
                chat([{"role": "user", "content": "hi"}])
        assert any("system prompt" in r.message.lower() for r in caplog.records)

    def test_chat_includes_thinking_disabled(self, mock_openai_client: MagicMock) -> None:
        """Verify extra_body includes thinking disabled."""
        with patch("news_agent.llm.get_api_key", return_value="fake-key"):
            chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
        create_mock = mock_openai_client.return_value.chat.completions.create
        create_mock.assert_called_once()
        _, kwargs = create_mock.call_args
        assert kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}


class TestChatRetry:
    def test_retry_on_rate_limit(self, mock_openai_client: MagicMock) -> None:
        """Should retry on RateLimitError and succeed on second attempt."""
        create_mock = mock_openai_client.return_value.chat.completions.create
        mock_success = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "success after retry"
        mock_success.choices = [mock_choice]
        mock_success.usage.total_tokens = 50
        create_mock.side_effect = [
            RateLimitError("rate limited", response=MagicMock(), body=None),
            mock_success,
        ]

        with patch("news_agent.llm.get_api_key", return_value="fake-key"):
            result = chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
        assert result == "success after retry"
        assert create_mock.call_count == 2

    def test_no_retry_on_400(self, mock_openai_client: MagicMock) -> None:
        """BadRequestError should NOT be retried."""
        create_mock = mock_openai_client.return_value.chat.completions.create
        create_mock.side_effect = BadRequestError(
            "bad request", response=MagicMock(), body=None
        )

        with patch("news_agent.llm.get_api_key", return_value="fake-key"):
            with pytest.raises(BadRequestError):
                chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
        # Should have been called exactly once (no retry)
        assert create_mock.call_count == 1


# ── get_today_remaining_tokens ─────────────────────────────────────────────


def test_get_today_remaining_tokens_fresh(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    remaining = get_today_remaining_tokens(tmp_db_path)
    assert remaining == DAILY_TOKEN_CEILING
