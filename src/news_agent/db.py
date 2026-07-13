"""Dual-process SQLite layer with WAL + busy_timeout guards.

Provides init_db, connection helpers (write / read-only), and CRUD helpers for
articles, conversations, and daily token usage tracking.

All internal timestamps are stored as UTC ISO 8601 strings with "Z" suffix.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_cutoff(hours: int = 0, days: int = 0) -> str:
    """Return a past UTC timestamp relative to now for string comparison."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours, days=days)
    return dt.isoformat().replace("+00:00", "Z")


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply mandatory PRAGMAs for dual-process safety.

    Order matters: WAL first, then busy_timeout, then foreign_keys.
    """
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")


# ---------------------------------------------------------------------------
# Connection factories
# ---------------------------------------------------------------------------


def get_write_connection(db_path: Path) -> sqlite3.Connection:
    """Open a full read/write SQLite connection (used by Worker).

    Applies WAL, busy_timeout=5000, and foreign_keys=ON PRAGMAs on open.
    Row factory is set to sqlite3.Row for dict-style access.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def get_read_only_connection(db_path: Path) -> sqlite3.Connection:
    """Open a read-only SQLite connection via URI mode (used by main process).

    Uses ``file:{abs-path}?mode=ro`` to prevent accidental writes — critical
    for dual-process safety where the main UI process must never mutate data.
    Row factory is set to sqlite3.Row.
    """
    # Convert Windows backslashes to forward slashes for URI format.
    abs_path = db_path.resolve().as_posix()
    uri = f"file:{abs_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------


def init_db(db_path: Path) -> None:
    """Create database directory, tables, and insert schema_version=1.

    Creates the parent directory if missing, opens a write connection, applies
    PRAGMAs, creates all 4 tables with ``CREATE TABLE IF NOT EXISTS``, and
    inserts ``schema_version(1)`` if the table is empty.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_write_connection(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS articles (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT,
                source TEXT NOT NULL,
                domain TEXT NOT NULL,
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                score REAL DEFAULT 0,
                summary_ai TEXT
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL DEFAULT 'legacy',
                role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_usage (
                date TEXT PRIMARY KEY,
                tokens_used INTEGER NOT NULL DEFAULT 0
            );
            """
        )

        conversation_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(conversations)")
        }
        if "session_id" not in conversation_columns:
            conn.execute(
                "ALTER TABLE conversations ADD COLUMN session_id TEXT NOT NULL DEFAULT 'legacy'"
            )
        now = _utcnow_iso()
        conn.execute(
            """INSERT OR IGNORE INTO conversation_sessions
               (id, title, created_at, updated_at) VALUES ('legacy', '历史对话', ?, ?)""",
            (now, now),
        )

        existing = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()
        if existing[0] == 0:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (1, ?)",
                (_utcnow_iso(),),
            )

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Article helpers
# ---------------------------------------------------------------------------


def insert_article(
    conn: sqlite3.Connection,
    url: str,
    title: str,
    summary: str | None,
    source: str,
    domain: str,
    published_at: str | None,
    score: float = 0.0,
    summary_ai: str | None = None,
) -> bool:
    """Insert an article with INSERT OR IGNORE for URL-level permanent dedup.

    The ``fetched_at`` column is set to the current UTC time automatically.

    Returns:
        ``True`` if the row was inserted (new URL), ``False`` if the URL
        already exists (duplicate).
    """
    cursor = conn.execute(
        """INSERT OR IGNORE INTO articles
           (url, title, summary, source, domain, published_at, fetched_at, score, summary_ai)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (url, title, summary, source, domain, published_at, _utcnow_iso(), score, summary_ai),
    )
    return cursor.rowcount > 0


def get_recent_articles(
    conn: sqlite3.Connection,
    domain: str | None = None,
    hours: int = 24,
    limit: int = 50,
) -> list[dict]:
    """Return recent articles, newest first. Optional domain filter.

    Args:
        domain: If provided, only return articles from this domain.
        hours: Look-back window in hours (based on ``fetched_at``).
        limit: Maximum number of articles to return.
    """
    cutoff = _utc_cutoff(hours=hours)
    if domain is not None:
        rows = conn.execute(
            """SELECT * FROM articles
               WHERE domain = ? AND fetched_at >= ?
               ORDER BY fetched_at DESC
               LIMIT ?""",
            (domain, cutoff, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM articles
               WHERE fetched_at >= ?
               ORDER BY fetched_at DESC
               LIMIT ?""",
            (cutoff, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Conversation helpers
# ---------------------------------------------------------------------------


def insert_conversation(
    conn: sqlite3.Connection, role: str, content: str, session_id: str = "legacy"
) -> int:
    """Insert a conversation message and return its auto-generated id."""
    cursor = conn.execute(
        "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, _utcnow_iso()),
    )
    conn.execute(
        "UPDATE conversation_sessions SET updated_at = ? WHERE id = ?",
        (_utcnow_iso(), session_id),
    )
    return cursor.lastrowid


def get_recent_conversations(
    conn: sqlite3.Connection, limit: int = 50, session_id: str | None = None
) -> list[dict]:
    """Return recent conversation messages, newest first."""
    if session_id is None:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def create_conversation_session(conn: sqlite3.Connection, title: str = "新对话") -> dict:
    """Create and return an independent saved conversation session."""
    session_id = uuid.uuid4().hex
    now = _utcnow_iso()
    conn.execute(
        "INSERT INTO conversation_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, title, now, now),
    )
    return {"id": session_id, "title": title, "created_at": now, "updated_at": now}


def list_conversation_sessions(conn: sqlite3.Connection) -> list[dict]:
    """Return saved conversations with their latest-message preview."""
    rows = conn.execute(
        """SELECT s.id, s.title, s.created_at, s.updated_at,
                  COUNT(c.id) AS message_count,
                  (SELECT content FROM conversations x WHERE x.session_id = s.id
                   ORDER BY x.created_at DESC, x.id DESC LIMIT 1) AS preview
           FROM conversation_sessions s
           LEFT JOIN conversations c ON c.session_id = s.id
           GROUP BY s.id
           ORDER BY s.updated_at DESC, s.created_at DESC"""
    ).fetchall()
    return [dict(row) for row in rows]


def conversation_session_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM conversation_sessions WHERE id = ?", (session_id,)
    ).fetchone() is not None


def update_conversation_session_title(
    conn: sqlite3.Connection, session_id: str, title: str
) -> None:
    conn.execute(
        "UPDATE conversation_sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title, _utcnow_iso(), session_id),
    )


def truncate_older_than_days(
    conn: sqlite3.Connection, days: int = 30, session_id: str | None = None
) -> int:
    """Delete conversation messages older than *days*.

    Can be paired with a ``[已省略早期对话]`` marker inserted by the caller
    for context truncation.

    Returns:
        Number of rows deleted.
    """
    cutoff = _utc_cutoff(days=days)
    if session_id is None:
        cursor = conn.execute("DELETE FROM conversations WHERE created_at < ?", (cutoff,))
    else:
        cursor = conn.execute(
            "DELETE FROM conversations WHERE session_id = ? AND created_at < ?",
            (session_id, cutoff),
        )
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Daily token usage helpers
# ---------------------------------------------------------------------------


def add_token_usage(conn: sqlite3.Connection, tokens: int) -> None:
    """Add *tokens* to today's daily_usage row via UPSERT.

    Uses ``ON CONFLICT(date) DO UPDATE`` so the first call each day inserts
    and subsequent calls accumulate.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO daily_usage (date, tokens_used) VALUES (?, ?)
           ON CONFLICT(date) DO UPDATE SET tokens_used = tokens_used + ?""",
        (today, tokens, tokens),
    )


def get_today_token_usage(conn: sqlite3.Connection) -> int:
    """Return today's cumulative token usage, or 0 if no row exists yet."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT tokens_used FROM daily_usage WHERE date = ?", (today,)
    ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def cleanup_old_articles(conn: sqlite3.Connection, days: int = 30) -> int:
    """Delete articles whose ``fetched_at`` is older than *days*.

    Returns:
        Number of rows deleted.
    """
    cutoff = _utc_cutoff(days=days)
    cursor = conn.execute("DELETE FROM articles WHERE fetched_at < ?", (cutoff,))
    return cursor.rowcount


def cleanup_old_conversations(conn: sqlite3.Connection, days: int = 30) -> int:
    """Delete conversations whose ``created_at`` is older than *days*.

    Returns:
        Number of rows deleted.
    """
    return truncate_older_than_days(conn, days)


# ---------------------------------------------------------------------------
# Ad-hoc testing entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db_path = Path("data/state.db")
    init_db(db_path)
    print(f"DB initialized at {db_path.resolve()}")
