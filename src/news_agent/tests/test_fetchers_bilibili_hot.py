"""Tests for ``news_agent.fetchers.bilibili_hot`` — Bilibili hot-search fetcher."""

from __future__ import annotations

from news_agent.config import SourceEntry
from news_agent.fetchers.bilibili_hot import fetch_bilibili_hot

MOCK_JSON = """{
  "code": 0,
  "data": {
    "trending": {
      "title": "bilibili\u70ed\u641c",
      "list": [
        {"keyword": "\u6d4b\u8bd5\u5173\u952e\u8bcd1",
         "show_name": "\u6d4b\u8bd5\u70ed\u641c1",
         "heat_score": 32922574, "position": 1},
        {"keyword": "\u6d4b\u8bd5\u8bcd2",
         "show_name": "\u6d4b\u8bd5\u70ed\u641c2",
         "heat_score": 500000, "position": 2},
        {"keyword": "test3",
         "show_name": "\u6d4b\u8bd5\u70ed\u641c3",
         "heat_score": 100, "position": 3}
      ]
    }
  }
}"""


def test_fetch_bilibili_hot_returns_normalized_dicts(httpx_mock) -> None:
    source = SourceEntry(type="api", url="https://api.bilibili.com", domain="bilibili_hot")

    httpx_mock.add_response(
        url="https://api.bilibili.com/x/web-interface/search/square?limit=10",
        content=MOCK_JSON.encode("utf-8"),
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    result = fetch_bilibili_hot(source)

    assert len(result) == 3

    # First item
    assert result[0]["title"] == "测试热搜1"
    assert "%E6%B5%8B%E8%AF%95%E5%85%B3%E9%94%AE%E8%AF%8D1" in result[0]["url"]
    assert result[0]["url"].startswith("https://search.bilibili.com/all?keyword=")
    assert result[0]["domain"] == "bilibili_hot"
    assert "热度" in result[0]["summary"]
    assert "3292万" in result[0]["summary"]
    assert "source_url" in result[0]
    assert "fetched_at" in result[0]
    assert "published_at" in result[0]

    # Second item
    assert result[1]["title"] == "测试热搜2"
    assert "%E6%B5%8B%E8%AF%95%E8%AF%8D2" in result[1]["url"]
    assert "50万" in result[1]["summary"]

    # Third item
    assert result[2]["title"] == "测试热搜3"
    assert "test3" in result[2]["url"]
    assert "100" in result[2]["summary"]


def test_fetch_bilibili_hot_api_error(httpx_mock) -> None:
    source = SourceEntry(type="api", url="https://api.bilibili.com", domain="bilibili_hot")

    httpx_mock.add_response(
        url="https://api.bilibili.com/x/web-interface/search/square?limit=10",
        content=b'{"code": -1, "message": "error"}',
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    result = fetch_bilibili_hot(source)
    assert result == []


def test_fetch_bilibili_hot_non_200(httpx_mock) -> None:
    source = SourceEntry(type="api", url="https://api.bilibili.com", domain="bilibili_hot")

    httpx_mock.add_response(
        url="https://api.bilibili.com/x/web-interface/search/square?limit=10",
        status_code=500,
    )

    result = fetch_bilibili_hot(source)
    assert result == []
