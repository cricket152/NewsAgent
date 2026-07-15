"""Tests for ``news_agent.curator`` — orchestrates fetchers + LLM."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from news_agent.config import Config, SourceEntry
from news_agent.curator import run_curator
from news_agent.db import get_write_connection, init_db, insert_article

FAKE_ARTICLE = {
    "url": "https://example.com/1",
    "title": "Test Article",
    "summary": "Test summary",
    "domain": "ai_tech",
    "source_url": "https://example.com/feed",
    "published_at": "2026-07-11T06:00:00Z",
    "fetched_at": "2026-07-11T08:00:00Z",
}

_MOCK_FORTUNE = {
    "solar_date": "2026-07-11",
    "lunar_date": "丙午年 五月廿七",
    "ganzi_year": "丙午",
    "lunar_month_name": "五月",
    "lunar_day_name": "廿七",
    "is_leap_month": False,
    "zodiac": "马",
    "weekday": "星期六",
    "yi": ["嫁娶"],
    "ji": ["动土"],
    "fetched_at": "2026-07-11T08:00:00Z",
    "source": "lunardate",
}


def _make_config_with_sources() -> Config:
    cfg = Config()
    cfg.sources = [
        SourceEntry(
            type="github_trending",
            url="https://github.com/trending?since=daily",
            domain="github_trending",
        ),
        SourceEntry(
            type="rss",
            url="https://example.com/prog",
            domain="programming",
        ),
        SourceEntry(
            type="bilibili_hot",
            url="https://api.bilibili.com/x/web-interface/search/square?limit=10",
            domain="bilibili_hot",
        ),
    ]
    return cfg


def test_run_curator_returns_all_domains(tmp_db_path: Path) -> None:
    """All 3 domains present in output, headlines_only_mode=False, daily_summary non-empty."""
    init_db(tmp_db_path)
    cfg = _make_config_with_sources()

    with patch("news_agent.curator.chat", return_value="AI摘要内容"):
        with patch("news_agent.fetchers.fortune.fetch_fortune", return_value=_MOCK_FORTUNE):
            with patch("news_agent.fetchers.weather.fetch_weather", return_value=None):
                with patch("news_agent.curator._dispatch_fetcher") as mock_dispatch:
                    mock_dispatch.side_effect = lambda source, config: [
                        dict(FAKE_ARTICLE, domain=source.domain)
                    ]
                    result = run_curator(cfg, db_path=tmp_db_path)

    assert "articles_by_domain" in result
    assert set(result["articles_by_domain"]) == {
        "github_trending",
        "programming",
        "bilibili_hot",
    }
    assert all(result["articles_by_domain"].values())
    assert result["headlines_only_mode"] is False
    assert len(result["daily_summary"]) > 0


def test_run_curator_cost_ceiling_headlines_only(tmp_db_path: Path) -> None:
    """When remaining tokens is 0, headlines_only_mode=True, no LLM calls."""
    init_db(tmp_db_path)
    cfg = _make_config_with_sources()

    with patch(
        "news_agent.curator.get_today_remaining_tokens", return_value=0
    ):
        with patch("news_agent.curator.chat") as mock_chat:
            with patch(
                "news_agent.fetchers.fortune.fetch_fortune",
                return_value=_MOCK_FORTUNE,
            ):
                with patch("news_agent.fetchers.weather.fetch_weather", return_value=None):
                    with patch("news_agent.curator._dispatch_fetcher", return_value=[]):
                        result = run_curator(cfg, db_path=tmp_db_path)

    assert result["headlines_only_mode"] is True
    mock_chat.assert_not_called()


def test_run_curator_keeps_a_local_summary_when_llm_fails(tmp_db_path: Path) -> None:
    """A blocked LLM must not leave the refreshed home page summary empty."""
    init_db(tmp_db_path)
    cfg = _make_config_with_sources()

    with patch("news_agent.curator.chat", side_effect=RuntimeError("blocked")):
        with patch("news_agent.fetchers.fortune.fetch_fortune", return_value=_MOCK_FORTUNE):
            with patch("news_agent.fetchers.weather.fetch_weather", return_value=None):
                with patch(
                    "news_agent.curator._dispatch_fetcher",
                    return_value=[dict(FAKE_ARTICLE)],
                ):
                    result = run_curator(cfg, db_path=tmp_db_path)

    assert result["daily_summary"]
    assert "AI" in result["daily_summary"]


def test_run_curator_graceful_degradation(tmp_db_path: Path) -> None:
    """When one fetcher raises, other domains are still fetched."""
    init_db(tmp_db_path)
    cfg = _make_config_with_sources()

    call_count = 0

    def _flaky_dispatch(source, config):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate a failed fetcher — in production _dispatch_fetcher
            # catches exceptions and returns [], so we return [] here.
            return []
        return [dict(FAKE_ARTICLE, domain=source.domain)]

    with patch("news_agent.curator.chat", return_value="ok"):
        with patch("news_agent.fetchers.fortune.fetch_fortune", return_value=_MOCK_FORTUNE):
            with patch("news_agent.fetchers.weather.fetch_weather", return_value=None):
                with patch(
                    "news_agent.curator._dispatch_fetcher",
                    side_effect=_flaky_dispatch,
                ):
                    result = run_curator(cfg, db_path=tmp_db_path)

    assert call_count == 4
    assert "articles_by_domain" in result
    assert all(result["articles_by_domain"].values())
    assert not result["headlines_only_mode"]


def test_run_curator_uses_cached_domain_after_live_fetch_fails(
    tmp_db_path: Path, tmp_path: Path, monkeypatch
) -> None:
    """A transiently unavailable source must not erase its domain section."""
    init_db(tmp_db_path)
    cfg = _make_config_with_sources()
    state_dir = tmp_path / "news-agent"
    state_dir.mkdir()
    cached_article = dict(
        FAKE_ARTICLE,
        url="https://example.com/cached-bilibili",
        domain="bilibili_hot",
        ai_summary="cached summary",
    )
    (state_dir / "latest_state.json").write_text(
        json.dumps({"articles_by_domain": {"bilibili_hot": [cached_article]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))

    def _dispatch(source, config):
        if source.domain == "bilibili_hot":
            return []
        return [dict(FAKE_ARTICLE, domain=source.domain)]

    with patch("news_agent.curator.chat", return_value="ok"):
        with patch("news_agent.fetchers.fortune.fetch_fortune", return_value=_MOCK_FORTUNE):
            with patch("news_agent.fetchers.weather.fetch_weather", return_value=None):
                with patch("news_agent.curator._dispatch_fetcher", side_effect=_dispatch):
                    result = run_curator(cfg, db_path=tmp_db_path)

    assert all(result["articles_by_domain"].values())
    assert result["articles_by_domain"]["bilibili_hot"][0]["url"] == cached_article["url"]
    assert result["articles_by_domain"]["bilibili_hot"][0]["ai_summary"] == "ok"


def test_run_curator_uses_database_when_latest_state_lacks_domain(
    tmp_db_path: Path, tmp_path: Path, monkeypatch
) -> None:
    """SQLite history is the fallback when the latest bundle is already incomplete."""
    init_db(tmp_db_path)
    cfg = _make_config_with_sources()
    conn = get_write_connection(tmp_db_path)
    try:
        insert_article(
            conn,
            url="https://example.com/database-bilibili",
            title="Cached database article",
            summary="Cached summary",
            source="https://api.bilibili.com",
            domain="bilibili_hot",
            published_at=None,
            summary_ai="Cached AI summary",
        )
        conn.commit()
    finally:
        conn.close()

    state_dir = tmp_path / "news-agent"
    state_dir.mkdir()
    (state_dir / "latest_state.json").write_text(
        json.dumps({"articles_by_domain": {}}), encoding="utf-8"
    )
    monkeypatch.setenv("APPDATA", str(tmp_path))

    def _dispatch(source, config):
        if source.domain == "bilibili_hot":
            return []
        return [dict(FAKE_ARTICLE, domain=source.domain)]

    with patch("news_agent.curator.chat", return_value="ok"):
        with patch("news_agent.fetchers.fortune.fetch_fortune", return_value=_MOCK_FORTUNE):
            with patch("news_agent.fetchers.weather.fetch_weather", return_value=None):
                with patch("news_agent.curator._dispatch_fetcher", side_effect=_dispatch):
                    result = run_curator(cfg, db_path=tmp_db_path)

    articles = result["articles_by_domain"]["bilibili_hot"]
    assert articles
    assert articles[0]["url"] == "https://example.com/database-bilibili"
