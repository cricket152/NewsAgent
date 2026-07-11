"""Task T11: Bangumi API v0 fetcher — anime/manga metadata for 百合 / GL domain.

Queries the free `api.bgm.tv <https://api.bgm.tv>`_ ``/v0/subjects`` endpoint
by tag (e.g. ``百合``, ``GL``) and normalises each subject to the same dict
shape used by the RSS / RSSHub / HTML fetchers so the curator can treat all
outputs uniformly.

Bangumi API requirements (mandatory):
  - ``User-Agent: news-agent/0.1 (https://github.com/ local)``
  - ``Accept: application/json``

Returns ≤ *MAX_ENTRIES* per call, sorted by ``date`` (newest first).  Never
raises — logs warnings on errors and returns an empty list.

Reference: ``https://github.com/bangumi/api/blob/master/docs-raw/Common_Headers.md``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from news_agent.config import SourceEntry
from news_agent.logging_setup import get_logger

logger = get_logger()

MAX_ENTRIES = 20

_DEFAULT_BASE_URL = "https://api.bgm.tv"
_USER_AGENT = "news-agent/0.1 (https://github.com/ local)"


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


def _parse_bangumi_date(date_str: str) -> str:
    """Parse ``"YYYY-MM-DD"`` (or ``"YYYY-MM"``, ``"YYYY"``) → ISO 8601 UTC ``Z``.

    Returns ``""`` when *date_str* is falsy or cannot be parsed.
    """
    if not date_str:
        return ""
    try:
        parts = date_str.strip().split("-")
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        dt = datetime(year, month, day, tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, IndexError):
        return ""


def _resolve_base_url(source_url: str) -> str:
    """Extract ``scheme://netloc`` from *source_url*; fall back to default.

    A config may store the full Bangumi URL (e.g.
    ``https://api.bgm.tv/v0/subjects?type=2&tag=百合``).  The fetcher only
    needs the scheme + host to construct its own endpoint, so we strip
    everything else.
    """
    if not source_url:
        return _DEFAULT_BASE_URL
    try:
        parsed = urlparse(source_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    return _DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_bangumi(source: SourceEntry) -> list[dict[str, Any]]:
    """Fetch Bangumi subjects by tag and return normalised dicts.

    Args:
        source: A ``SourceEntry`` whose ``url`` points to the Bangumi API
            base (e.g. ``https://api.bgm.tv``).  ``source.params`` may
            hold per-source overrides:

            - ``tag``   (``str``,  default ``"百合"``)
            - ``type``  (``int``,  default ``2`` — anime; 1=book, 3=music,
              4=game, 6=real)
            - ``limit`` (``int``,  default ``20``, max 50 per Bangumi API)
            - ``sort``  (``str``,  default ``"date"`` — newest first)

    Returns:
        Up to ``MAX_ENTRIES`` normalised dicts (newest first), each with
        keys ``url``, ``title``, ``summary``, ``domain``, ``source_url``,
        ``published_at``, and ``fetched_at``.  Returns an empty list on any
        error — **never raises**.
    """
    params = source.params or {}
    tag = params.get("tag", "百合")
    subject_type = int(params.get("type", 2))
    limit = min(int(params.get("limit", 20)), 50)
    sort = params.get("sort", "date")

    base_url = _resolve_base_url(source.url)
    api_url = f"{base_url.rstrip('/')}/v0/subjects"

    query_params: dict[str, Any] = {
        "type": subject_type,
        "tag": tag,
        "limit": limit,
        "sort": sort,
    }

    # 1. HTTP GET via httpx (respects Bangumi's mandatory UA + Accept headers)
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                api_url,
                params=query_params,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "application/json",
                },
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "bangumi %s returned %s", api_url, exc.response.status_code
        )
        return []
    except httpx.HTTPError as exc:
        logger.warning("bangumi %s returned error: %s", api_url, exc)
        return []

    # 2. Parse JSON body
    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning("bangumi %s JSON parse error: %s", api_url, exc)
        return []

    subjects = data.get("data", [])
    if not isinstance(subjects, list):
        logger.warning(
            "bangumi %s returned unexpected shape (data is %s, not list)",
            api_url,
            type(subjects).__name__,
        )
        return []

    # 3. Normalise each subject → curator-ready dict
    entries: list[dict[str, Any]] = []
    fetched_at = _utcnow_iso()
    # The URL actually queried (with httpx-resolved query string)
    source_url = str(resp.url)

    for item in subjects:
        if not isinstance(item, dict):
            continue

        subject_id = item.get("id")
        if subject_id is None:
            continue

        # title: prefer Chinese name (name_cn), fall back to Japanese (name)
        title = item.get("name_cn") or item.get("name") or ""
        if not title:
            continue

        # summary: prefer short_summary, fall back to full summary; cap at 500
        summary_raw = item.get("summary") or ""
        short = item.get("short_summary")
        if short:
            summary_raw = short
        summary = str(summary_raw)[:500]

        published_at = _parse_bangumi_date(item.get("date", ""))

        entries.append(
            {
                "url": f"https://bgm.tv/subject/{subject_id}",
                "title": title,
                "summary": summary,
                "domain": source.domain,
                "source_url": source_url,
                "published_at": published_at,
                "fetched_at": fetched_at,
            }
        )

        if len(entries) >= MAX_ENTRIES:
            break

    # Sort newest first; empty published_at values sort last
    entries.sort(key=lambda e: e["published_at"] or "", reverse=True)

    return entries[:MAX_ENTRIES]


# ---------------------------------------------------------------------------
# Ad-hoc smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    source = SourceEntry(
        type="api",
        url="https://api.bgm.tv",
        domain="yuri_gl",
        params={"tag": "百合", "type": 2, "limit": 5, "sort": "date"},
    )
    items = fetch_bangumi(source)
    print(f"Fetched {len(items)} items (百合 tag, anime)")
    for item in items[:5]:
        print(f"  - {item['title'][:60]}")
        print(f"    {item['url']}")
