"""Task T8: RSS feed fetcher via feedparser — HN, GitHub trending, dmhy.

Normalises RSS 2.0 and Atom feeds to a standard dict format ready for
curation. Returns ≤ MAX_ENTRIES per call, newest first. Never raises —
logs warnings on errors and returns an empty list.

Uses httpx to fetch the feed content first (avoids feedparser/urllib SSL
issues on Windows), then passes the raw XML to feedparser for parsing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from news_agent.config import SourceEntry
from news_agent.logging_setup import get_logger

logger = get_logger()

MAX_ENTRIES = 20
_FETCH_TIMEOUT = 15
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 with Z suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_published(entry: feedparser.FeedParserDict) -> str:
    """Parse ``entry.published_parsed`` (struct_time) → ISO 8601 UTC with ``Z``.

    Returns empty string when ``published_parsed`` is missing or its value
    cannot be converted to a valid datetime.
    """
    parsed = entry.get("published_parsed")
    if parsed is None:
        return ""
    try:
        # struct_time from feedparser is always normalised to UTC
        dt = datetime(*parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_rss(source: SourceEntry) -> list[dict[str, Any]]:
    """Fetch an RSS/Atom feed and return normalised article dicts.

    Args:
        source: A ``SourceEntry`` whose ``url`` points to a valid RSS 2.0 or
            Atom feed.

    Returns:
        Up to ``MAX_ENTRIES`` normalised dicts (newest first), each with keys
        ``url``, ``title``, ``summary``, ``domain``, ``source_url``,
        ``published_at``, and ``fetched_at``.  Returns an empty list on any
        error (network, parse, timeout) — **never raises**.
    """
    try:
        # Use httpx to fetch the raw feed content first, avoiding
        # feedparser/urllib SSL issues on Windows (UNEXPECTED_EOF_WHILE_READING).
        with httpx.Client(
            timeout=_FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = client.get(source.url)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
    except Exception as exc:
        logger.warning("rss feed %s returned error: %s", source.url, exc)
        return []

    # feedparser signals network / parse errors via bozo + bozo_exception
    # instead of raising — treat these identically to exceptions.
    if feed.bozo and feed.bozo_exception is not None:
        logger.warning(
            "rss feed %s returned error: %s", source.url, feed.bozo_exception
        )
        return []

    entries: list[dict[str, Any]] = []
    for entry in feed.entries:
        link = entry.get("link", "")
        title = entry.get("title", "")

        if not link or not title:
            logger.debug(
                "rss feed %s: skipping entry with empty link or title",
                source.url,
            )
            continue

        # Truncate summary to 500 chars to control downstream LLM token cost
        summary_raw = entry.get("summary", "") or ""
        summary = summary_raw[:500]

        entries.append(
            {
                "url": link,
                "title": title,
                "summary": summary,
                "domain": source.domain,
                "source_url": source.url,
                "published_at": _parse_published(entry),
                "fetched_at": _utcnow_iso(),
            }
        )

    # Sort newest first by published_at; empty strings sort last
    entries.sort(key=lambda e: e["published_at"] or "", reverse=True)

    return entries[:MAX_ENTRIES]


# ---------------------------------------------------------------------------
# Ad-hoc smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    source = SourceEntry(
        type="rss",
        url="https://hnrss.org/frontpage",
        domain="ai_tech",
    )
    items = fetch_rss(source)
    print(f"Fetched {len(items)} items from HN frontpage")
    for item in items[:3]:
        print(f"  - {item['title'][:80]}")
