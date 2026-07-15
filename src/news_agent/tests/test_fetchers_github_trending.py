"""Tests for ``news_agent.fetchers.github_trending`` — GitHub trending fetcher."""

from __future__ import annotations

from datetime import date

from news_agent.config import SourceEntry
from news_agent.fetchers.github_trending import (
    _select_daily_sample,
    fetch_github_trending,
)

MOCK_HTML = b"""<html><body>
<article class="Box-row">
  <h2><a href="/owner1/repo1">owner1 /repo1</a></h2>
  <p>A test repo description for testing</p>
  <a class="Link--muted" href="/owner1/repo1/stargazers">1,234</a>
  <a class="Link--muted" href="/owner1/repo1/forks">56</a>
  <span itemprop="programmingLanguage">Python</span>
</article>
<article class="Box-row">
  <h2><a href="/owner2/repo2">owner2 /repo2</a></h2>
  <p>Another test repository</p>
  <a class="Link--muted" href="/owner2/repo2/stargazers">5,678</a>
  <a class="Link--muted" href="/owner2/repo2/forks">100</a>
  <span itemprop="programmingLanguage">Rust</span>
</article>
</body></html>"""


def test_fetch_github_trending_parses_repos(httpx_mock) -> None:
    source = SourceEntry(type="html", url="https://github.com/trending", domain="github_trending")

    httpx_mock.add_response(
        url="https://github.com/trending",
        content=MOCK_HTML,
        status_code=200,
        headers={"Content-Type": "text/html"},
    )

    result = fetch_github_trending(source)

    assert len(result) == 2

    # First repo
    assert "owner1" in result[0]["title"] or "repo1" in result[0]["title"]
    assert result[0]["url"] == "https://github.com/owner1/repo1"
    assert result[0]["domain"] == "github_trending"
    assert "1,234" in result[0]["summary"]
    assert "⭐" in result[0]["summary"]
    assert "Python" in result[0]["summary"]
    assert "A test repo description" in result[0]["summary"]
    assert "source_url" in result[0]
    assert "fetched_at" in result[0]

    # Second repo
    assert "owner2" in result[1]["title"]
    assert result[1]["url"] == "https://github.com/owner2/repo2"
    assert "5,678" in result[1]["summary"]
    assert "Rust" in result[1]["summary"]
    assert "Another test repository" in result[1]["summary"]


def test_fetch_github_trending_empty_page(httpx_mock) -> None:
    source = SourceEntry(type="html", url="https://github.com/trending", domain="github_trending")

    httpx_mock.add_response(
        url="https://github.com/trending",
        content=b"<html><body><p>No trending repos today</p></body></html>",
        status_code=200,
        headers={"Content-Type": "text/html"},
    )

    result = fetch_github_trending(source)
    assert result == []


def test_fetch_github_trending_non_200(httpx_mock) -> None:
    source = SourceEntry(type="html", url="https://github.com/trending", domain="github_trending")

    httpx_mock.add_response(
        url="https://github.com/trending",
        status_code=500,
    )

    result = fetch_github_trending(source)
    assert result == []


def test_daily_sample_is_stable_and_limited_to_five() -> None:
    entries = [
        {"url": f"https://github.com/owner/repo-{index}"}
        for index in range(20)
    ]

    first = _select_daily_sample(entries, sample_date=date(2026, 7, 15))
    repeated = _select_daily_sample(entries, sample_date=date(2026, 7, 15))

    assert len(first) == 5
    assert first == repeated
    assert len({entry["url"] for entry in first}) == 5
    assert all(entry in entries for entry in first)


def test_daily_sample_changes_across_days() -> None:
    entries = [
        {"url": f"https://github.com/owner/repo-{index}"}
        for index in range(20)
    ]

    first_day = _select_daily_sample(entries, sample_date=date(2026, 7, 15))
    next_day = _select_daily_sample(entries, sample_date=date(2026, 7, 16))

    assert first_day != next_day


def test_daily_sample_keeps_all_entries_when_fewer_than_five() -> None:
    entries = [
        {"url": f"https://github.com/owner/repo-{index}"}
        for index in range(3)
    ]

    assert _select_daily_sample(entries, sample_date=date(2026, 7, 15)) == entries
