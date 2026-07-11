"""Task T13: GitHub trending HTML scraper — trending repositories page.

Fetches GitHub trending (default daily, configurable via ``source.url``
for weekly/monthly — e.g. ``https://github.com/trending?since=weekly``),
parses the HTML with BeautifulSoup, and normalises each trending repository
to the same dict shape used by other fetchers so the curator can treat all
outputs uniformly.

GitHub's trending page lists ~24 repositories per range.  We extract repo
name, description, star count, fork count, and primary language from the
structured ``Box-row`` article elements.

Returns ≤ *MAX_ENTRIES* per call.  Never raises — logs warnings on errors
and returns an empty list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from news_agent.config import SourceEntry
from news_agent.logging_setup import get_logger

logger = get_logger()

MAX_ENTRIES = 20
_TRENDING_URL = "https://github.com/trending?since=daily"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html",
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


def _find_stat(soup: BeautifulSoup, path: str) -> str:
    """Find the text of a link whose href contains *path* (e.g. ``/stargazers``).

    Returns empty string when no matching link is found.
    """
    tag = soup.find("a", href=lambda h: h and path in h)
    if tag is None:
        return ""
    text = tag.get_text(strip=True)
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_github_trending(source: SourceEntry) -> list[dict[str, Any]]:
    """Fetch GitHub trending repositories and return normalised dicts.

    Args:
        source: A ``SourceEntry`` whose ``domain`` is used in the output
            entries (typically ``"programming"``).

    Returns:
        Up to ``MAX_ENTRIES`` normalised dicts, each with keys ``url``,
        ``title``, ``summary``, ``domain``, ``source_url``,
        ``published_at``, and ``fetched_at``.  Returns an empty list on any
        error — **never raises**.
    """
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(source.url or _TRENDING_URL, headers=_HEADERS)
        if resp.status_code != 200:
            logger.warning(
                "github_trending returned status %s", resp.status_code
            )
            return []
    except httpx.HTTPError as exc:
        logger.warning("github_trending request error: %s", exc)
        return []

    # Parse HTML
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.warning("github_trending HTML parse error: %s", exc)
        return []

    articles = soup.select("article.Box-row")
    if not articles:
        logger.warning(
            "github_trending: no article.Box-row elements found —"
            " page structure may have changed"
        )
        return []

    entries: list[dict[str, Any]] = []
    fetched_at = _utcnow_iso()

    for article in articles[:MAX_ENTRIES]:
        # Repo name + link: h2 a
        link_tag = article.select_one("h2 a")
        if link_tag is None:
            continue

        href = link_tag.get("href", "")
        if not href:
            continue

        if href.startswith("/"):
            repo_url = f"https://github.com{href}"
        else:
            repo_url = str(href)

        # Title: normalise "owner / repo" → "owner/repo"
        raw_title = link_tag.get_text(strip=True)
        title = " ".join(raw_title.split()).replace(" / ", "/")

        if not title:
            continue

        # Description: first p tag text
        desc_tag = article.select_one("p")
        description = ""
        if desc_tag is not None:
            description = desc_tag.get_text(strip=True)

        # Stars: a.Link--muted with href containing /stargazers
        stars = _find_stat(article, "/stargazers")

        # Language: [itemprop="programmingLanguage"]
        lang_tag = article.select_one('[itemprop="programmingLanguage"]')
        language = ""
        if lang_tag is not None:
            language = lang_tag.get_text(strip=True)

        # Build summary
        summary_parts = []
        if stars:
            summary_parts.append(f"⭐ {stars}")
        if language:
            summary_parts.append(language)
        if description:
            summary_parts.append(description[:100])
        summary = " | ".join(summary_parts)

        entries.append(
            {
                "url": repo_url,
                "title": title,
                "summary": summary,
                "domain": source.domain,
                "source_url": source.url or _TRENDING_URL,
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
        type="html",
        url="https://github.com/trending?since=daily",
        domain="programming",
    )
    items = fetch_github_trending(source)
    print(f"Fetched {len(items)} GitHub trending repos")
    for item in items[:5]:
        print(f"  - {item['title'][:60]}")
        print(f"    {item['summary'][:100]}")
