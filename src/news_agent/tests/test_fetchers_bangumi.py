"""Tests for ``news_agent.fetchers.bangumi`` — Bangumi API v0 fetcher."""

from __future__ import annotations

from news_agent.config import SourceEntry
from news_agent.fetchers.bangumi import fetch_bangumi

BANGUMI_JSON = {
    "data": [
        {
            "id": 123,
            "name_cn": "测试动画",
            "name": "テストアニメ",
            "summary": "这是完整摘要，内容较长",
            "short_summary": "短摘要",
            "date": "2024-01-15",
        },
        {
            "id": 456,
            "name_cn": "",
            "name": "Another Anime",
            "summary": "Another summary",
            "date": "2023-06-01",
        },
    ]
}


def test_fetch_bangumi_name_cn_preferred(httpx_mock) -> None:
    """name_cn is preferred over name when both present."""
    source = SourceEntry(
        type="api",
        url="https://api.bgm.tv",
        domain="yuri_gl",
        params={"tag": "百合", "type": 2},
    )
    httpx_mock.add_response(
        url="https://api.bgm.tv/v0/subjects?type=2&tag=%E7%99%BE%E5%90%88&limit=20&sort=date",
        json=BANGUMI_JSON,
        status_code=200,
    )

    result = fetch_bangumi(source)
    assert len(result) == 2
    assert result[0]["title"] == "测试动画"
    assert result[1]["title"] == "Another Anime"


def test_fetch_bangumi_short_summary_preferred(httpx_mock) -> None:
    """short_summary is used when available, truncated to 500 chars."""
    source = SourceEntry(
        type="api",
        url="https://api.bgm.tv",
        domain="yuri_gl",
    )
    httpx_mock.add_response(
        url="https://api.bgm.tv/v0/subjects?type=2&tag=%E7%99%BE%E5%90%88&limit=20&sort=date",
        json=BANGUMI_JSON,
        status_code=200,
    )

    result = fetch_bangumi(source)
    assert result[0]["summary"] == "短摘要"


def test_fetch_bangumi_non_200(httpx_mock) -> None:
    source = SourceEntry(type="api", url="https://api.bgm.tv", domain="yuri_gl")
    httpx_mock.add_response(
        url="https://api.bgm.tv/v0/subjects?type=2&tag=%E7%99%BE%E5%90%88&limit=20&sort=date",
        status_code=500,
    )
    result = fetch_bangumi(source)
    assert result == []
