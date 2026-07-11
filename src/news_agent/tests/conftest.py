"""Pytest shared fixtures — mock all external I/O, no real network/API/registry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_agent.config import Config, SourceEntry

# ── autouse: redirect APPDATA + TEMP to tmp_path for all tests ────────────


@pytest.fixture(autouse=True)
def temp_appdata_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect APPDATA & TEMP to tmp_path so no real user data is touched."""
    appdata = tmp_path / "AppData"
    temp_dir = tmp_path / "Temp"
    appdata.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    (appdata / "news-agent").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("TEMP", str(temp_dir))
    return tmp_path


# ── database fixture ──────────────────────────────────────────────────────


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Fresh DB path per test under tmp_path."""
    return tmp_path / "state.db"


# ── config fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def sample_config() -> Config:
    """Return a Config() with all default values."""
    return Config()


@pytest.fixture
def sample_source_rss() -> SourceEntry:
    """A sample RSS-type SourceEntry."""
    return SourceEntry(
        type="rss",
        url="https://example.com/rss",
        domain="ai_tech",
    )


@pytest.fixture
def sample_source_rsshub() -> SourceEntry:
    """A sample rsshub-type SourceEntry."""
    return SourceEntry(
        type="rsshub",
        url="/test/route",
        domain="programming",
    )


@pytest.fixture
def sample_source_html() -> SourceEntry:
    """A sample html-type SourceEntry."""
    return SourceEntry(
        type="html",
        url="https://example.com/news",
        domain="arknights",
    )


@pytest.fixture
def sample_source_api() -> SourceEntry:
    """A sample api-type SourceEntry."""
    return SourceEntry(
        type="api",
        url="https://api.example.com/v1/items",
        domain="yuri_gl",
    )


@pytest.fixture
def sample_bundle() -> dict:
    """A fully populated daily-bundle dict (5 domains x 3 articles each)."""
    domains = ["github_trending", "programming", "bilibili_hot"]
    articles_by_domain: dict[str, list[dict]] = {}
    for d in domains:
        articles_by_domain[d] = [
            {
                "url": f"https://{d}.example.com/article/{i}",
                "title": f"{d} article {i}",
                "summary": f"Summary of {d} article {i}",
                "domain": d,
                "source_url": f"https://{d}.example.com/feed",
                "published_at": f"2026-07-{10+i:02d}T0{i}:00:00Z",
                "fetched_at": "2026-07-11T08:00:00Z",
                "ai_summary": f"AI: {d} article {i} summary",
            }
            for i in range(3)
        ]
    return {
        "articles_by_domain": articles_by_domain,
        "weather": {
            "city": "Beijing",
            "resolved_name": "Beijing",
            "latitude": 39.9,
            "longitude": 116.4,
            "today": {
                "temp_max": 32.0,
                "temp_min": 22.0,
                "precipitation_mm": 0.0,
                "weather_code": 0,
                "weather_description": "晴",
            },
            "fetched_at": "2026-07-11T08:00:00Z",
            "source": "open-meteo",
        },
        "fortune": {
            "solar_date": "2026-07-11",
            "lunar_date": "丙午年 五月廿七",
            "ganzi_year": "丙午",
            "lunar_month_name": "五月",
            "lunar_day_name": "廿七",
            "is_leap_month": False,
            "zodiac": "马",
            "weekday": "星期六",
            "yi": ["嫁娶", "出行", "祭祀"],
            "ji": ["动土", "开仓"],
            "fetched_at": "2026-07-11T08:00:00Z",
            "source": "lunardate+local-rules",
        },
        "daily_summary": "今日AI/科技和编程领域有多项重要更新。",
        "headlines_only_mode": False,
        "fetched_at": "2026-07-11T08:00:00Z",
    }


# ── OpenAI client mock ────────────────────────────────────────────────────


@pytest.fixture
def mock_openai_client() -> MagicMock:
    """Mock openai.OpenAI class — no real DeepSeek API calls.

    Returns the patched OpenAI class mock. Test functions can configure
    ``mock_openai_client.return_value.chat.completions.create`` to control
    behaviour (return_value, side_effect, etc.).
    """
    with patch("news_agent.llm.OpenAI") as mock_cls:
        mock_instance = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "mocked AI response"
        mock_response.choices = [mock_choice]
        mock_response.usage.total_tokens = 100
        mock_instance.chat.completions.create.return_value = mock_response
        mock_cls.return_value = mock_instance
        yield mock_cls


# ── pytest-httpx integration ──────────────────────────────────────────────
# pytest-httpx provides `httpx_mock` fixture automatically — no alias needed.
# Use `httpx_mock.add_response(...)` directly in test functions.


# ── winreg mock ───────────────────────────────────────────────────────────


@pytest.fixture
def mock_winreg() -> MagicMock:
    """Mock the ``winreg`` module — no real registry writes.

    Use in autostart tests. Returns the patched module mock.
    """
    with patch("news_agent.autostart.winreg") as mock_mod:
        # Set up common constants used by autostart module
        mock_mod.HKEY_CURRENT_USER = 0
        mock_mod.KEY_SET_VALUE = 2
        mock_mod.KEY_READ = 1
        mock_mod.REG_SZ = 1
        yield mock_mod


# ── subprocess mock ───────────────────────────────────────────────────────


@pytest.fixture
def mock_subprocess() -> MagicMock:
    """Mock ``subprocess.run`` — no real schtasks calls.

    Returns the patched ``subprocess.run`` mock.
    """
    with patch("news_agent.scheduler.subprocess.run") as mock_run:
        yield mock_run


# ── convenience: keyring mock ─────────────────────────────────────────────


@pytest.fixture
def mock_keyring() -> MagicMock:
    """Mock the ``keyring`` module — no real credential manager access."""
    with patch("news_agent.api_key.keyring") as mock_mod:
        yield mock_mod
