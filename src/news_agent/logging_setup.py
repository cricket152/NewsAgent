"""Per-process logging with 7-day rotation to %APPDATA%/news-agent/logs/.

Provides per-process log files (main.log / worker.log) with daily rotation
(7-day retention). INFO-level messages go to file, WARNING+ also go to stderr.
Uses a named ``"news_agent"`` logger so library loggers are not disturbed.
"""

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def setup_logging(
    process_name: str = "main",
    log_dir: Path | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure the named ``"news_agent"`` logger with file + stderr handlers.

    Args:
        process_name: Used in the log filename, e.g. ``"main"`` produces
            ``main.log``, ``"worker"`` produces ``worker.log``.
        log_dir: Directory for log files.  Defaults to
            ``%APPDATA%/news-agent/logs/`` on Windows, falling back to
            ``~/.config/news-agent/logs/`` on other platforms.
        level: Minimum level for the file handler (default ``logging.INFO``).

    Returns:
        The configured ``"news_agent"`` logger.
    """
    if log_dir is None:
        log_dir = (
            Path(os.environ.get("APPDATA", Path.home() / ".config"))
            / "news-agent"
            / "logs"
        )
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("news_agent")

    # Clear existing handlers to avoid duplicates on re-init
    logger.handlers.clear()

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s [%(processName)s:%(process)d] %(levelname)s %(name)s: %(message)s"
    )

    # TimedRotatingFileHandler: daily rotation, 7-day retention, utf-8, lazy open
    log_path = log_dir / f"{process_name}.log"
    file_handler = TimedRotatingFileHandler(
        filename=str(log_path),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # StreamHandler to stderr for WARNING and above
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def get_logger(name: str = "news_agent") -> logging.Logger:
    """Return the ``"news_agent"`` logger for use in other modules.

    Other modules should call ``get_logger()`` without arguments to obtain
    the already-configured logger (does not reconfigure).
    """
    return logging.getLogger(name)


if __name__ == "__main__":
    setup_logging("main")
    logger = get_logger()
    logger.info("test")
    logger.warning("test-warn")
