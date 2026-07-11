"""Tests for ``news_agent.fetchers.rss`` — RSS feed fetcher via feedparser.

Uses pytest-httpx to mock the httpx pre-fetch, then feedparser parses
the real ( miniature ) RSS XML.
"""

from __future__ import annotations

import logging

from news_agent.config import SourceEntry
from news_agent.fetchers.rss import fetch_rss

# -- Valid RSS 2.0 with two items --------------------------------------------
RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Article One</title>
      <link>https://example.com/1</link>
      <description>Summary of article one</description>
    </item>
    <item>
      <title>Article Two</title>
      <link>https://example.com/2</link>
      <description>Summary of article two</description>
    </item>
  </channel>
</rss>"""

EMPTY_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
  </channel>
</rss>"""

BOZO_XML = b"<rss><broken"


def test_fetch_rss_returns_normalized_dicts(httpx_mock) -> None:
    source = SourceEntry(type="rss", url="https://example.com/rss", domain="ai_tech")
    httpx_mock.add_response(
        url="https://example.com/rss",
        content=RSS_XML,
        status_code=200,
        headers={"Content-Type": "application/rss+xml"},
    )

    result = fetch_rss(source)

    assert len(result) == 2
    assert result[0]["url"] == "https://example.com/1"
    assert result[0]["title"] == "Article One"
    assert result[0]["domain"] == "ai_tech"
    assert "fetched_at" in result[0]


def test_fetch_rss_empty_feed(httpx_mock) -> None:
    source = SourceEntry(type="rss", url="https://example.com/empty", domain="ai_tech")
    httpx_mock.add_response(
        url="https://example.com/empty",
        content=EMPTY_RSS_XML,
        status_code=200,
    )

    result = fetch_rss(source)
    assert result == []


def test_fetch_rss_bozo_feed(httpx_mock, caplog) -> None:
    """Malformed XML returns empty list with warning."""
    source = SourceEntry(type="rss", url="https://example.com/bad", domain="ai_tech")
    httpx_mock.add_response(
        url="https://example.com/bad",
        content=BOZO_XML,
        status_code=200,
    )

    with caplog.at_level(logging.WARNING):
        result = fetch_rss(source)

    assert result == []
    assert any(
        "error" in r.message.lower() or "bozo" in r.message.lower()
        for r in caplog.records
    )
