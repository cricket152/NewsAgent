"""Tests for ``news_agent.fetchers.html_src`` — HTML page scraper."""

from __future__ import annotations

from news_agent.config import SourceEntry
from news_agent.fetchers.html_src import fetch_html

HTML_PAGE = """<html><body>
  <div class="news-list-item">
    <a class="title" href="/page1">News Title 1</a>
    <span class="summary">Summary one here.</span>
  </div>
  <div class="news-list-item">
    <a class="title" href="/page2">News Title 2</a>
    <span class="summary">Summary two here.</span>
  </div>
</body></html>"""


def test_fetch_html_parses_items(httpx_mock) -> None:
    source = SourceEntry(
        type="html",
        url="https://example.com/news",
        domain="arknights",
    )
    httpx_mock.add_response(
        url="https://example.com/news",
        text=HTML_PAGE,
        status_code=200,
    )

    result = fetch_html(source)
    assert len(result) == 2
    assert result[0]["title"] == "News Title 1"
    assert result[0]["domain"] == "arknights"
    assert result[0]["url"].endswith("/page1")


def test_fetch_html_selector_matches_none(httpx_mock) -> None:
    """When CSS selector matches 0 items, returns empty list."""
    source = SourceEntry(
        type="html",
        url="https://example.com/empty",
        domain="arknights",
    )
    httpx_mock.add_response(
        url="https://example.com/empty",
        text="<html><body><p>Nothing here</p></body></html>",
        status_code=200,
    )

    result = fetch_html(source)
    assert result == []


def test_fetch_html_non_200(httpx_mock) -> None:
    source = SourceEntry(type="html", url="https://example.com/404", domain="arknights")
    httpx_mock.add_response(url="https://example.com/404", status_code=404)
    result = fetch_html(source)
    assert result == []
