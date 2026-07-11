"""Tests for ``news_agent.config`` — YAML config load/save/validation."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from news_agent.config import (
    Config,
    SourceEntry,
    get_config_path,
    get_default_config,
    load_config,
    save_config,
)

# ── get_default_config ─────────────────────────────────────────────────────


def test_default_config_3_sources() -> None:
    cfg = get_default_config()
    assert len(cfg.sources) == 3
    domains = {s.domain for s in cfg.sources}
    assert domains == {"github_trending", "programming", "bilibili_hot"}


# ── roundtrip ──────────────────────────────────────────────────────────────


def test_roundtrip_save_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(
        weather_city="Shanghai",
        cost_ceiling_daily_tokens=10000,
        rsshub_url="http://custom:1200",
    )
    cfg.sources = [
        SourceEntry(type="rss", url="https://example.com/rss", domain="programming"),
        SourceEntry(type="rsshub", url="/bilibili/popular/all", domain="bilibili_hot"),
    ]
    config_file = tmp_path / "config.yaml"
    save_config(cfg, config_file)
    loaded = load_config(config_file)
    assert loaded.weather_city == "Shanghai"
    assert loaded.cost_ceiling_daily_tokens == 10000
    assert loaded.rsshub_url == "http://custom:1200"
    assert len(loaded.sources) == 2
    assert loaded.sources[0].domain == "programming"
    assert loaded.sources[1].domain == "bilibili_hot"


# ── load_config edge cases ─────────────────────────────────────────────────


def test_load_missing_file_returns_defaults() -> None:
    cfg = load_config(Path("/nonexistent/path/config.yaml"))
    assert isinstance(cfg, Config)
    assert cfg.weather_city == "Beijing"


def test_load_corrupt_yaml_returns_defaults(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(": invalid ::: yaml", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = load_config(bad_yaml)
    assert isinstance(cfg, Config)
    # Should have logged a warning or error about parse failure


def test_load_partial_config_fills_defaults(tmp_path: Path) -> None:
    partial_path = tmp_path / "partial.yaml"
    data = {"weather_city": "Shanghai"}
    with open(partial_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)
    cfg = load_config(partial_path)
    assert cfg.weather_city == "Shanghai"
    # Other fields should be defaults from Config()
    assert cfg.hotkey_binding == "ctrl+alt+n"
    assert cfg.retention_days == 30


def test_invalid_domain_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    invalid_path = tmp_path / "invalid_domain.yaml"
    data = {
        "sources": {
            "invalid_xyz": [{"type": "rss", "url": "https://example.com/rss"}],
            "programming": [{"type": "rss", "url": "https://hnrss.org/frontpage"}],
        }
    }
    with open(invalid_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)
    with caplog.at_level(logging.WARNING):
        cfg = load_config(invalid_path)
    assert len(cfg.sources) <= 1  # invalid domain skipped
    domains = {s.domain for s in cfg.sources}
    assert "invalid_xyz" not in domains


# ── get_config_path ────────────────────────────────────────────────────────


def test_get_config_path_cwd_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CWD config.yaml is preferred over APPDATA."""
    cwd_config = tmp_path / "config.yaml"
    cwd_config.write_text("weather_city: Nanjing", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # CWD has config.yaml → should be returned
    resolved = get_config_path()
    assert resolved.resolve() == cwd_config.resolve()


def test_get_config_path_falls_back_to_appdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When CWD has no config.yaml, APPDATA path is returned."""
    empty_dir = tmp_path / "empty_cwd"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)
    # No config.yaml in CWD → returns APPDATA path (which doesn't need to exist)
    resolved = get_config_path()
    assert "news-agent" in str(resolved)
