"""Tests for ``news_agent.fetchers.rsshub`` — RSSHub route fetcher."""

from __future__ import annotations

from news_agent.config import SourceEntry
from news_agent.fetchers.rsshub import fetch_rsshub

RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test RSSHub</title>
    <item>
      <title>Item One</title>
      <link>https://example.com/1</link>
      <description>Summary one</description>
    </item>
    <item>
      <title>Item Two</title>
      <link>https://example.com/2</link>
      <description>Summary two</description>
    </item>
  </channel>
</rss>"""


def test_fetch_rsshub_returns_normalized(httpx_mock) -> None:
    source = SourceEntry(type="rsshub", url="/test/route", domain="ai_tech")
    httpx_mock.add_response(
        url="http://localhost:1200/test/route",
        content=RSS_XML,
        status_code=200,
        headers={"Content-Type": "application/rss+xml"},
    )

    result = fetch_rsshub(source, rsshub_url="http://localhost:1200")

    assert len(result) == 2
    assert result[0]["url"] == "https://example.com/1"
    assert result[0]["title"] == "Item One"
    assert result[0]["domain"] == "ai_tech"
    assert "fetched_at" in result[0]


def test_fetch_rsshub_non_200(httpx_mock) -> None:
    source = SourceEntry(type="rsshub", url="/bad/route", domain="programming")
    httpx_mock.add_response(url="http://localhost:1200/bad/route", status_code=404)

    result = fetch_rsshub(source, rsshub_url="http://localhost:1200")
    assert result == []


def test_fetch_rsshub_httpx_error(httpx_mock) -> None:
    source = SourceEntry(type="rsshub", url="/timeout", domain="programming")
    import httpx
    httpx_mock.add_exception(
        url="http://localhost:1200/timeout",
        exception=httpx.ConnectError("Connection refused"),
    )

    result = fetch_rsshub(source, rsshub_url="http://localhost:1200")
    assert result == []
