"""MediaWiki API fetcher — fetches recent changes from a MediaWiki wiki (e.g. PRTS).

Calls the ``api.php`` endpoint with ``action=query&list=recentchanges`` and
normalises the JSON response to the standard article dict shape.

PRTS Wiki uses a JavaScript-based anti-bot challenge ("Sisyphus") that blocks
both RSS feeds and HTML scraping.  The ``api.php`` endpoint is not behind this
challenge and returns clean JSON, making it the reliable way to track wiki
activity.

Returns <= MAX_ENTRIES per call.  Never raises — logs warnings on errors and
returns an empty list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
    """Return current UTC time as ISO 8601 with ``Z`` suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _build_api_url(source: SourceEntry) -> str:
    """Ensure the source URL has the required MediaWiki API parameters.

    If the URL already contains ``action=query``, pass it through as-is.
    Otherwise, append the default recent-changes query parameters.
    """
    url = source.url
    if "action=query" in url:
        return url
    # Default: recent changes in main namespace, JSON format
    separator = "&" if "?" in url else "?"
    return (
        f"{url}{separator}action=query&list=recentchanges"
        "&rclimit=20&rcnamespace=0&format=json"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_mediawiki_recent(source: SourceEntry) -> list[dict[str, Any]]:
    """Fetch recent changes from a MediaWiki API endpoint.

    Args:
        source: A :class:`SourceEntry` with ``type="mediawiki_api"``.
            The ``url`` should point to the wiki's ``api.php`` endpoint.
            ``source.params`` may override ``rclimit``.

    Returns:
        List of normalised article dicts (<= ``MAX_ENTRIES`` items).
        Each dict has: url, title, summary, domain, source_url,
        published_at, fetched_at.
    """
    api_url = _build_api_url(source)
    limit = int(source.params.get("rclimit", MAX_ENTRIES))

    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        ) as client:
            resp = client.get(api_url)
            resp.raise_for_status()
            data = resp.json()

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "mediawiki API returned HTTP %s for %s",
            exc.response.status_code,
            source.url,
        )
        return []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("mediawiki API fetch failed for %s: %s", source.url, exc)
        return []

    changes = data.get("query", {}).get("recentchanges", [])
    if not changes:
        logger.warning("mediawiki API returned 0 recent changes from %s", source.url)
        return []

    # Deduplicate by title (MediaWiki may return multiple edits to same page)
    seen_titles: set[str] = set()
    items: list[dict[str, Any]] = []

    for rc in changes[:limit]:
        title = rc.get("title", "")
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)

        pageid = rc.get("pageid", "")
        timestamp = rc.get("timestamp", "")
        # timestamp from MediaWiki is already ISO 8601 with Z suffix

        items.append(
            {
                "url": f"https://prts.wiki/?curid={pageid}" if pageid else source.url,
                "title": title,
                "summary": "",  # recent changes API has no summary
                "domain": source.domain,
                "source_url": source.url,
                "published_at": timestamp,
                "fetched_at": _utcnow_iso(),
            }
        )

    return items


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from news_agent.config import SourceEntry

    test_source = SourceEntry(
        type="mediawiki_api",
        url="https://prts.wiki/api.php",
        domain="arknights",
    )
    results = fetch_mediawiki_recent(test_source)
    print(f"Fetched {len(results)} items from PRTS Wiki")
    for item in results[:3]:
        print(f"  - {item['title']} ({item['url']}) @ {item['published_at']}")
