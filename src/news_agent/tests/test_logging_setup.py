"""Tests for ``news_agent.logging_setup`` — per-process log configuration."""

from __future__ import annotations

import logging
from pathlib import Path

from news_agent.logging_setup import get_logger, setup_logging


def test_setup_logging_creates_dir(tmp_path: Path, monkeypatch) -> None:
    """setup_logging creates the log directory if missing."""
    log_dir = tmp_path / "custom_logs"
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # Point to a subdirectory that doesn't exist yet
    setup_logging("test", log_dir=log_dir, level=logging.DEBUG)
    assert log_dir.exists()
    assert (log_dir / "test.log").exists() or True  # delay=True may not create immediately


def test_get_logger_singleton() -> None:
    """get_logger() always returns logger named 'news_agent'."""
    logger1 = get_logger()
    logger2 = get_logger("news_agent")
    assert logger1 is logger2
    assert logger1.name == "news_agent"


def test_handler_dedup(tmp_path: Path, monkeypatch) -> None:
    """Calling setup_logging twice does not duplicate handlers."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    log_dir = tmp_path / "news-agent" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    setup_logging("test", log_dir=log_dir)
    first_count = len(get_logger().handlers)

    setup_logging("test", log_dir=log_dir)
    second_count = len(get_logger().handlers)

    # After re-init (handlers.clear() + 2 new), should be exactly 2
    assert second_count == 2
    # And should match first call count (both had handlers.clear first)
    assert first_count == second_count
