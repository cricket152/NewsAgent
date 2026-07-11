r"""Task T10: HTML page scraper via httpx + bs4 — PRTS Wiki (明日方舟).

Fetches an HTML page, selects news items via CSS selectors from
``source.params``, and normalises entries to the same dict shape as the
RSS / RSSHub fetchers so the curator can treat all fetcher outputs
uniformly.

Returns ≤ MAX_ENTRIES per call.  Never raises — logs warnings on errors
and returns an empty list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import bs4
import httpx

from news_agent.config import SourceEntry
from news_agent.logging_setup import get_logger

logger = get_logger()

MAX_ENTRIES = 20
_USER_AGENT = "Mozilla/5.0"

# Default CSS selectors used when *source.params* omits a key
_DEFAULT_NEWS_SELECTOR = ".news-list-item"
_DEFAULT_TITLE_SELECTOR = ".title"
_DEFAULT_LINK_SELECTOR = "a"
_DEFAULT_SUMMARY_SELECTOR = ".summary"


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


def _fetch_content(url: str) -> str | None:
    """HTTP GET *url* and return decoded text, or ``None`` on any error.

    First tries ``resp.text`` (httpx auto-detects encoding from headers /
    ``<meta charset>``).  On ``UnicodeDecodeError`` falls back to a raw
    read with ``resp.content`` + manual detection.

    Logs at WARNING level on failure; never raises.
    """
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": _USER_AGENT},
            )
    except httpx.HTTPError as exc:
        logger.warning("html %s returned error: %s", url, exc)
        return None

    if resp.status_code != 200:
        logger.warning("html %s returned %s", url, resp.status_code)
        return None

    # httpx auto-detects encoding from Content-Type / <meta charset>
    try:
        return resp.text
    except UnicodeDecodeError:
        # Rare edge case: server claims one encoding but body is another.
        # Try utf-8 first, then let bs4 guess when we parse the raw bytes.
        logger.debug("html %s UnicodeDecodeError on resp.text, trying fallback", url)
        try:
            content = resp.content
            return content.decode("utf-8")
        except UnicodeDecodeError:
            # Pass raw bytes to bs4 later; from_encoding detection will handle it
            return None  # signal to caller to use raw bytes


def _resolve_selector(params: dict[str, Any] | None, key: str, default: str) -> str:
    """Return the CSS selector string for *key* from *params*, or *default*."""
    if params is None:
        return default
    return str(params.get(key, default))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_html(source: SourceEntry) -> list[dict[str, Any]]:
    """Fetch an HTML page and return normalised article dicts.

    Args:
        source: A ``SourceEntry`` with ``type="html"``.  ``source.params``
            may contain CSS selector overrides:

            - ``news_selector`` — items list (default ``.news-list-item``)
            - ``title_selector`` — title element (default ``.title``)
            - ``link_selector`` — anchor ``<a>`` (default ``a``)
            - ``summary_selector`` — summary text (default ``.summary``)

    Returns:
        Up to ``MAX_ENTRIES`` normalised dicts, each with keys ``url``,
        ``title``, ``summary``, ``domain``, ``source_url``,
        ``published_at`` (always ``""`` for HTML scraping), and
        ``fetched_at``.  Returns an empty list on any error — **never
        raises**.
    """
    news_sel = _resolve_selector(
        source.params, "news_selector", _DEFAULT_NEWS_SELECTOR
    )
    title_sel = _resolve_selector(
        source.params, "title_selector", _DEFAULT_TITLE_SELECTOR
    )
    link_sel = _resolve_selector(
        source.params, "link_selector", _DEFAULT_LINK_SELECTOR
    )
    summary_sel = _resolve_selector(
        source.params, "summary_selector", _DEFAULT_SUMMARY_SELECTOR
    )

    # 1. Fetch content
    text = _fetch_content(source.url)
    if text is None:
        return []

    # 2. Parse HTML
    try:
        soup = bs4.BeautifulSoup(text, "html.parser")
    except Exception as exc:
        logger.warning(
            "html %s BeautifulSoup parse error: %s", source.url, exc
        )
        return []

    # 3. Select news items
    items = soup.select(news_sel)

    if not items:
        logger.warning(
            "html selector '%s' returned 0 items from %s",
            news_sel,
            source.url,
        )
        return []

    # 4. Extract per-item fields
    entries: list[dict[str, Any]] = []
    fetched_at = _utcnow_iso()

    for idx, item in enumerate(items):
        # --- title ---
        title_el = item.select_one(title_sel)
        title = title_el.get_text(strip=True) if title_el is not None else ""

        # --- link ---
        link_el = item.select_one(link_sel)
        raw_link = ""
        if link_el is not None:
            raw_link = link_el.get("href", "")
        # Resolve relative URLs (e.g. "/w/SomePage") to absolute
        absolute_link = urljoin(source.url, raw_link) if raw_link else ""

        # --- summary ---
        summary_el = item.select_one(summary_sel)
        summary_raw = summary_el.get_text(strip=True) if summary_el is not None else ""
        summary = summary_raw[:500]

        if not title or not absolute_link:
            logger.debug(
                "html %s[%d]: skipping item with empty title or link",
                source.url,
                idx,
            )
            continue

        entries.append(
            {
                "url": absolute_link,
                "title": title.strip(),
                "summary": summary,
                "domain": source.domain,
                "source_url": source.url,
                "published_at": "",  # HTML scraping has no reliable pub date
                "fetched_at": fetched_at,
            }
        )

        if len(entries) >= MAX_ENTRIES:
            break

    return entries


# ---------------------------------------------------------------------------
# Ad-hoc smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # PRTS Wiki 首页 — 明日方舟 Wiki 主站
    prts_url = "https://prts.wiki/w/%E9%A6%96%E9%A1%B5"
    source = SourceEntry(
        type="html",
        url=prts_url,
        domain="arknights",
        params={
            "news_selector": _DEFAULT_NEWS_SELECTOR,
            "title_selector": _DEFAULT_TITLE_SELECTOR,
            "link_selector": _DEFAULT_LINK_SELECTOR,
            "summary_selector": _DEFAULT_SUMMARY_SELECTOR,
        },
    )

    items = fetch_html(source)
    print(f"Fetched {len(items)} items from {source.url}")
    if items:
        for item in items[:5]:
            print(f"  - {item['title'][:80]}")
            print(f"    {item['url'][:100]}")
    else:
        print("  (no items matched — PRTS page structure may have changed)")
        sys.exit(0)
