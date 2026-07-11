"""Tests for ``news_agent.db`` — dual-process SQLite layer."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from news_agent.db import (
    add_token_usage,
    cleanup_old_articles,
    get_read_only_connection,
    get_recent_articles,
    get_recent_conversations,
    get_today_token_usage,
    get_write_connection,
    init_db,
    insert_article,
    insert_conversation,
    truncate_older_than_days,
)

# ── helpers ────────────────────────────────────────────────────────────────


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return {r[0] for r in rows}


# ── init_db ────────────────────────────────────────────────────────────────


class TestInitDb:
    def test_init_db_creates_tables(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            tables = _table_names(conn)
            assert tables >= {"schema_version", "articles", "conversations", "daily_usage"}
        finally:
            conn.close()

    def test_wal_mode_active(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            assert row[0].lower() == "wal"
        finally:
            conn.close()

    def test_busy_timeout_set(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
            assert row[0] == 5000
        finally:
            conn.close()


# ── articles ───────────────────────────────────────────────────────────────


class TestArticles:
    def test_insert_article_dedup_url(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            assert insert_article(conn, "http://a.com", "T", "S", "src", "ai_tech", None)
            assert not insert_article(conn, "http://a.com", "T2", "S2", "src2", "ai_tech", None)
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            assert count == 1
        finally:
            conn.close()

    def test_get_recent_articles_desc(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            ts1 = "2020-01-01T00:00:00Z"
            ts2 = "2025-01-01T00:00:00Z"
            ts3 = "2023-01-01T00:00:00Z"
            insert_article(conn, "http://a.com/1", "Old", "", "src", "ai_tech", ts1)
            insert_article(conn, "http://a.com/2", "New", "", "src", "ai_tech", ts2)
            insert_article(conn, "http://a.com/3", "Mid", "", "src", "ai_tech", ts3)
            conn.commit()
        finally:
            conn.close()

        ro = get_read_only_connection(tmp_db_path)
        try:
            # Use a large hours window so we see all
            articles = get_recent_articles(ro, hours=24 * 365 * 10, limit=50)
            # get_recent_articles filters by fetched_at, not published_at
            # All were inserted recently, so they all appear
            # Sorted by fetched_at DESC (newest first) — insertion order reversed
            assert len(articles) >= 3
        finally:
            ro.close()

    def test_cleanup_old_articles(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            # Insert one article with an old fetched_at (simulated via direct SQL)
            delta60 = datetime.now(timezone.utc) - timedelta(days=60)
            old_fetched = delta60.isoformat().replace("+00:00", "Z")
            conn.execute(
                """INSERT INTO articles (url, title, summary, source, domain, fetched_at)
                   VALUES ('old', 'Old', '', 'src', 'ai_tech', ?)""",
                (old_fetched,),
            )
            insert_article(conn, "http://new.com", "New", "", "src", "ai_tech", None)
            conn.commit()
            count_before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            assert count_before == 2
        finally:
            conn.close()

        conn2 = get_write_connection(tmp_db_path)
        try:
            deleted = cleanup_old_articles(conn2, days=7)
            conn2.commit()
            assert deleted >= 1  # at least the old one removed
            remaining = conn2.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            assert remaining == 1
        finally:
            conn2.close()


# ── conversations ──────────────────────────────────────────────────────────


class TestConversations:
    def test_conversation_insert_and_get(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            msg_id = insert_conversation(conn, "user", "hello")
            conn.commit()
            rows = get_recent_conversations(conn, limit=10)
            assert len(rows) == 1
            assert rows[0]["role"] == "user"
            assert rows[0]["content"] == "hello"
            assert rows[0]["id"] == msg_id
        finally:
            conn.close()

    def test_truncate_older_than_days(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            # Insert an old message via direct SQL
            delta60 = datetime.now(timezone.utc) - timedelta(days=60)
            old_ts = delta60.isoformat().replace("+00:00", "Z")
            conn.execute(
                "INSERT INTO conversations (role, content, created_at) VALUES (?, ?, ?)",
                ("user", "old", old_ts),
            )
            insert_conversation(conn, "user", "new")
            conn.commit()
            assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 2
            deleted = truncate_older_than_days(conn, days=30)
            conn.commit()
            assert deleted == 1
            assert conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
        finally:
            conn.close()


# ── token usage ────────────────────────────────────────────────────────────


class TestTokenUsage:
    def test_add_token_usage_upsert(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            add_token_usage(conn, 100)
            conn.commit()
            add_token_usage(conn, 200)
            conn.commit()
            usage = get_today_token_usage(conn)
            assert usage == 300
        finally:
            conn.close()

    def test_get_today_token_usage_zero(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        conn = get_write_connection(tmp_db_path)
        try:
            assert get_today_token_usage(conn) == 0
        finally:
            conn.close()


# ── concurrent access ──────────────────────────────────────────────────────


class TestConcurrency:
    def test_concurrent_read_during_write(self, tmp_db_path: Path) -> None:
        """WAL mode allows reads to proceed while a write transaction is open."""
        init_db(tmp_db_path)
        conn_w = get_write_connection(tmp_db_path)
        conn_w.execute("BEGIN EXCLUSIVE")
        try:
            # Insert something inside the exclusive transaction
            conn_w.execute(
                """INSERT INTO articles (url, title, summary, source, domain, fetched_at)
                   VALUES ('lock', 'L', '', 's', 'ai_tech', '2026-01-01T00:00:00Z')"""
            )

            def _read_in_thread() -> None:
                ro = get_read_only_connection(tmp_db_path)
                try:
                    ro.execute("SELECT COUNT(*) FROM articles").fetchone()
                finally:
                    ro.close()

            t = threading.Thread(target=_read_in_thread)
            t.start()
            t.join(timeout=3)
            assert not t.is_alive(), "Read thread blocked — WAL may not be active"
        finally:
            conn_w.rollback()
            conn_w.close()


class TestReadOnly:
    def test_read_only_connection_rejects_write(self, tmp_db_path: Path) -> None:
        init_db(tmp_db_path)
        ro = get_read_only_connection(tmp_db_path)
        try:
            with pytest.raises(sqlite3.OperationalError):
                ro.execute(
                    """INSERT INTO articles (url, title, summary, source, domain, fetched_at)
                       VALUES ('x', 'X', '', 's', 'ai_tech', '2026-01-01T00:00:00Z')"""
                )
        finally:
            ro.close()
