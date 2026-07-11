"""Task T9: RSSHub route fetcher via httpx + feedparser — Bilibili, Weibo, NGA.

Builds an RSSHub URL from ``rsshub_url + source.url``, fetches the RSS 2.0
XML, and normalises entries to the same dict shape as ``fetch_rss`` (T8) so
the curator can treat all fetcher outputs uniformly.

Returns ≤ MAX_ENTRIES per call.  Never raises — logs warnings on errors and
returns an empty list.
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
_USER_AGENT = "news-agent/0.1 (+https://github.com/local)"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 with ``Z`` suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_published(entry: feedparser.FeedParserDict) -> str:
    """Parse ``entry.published_parsed`` (struct_time) → ISO 8601 UTC ``Z``.

    Returns empty string when ``published_parsed`` is missing.
    """
    parsed = entry.get("published_parsed")
    if parsed is None:
        return ""
    try:
        dt = datetime(*parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_rsshub(
    source: SourceEntry,
    rsshub_url: str = "http://localhost:1200",
) -> list[dict[str, Any]]:
    """Fetch an RSSHub route and return normalised article dicts.

    Args:
        source: A ``SourceEntry`` whose ``url`` is an RSSHub route path
            (e.g. ``/bilibili/partition/24``).
        rsshub_url: Base URL of the RSSHub instance (defaults to
            ``http://localhost:1200``).  The Worker passes ``config.rsshub_url``.

    Returns:
        Up to ``MAX_ENTRIES`` normalised dicts (newest first), each with keys
        ``url``, ``title``, ``summary``, ``domain``, ``source_url``,
        ``published_at``, and ``fetched_at``.  Returns an empty list on any
        error — **never raises**.
    """
    full_url = rsshub_url.rstrip("/") + source.url

    # 1. HTTP GET via httpx
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(full_url, headers={"User-Agent": _USER_AGENT})
        if resp.status_code != 200:
            logger.warning(
                "rsshub %s returned status %s", full_url, resp.status_code
            )
            return []
    except httpx.HTTPError as exc:
        logger.warning("rsshub %s returned error: %s", full_url, exc)
        return []

    # 2. Parse RSS XML via feedparser
    feed = feedparser.parse(resp.content)
    if feed.bozo and feed.bozo_exception is not None:
        logger.warning(
            "rsshub %s parse error: %s", full_url, feed.bozo_exception
        )
        return []

    # 3. Normalize entries to the standard dict shape
    entries: list[dict[str, Any]] = []
    for entry in feed.entries:
        link = entry.get("link", "")
        title = entry.get("title", "")

        if not link or not title:
            logger.debug(
                "rsshub %s: skipping entry with empty link or title",
                full_url,
            )
            continue

        summary_raw = entry.get("summary", "") or ""
        summary = summary_raw[:500]

        entries.append(
            {
                "url": link,
                "title": title,
                "summary": summary,
                "domain": source.domain,
                "source_url": full_url,
                "published_at": _parse_published(entry),
                "fetched_at": _utcnow_iso(),
            }
        )

    entries.sort(key=lambda e: e["published_at"] or "", reverse=True)
    return entries[:MAX_ENTRIES]


# ---------------------------------------------------------------------------
# Ad-hoc smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Try localhost first; if unreachable, use a public RSSHub instance
    for rsshub_url in ("http://localhost:1200", "https://rsshub.app"):
        try:
            with httpx.Client(timeout=5) as client:
                client.get(rsshub_url, headers={"User-Agent": _USER_AGENT})
            break
        except httpx.HTTPError:
            rsshub_url = ""
    else:
        rsshub_url = ""

    if not rsshub_url:
        print("No RSSHub instance reachable — skipping smoke test")
    else:
        source = SourceEntry(
            type="rsshub",
            url="/36kr/motif",
            domain="ai_tech",
        )
        items = fetch_rsshub(source, rsshub_url=rsshub_url)
        print(f"Fetched {len(items)} items from {rsshub_url}/36kr/motif")
        for item in items[:3]:
            print(f"  - {item['title'][:80]}")
