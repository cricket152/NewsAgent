"""Worker: Task-Scheduler-triggered CLI process that fetches news + runs curator
+ writes articles to SQLite + writes the latest daily bundle JSON for the main
popup process to render.

NEVER imports any GUI library (webview/tkinter/pystray). The Worker is a pure
CLI process; importing pywebview would crash it (Issue #1387 two processes
can't share WebView2).

Uses a PID lock file at %TEMP%/news-agent-worker.lock to prevent 6AM/18PM
overlap. Has a 15-minute watchdog that hard-exits if the cycle hangs.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Task Scheduler invokes this file by absolute path, with an arbitrary
# working directory (usually ``C:\Windows\System32``).  In a source checkout
# that means the ``src`` directory is not on ``sys.path`` yet.  Bootstrap it
# before importing the package so scheduled refreshes work in development as
# well as in an installed/frozen build.
if __package__ in (None, ""):
    _src_dir = Path(__file__).resolve().parents[1]
    if str(_src_dir) not in sys.path:
        sys.path.insert(0, str(_src_dir))

from news_agent.config import load_config
from news_agent.db import (
    cleanup_old_articles,
    cleanup_old_conversations,
    get_write_connection,
    init_db,
    insert_article,
)
from news_agent.logging_setup import get_logger, setup_logging

try:
    from news_agent.curator import run_curator
except ImportError:
    # Stub for when curator module is not yet implemented (T14)
    def run_curator(config, db_path=None):
        """Stub — curator module not yet implemented."""
        _logger = logging.getLogger("news_agent")
        _logger.warning("curator.run_curator not available, returning empty bundle")
        return {
            "articles_by_domain": {},
            "weather": None,
            "fortune": {},
            "daily_summary": "",
            "headlines_only_mode": False,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_state_dir() -> Path:
    """Return ``%APPDATA%/news-agent/``, creating the directory if needed."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        state_dir = Path(appdata) / "news-agent"
    else:
        state_dir = Path.cwd() / "data"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _resolve_db_path() -> Path:
    """Return the SQLite database path, creating parent directories.

    Priority: ``%APPDATA%/news-agent/data/state.db``,
    falling back to ``<cwd>/data/state.db``.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        db_path = Path(appdata) / "news-agent" / "data" / "state.db"
    else:
        db_path = Path.cwd() / "data" / "state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _resolve_output_path() -> Path:
    """Return the path for ``latest_state.json`` (parent dir guaranteed to exist)."""
    return _resolve_state_dir() / "latest_state.json"


def _is_pid_alive(pid: int) -> bool:
    """Check whether a Windows process with *pid* is still running.

    Uses ``OpenProcess`` + ``GetExitCodeProcess`` via ctypes — no psutil
    dependency required.  On 64-bit Windows the HANDLE return must be
    explicitly typed as ``c_void_p`` to avoid truncation.
    """
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _acquire_lock(lock_path: Path) -> bool:
    """Try to acquire the PID lock file. Returns True if acquired, False if busy."""
    logger = logging.getLogger("news_agent")
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text().strip())
        except (ValueError, OSError):
            _release_lock(lock_path)
        else:
            if _is_pid_alive(pid):
                logger.info("Worker 已在运行 (pid=%d), 跳过本次运行", pid)
                return False
            _release_lock(lock_path)

    lock_path.write_text(str(os.getpid()))
    return True


def _release_lock(lock_path: Path) -> None:
    """Remove the PID lock file. Never raises."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _start_watchdog(timeout_seconds: int = 900) -> threading.Thread:
    """Start a daemon watchdog thread that hard-exits after *timeout_seconds*.

    Uses ``os._exit(1)`` (not ``sys.exit``) because the watchdog runs in a
    daemon thread and must terminate the entire process immediately.
    """

    def _watchdog() -> None:
        time.sleep(timeout_seconds)
        try:
            logger = logging.getLogger("news_agent")
            logger.critical("Watchdog triggered — forcing exit after %d s", timeout_seconds)
        except Exception:
            pass
        os._exit(1)

    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _insert_articles_from_bundle(db_path: Path, bundle: dict) -> int:
    """Insert all articles from a curator bundle into the database.

    Returns the number of newly inserted rows (URL-level dedup via INSERT OR IGNORE).
    """
    conn = get_write_connection(db_path)
    try:
        inserted = 0
        for domain, articles in bundle.get("articles_by_domain", {}).items():
            for article in articles:
                if insert_article(
                    conn,
                    url=article["url"],
                    title=article["title"],
                    summary=article.get("summary"),
                    source=article.get("source_url", article.get("source", "")),
                    domain=article.get("domain", domain),
                    published_at=article.get("published_at"),
                    score=0.0,
                    summary_ai=article.get("ai_summary", ""),
                ):
                    inserted += 1
        return inserted
    finally:
        conn.close()


def _save_latest_state(bundle: dict) -> None:
    """Atomically write the latest bundle JSON for the main process to read."""
    output_path = _resolve_output_path()
    tmp_path = output_path.with_suffix(".json.tmp")

    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)

    os.replace(str(tmp_path), str(output_path))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Worker entry point. Returns process exit code (0 on success, 1 on hard failure).

    Idempotent + safe to invoke any time. Skips silently if another Worker is
    already running.
    """
    setup_logging("worker")
    logger = get_logger()

    lock_path = Path(tempfile.gettempdir()) / "news-agent-worker.lock"

    if not _acquire_lock(lock_path):
        return 0

    _start_watchdog()

    try:
        logger.info("Worker 启动, pid=%d", os.getpid())

        config = load_config()

        # Apply proxy if configured (httpx + openai SDK both respect these env vars)
        if config.proxy:
            os.environ["HTTP_PROXY"] = config.proxy
            os.environ["HTTPS_PROXY"] = config.proxy
            logger.info("Using proxy: %s", config.proxy)

        db_path = _resolve_db_path()
        init_db(db_path)

        bundle = run_curator(config, db_path=db_path)

        inserted = _insert_articles_from_bundle(db_path, bundle)
        logger.info("插入 %d 篇新文章", inserted)

        conn = get_write_connection(db_path)
        try:
            deleted_articles = cleanup_old_articles(conn, days=config.retention_days)
            logger.info("清理 %d 条过旧文章", deleted_articles)

            deleted_convos = cleanup_old_conversations(conn, days=30)
            logger.info("清理 %d 条过旧对话", deleted_convos)
        finally:
            conn.close()

        _save_latest_state(bundle)
        logger.info("Worker 完成, fetched_at=%s", bundle.get("fetched_at", "N/A"))

        return 0

    except Exception:
        logger.exception("Worker 致命错误")
        return 1
    finally:
        _release_lock(lock_path)


if __name__ == "__main__":
    sys.exit(main())
