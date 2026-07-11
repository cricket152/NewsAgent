"""Task T12: Bilibili hot-search fetcher — 热搜榜 via public JSON API.

Queries ``api.bilibili.com/x/web-interface/search/square`` to get the
current trending keywords and normalises each entry to the same dict shape
used by other fetchers so the curator can treat all outputs uniformly.

Bilibili blocks requests without proper browser headers (User-Agent,
Referer, Accept), so we set them unconditionally.

Returns ≤ *MAX_ENTRIES* per call.  Never raises — logs warnings on errors
and returns an empty list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from news_agent.config import SourceEntry
from news_agent.logging_setup import get_logger

logger = get_logger()

MAX_ENTRIES = 10
_API_URL = "https://api.bilibili.com/x/web-interface/search/square?limit=10"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
    "Accept": "application/json",
}


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


def _format_heat(score: int) -> str:
    """Format a Bilibili heat score to human-readable Chinese text.

    Examples:
        32922574 → ``"3292万"``
        500000   → ``"50万"``
        8500     → ``"8500"``
    """
    if score >= 10000:
        return f"{score / 10000:.0f}万"
    return str(score)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_bilibili_hot(source: SourceEntry) -> list[dict[str, Any]]:
    """Fetch Bilibili hot search keywords and return normalised dicts.

    Args:
        source: A ``SourceEntry`` whose ``domain`` is used in the output
            entries.  The API URL is fixed — *source.url* is not used
            directly (the fetcher always queries the hot-search endpoint).

    Returns:
        Up to ``MAX_ENTRIES`` normalised dicts, each with keys ``url``,
        ``title``, ``summary``, ``domain``, ``source_url``,
        ``published_at``, and ``fetched_at``.  Returns an empty list on any
        error — **never raises**.
    """
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(_API_URL, headers=_HEADERS)
        if resp.status_code != 200:
            logger.warning(
                "bilibili_hot returned status %s", resp.status_code
            )
            return []
    except httpx.HTTPError as exc:
        logger.warning("bilibili_hot request error: %s", exc)
        return []

    # Parse JSON body
    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning("bilibili_hot JSON parse error: %s", exc)
        return []

    code = data.get("code")
    if code != 0:
        logger.warning(
            "bilibili_hot API returned code=%s (expected 0)", code
        )
        return []

    trending = data.get("data", {}).get("trending")
    if not isinstance(trending, dict):
        logger.warning(
            "bilibili_hot response missing data.trending (got %s)",
            type(trending).__name__,
        )
        return []

    items = trending.get("list")
    if not isinstance(items, list):
        logger.warning(
            "bilibili_hot response missing data.trending.list (got %s)",
            type(items).__name__,
        )
        return []

    # Normalise each keyword to the standard dict shape
    entries: list[dict[str, Any]] = []
    fetched_at = _utcnow_iso()
    source_url = str(resp.url)

    for item in items[:MAX_ENTRIES]:
        if not isinstance(item, dict):
            continue

        keyword = item.get("keyword")
        if not keyword:
            continue

        show_name = item.get("show_name") or keyword
        heat_score = item.get("heat_score", 0)
        if isinstance(heat_score, (int, float)):
            heat_score = int(heat_score)
        else:
            heat_score = 0

        url = f"https://search.bilibili.com/all?keyword={quote(str(keyword))}"

        entries.append(
            {
                "url": url,
                "title": str(show_name),
                "summary": f"🔥 热度: {_format_heat(heat_score)}",
                "domain": source.domain,
                "source_url": source_url,
                "published_at": "",
                "fetched_at": fetched_at,
            }
        )

    return entries


# ---------------------------------------------------------------------------
# Ad-hoc smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    source = SourceEntry(
        type="api",
        url="https://api.bilibili.com",
        domain="bilibili_hot",
    )
    items = fetch_bilibili_hot(source)
    print(f"Fetched {len(items)} Bilibili hot search items")
    for item in items[:5]:
        print(f"  - {item['title'][:60]}")
        print(f"    {item['summary']}")
