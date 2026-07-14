"""Dataclass-based config schema with YAML reader and fallback-to-defaults.

Config is loaded from ``config.yaml`` (cwd), then ``%APPDATA%/news-agent/config.yaml``,
and falls back to hardcoded sensible defaults if neither file exists or is
unparseable.  No hot-reload, no plugin hierarchy — pure stdlib dataclasses.

Typical usage::

    from news_agent.config import load_config, save_config, get_default_config
    cfg = load_config()
    print(cfg.weather_city)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("news_agent")

# ---------------------------------------------------------------------------
# Allowed values
# ---------------------------------------------------------------------------
_VALID_DOMAINS = frozenset({"github_trending", "programming", "bilibili_hot"})
_VALID_TYPES = frozenset(
    {"rss", "rsshub", "bilibili_hot", "github_trending"}
)


# ---------------------------------------------------------------------------
# Dataclass schema
# ---------------------------------------------------------------------------


@dataclass
class SourceEntry:
    """A single news source definition.

    ``params`` captures extra per-source keys from YAML (e.g. ``limit``,
    ``keyword``) that are not part of the core schema.
    """

    type: str  # "rss" | "rsshub" | "bilibili_hot" | "github_trending"
    url: str
    domain: str  # see _VALID_DOMAINS
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    """Top-level configuration.

    All fields have safe defaults so that a bare ``Config()`` is always
    usable.
    """

    api_key_ref: str = "keyring"
    sources: list[SourceEntry] = field(default_factory=list)
    cost_ceiling_daily_tokens: int = 50_000
    weather_city: str = "Beijing"
    hotkey_binding: str = "ctrl+alt+n"
    window_position: dict[str, int] = field(
        default_factory=lambda: {"x": -1, "y": -1, "w": 800, "h": 600}
    )  # x,y=-1 means centered
    worker_schedule: list[str] = field(
        default_factory=lambda: ["06:00", "18:00"]
    )  # 24hr HH:MM
    rsshub_url: str = "http://localhost:1200"
    retention_days: int = 30
    proxy: str = ""  # e.g. "http://127.0.0.1:7890" for Clash; empty = direct


# ---------------------------------------------------------------------------
# Default sources (one per domain — from RSSHub_SOURCES.md)
# ---------------------------------------------------------------------------

_DEFAULT_SOURCES: list[SourceEntry] = [
    SourceEntry(
        type="github_trending",
        url="https://github.com/trending?since=daily",
        domain="github_trending",
        params={},
    ),
    SourceEntry(
        type="rss",
        url="https://hnrss.org/frontpage?points=50",
        domain="programming",
        params={},
    ),
    SourceEntry(
        type="bilibili_hot",
        url="https://api.bilibili.com/x/web-interface/search/square?limit=10",
        domain="bilibili_hot",
        params={},
    ),
]


def get_default_config() -> Config:
    """Return a ``Config`` populated with one starter source per domain."""
    return Config(sources=list(_DEFAULT_SOURCES))


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _appdata_config_dir() -> Path:
    """Return ``%APPDATA%/news-agent/`` (or ``~/.config/news-agent/``)."""
    base = os.environ.get("APPDATA", str(Path.home() / ".config"))
    return Path(base) / "news-agent"


def _appdata_config_path() -> Path:
    return _appdata_config_dir() / "config.yaml"


def get_config_path() -> Path:
    """Return the resolved path that ``load_config()`` would try first.

    * ``config.yaml`` in cwd, if it exists.
    * Otherwise ``%APPDATA%/news-agent/config.yaml``.
    """
    cwd_path = Path("config.yaml")
    if cwd_path.exists():
        return cwd_path.resolve()
    appdata_path = _appdata_config_path()
    if appdata_path.exists():
        return appdata_path
    project_path = Path(__file__).resolve().parents[2] / "config.yaml"
    return project_path if project_path.exists() else appdata_path


def _resolve_config_path(path: Path | None) -> Path | None:
    """Resolve a user-supplied or auto-discovered config path.

    Returns ``None`` when no file exists (caller should use defaults).
    """
    if path is not None:
        return path if path.exists() else None

    cwd_path = Path("config.yaml")
    if cwd_path.exists():
        return cwd_path

    appdata_path = _appdata_config_path()
    if appdata_path.exists():
        return appdata_path

    # Task Scheduler starts from an arbitrary directory, so also look beside
    # the source package for source-based installations.
    project_path = Path(__file__).resolve().parents[2] / "config.yaml"
    if project_path.exists():
        return project_path

    return None


# ---------------------------------------------------------------------------
# YAML ↔ dataclass conversion
# ---------------------------------------------------------------------------


def _parse_yaml_file(path: Path) -> dict[str, Any] | None:
    """Safely parse a YAML file.  Returns ``None`` on any error."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError:
        logger.error("Config parse failed at %s, using defaults", path, exc_info=True)
        return None
    except OSError:
        logger.warning("Cannot read config file %s, using defaults", path)
        return None


def _dict_to_source_entry(raw: dict[str, Any], domain: str) -> SourceEntry | None:
    """Convert a single source dict from YAML into a ``SourceEntry``.

    Returns ``None`` when the entry is invalid (bad domain/type).
    """
    source_type = raw.get("type", "")
    if source_type not in _VALID_TYPES:
        logger.warning(
            "Unknown source type '%s' for domain '%s', skipping entry", source_type, domain
        )
        return None

    url = raw.get("url", "")
    if not url:
        logger.warning("Source entry missing 'url' for domain '%s', skipping", domain)
        return None

    # Collect unknown keys into params
    known_keys = {"type", "url", "domain"}
    params = {k: str(v) for k, v in raw.items() if k not in known_keys}

    return SourceEntry(type=source_type, url=url, domain=domain, params=params)


def _raw_dict_to_config(raw: dict[str, Any]) -> Config:
    """Convert a YAML-loaded dict into a ``Config`` instance.

    Missing keys fall back to ``Config`` defaults.  Unknown domains and
    invalid source types are logged and skipped.
    """
    defaults = Config()

    # --- api_key_ref ---
    api_key_ref = raw.get("api_key_ref")
    if isinstance(api_key_ref, str):
        api_key_ref = api_key_ref
    else:
        api_key_ref = defaults.api_key_ref

    # --- cost_ceiling_daily_tokens ---
    cost = raw.get("cost_ceiling_daily_tokens")
    if isinstance(cost, int) and cost > 0:
        cost_ceiling = cost
    else:
        cost_ceiling = defaults.cost_ceiling_daily_tokens

    # --- weather_city ---
    city = raw.get("weather_city")
    if isinstance(city, str):
        weather_city = city
    else:
        weather_city = defaults.weather_city

    # --- hotkey_binding ---
    hotkey = raw.get("hotkey_binding")
    if isinstance(hotkey, str):
        hotkey_binding = hotkey
    else:
        hotkey_binding = defaults.hotkey_binding

    # --- window_position ---
    wp_raw = raw.get("window_position")
    if isinstance(wp_raw, dict):
        window_position = {
            "x": int(wp_raw.get("x", -1) or -1),
            "y": int(wp_raw.get("y", -1) or -1),
            "w": int(wp_raw.get("w", 800) or 800),
            "h": int(wp_raw.get("h", 600) or 600),
        }
    else:
        window_position = dict(defaults.window_position)

    # --- worker_schedule ---
    ws_raw = raw.get("worker_schedule")
    if isinstance(ws_raw, list) and all(isinstance(v, str) for v in ws_raw):
        worker_schedule = ws_raw
    else:
        worker_schedule = list(defaults.worker_schedule)

    # --- rsshub_url ---
    rsshub = raw.get("rsshub_url") or raw.get("rsshub_base")
    if isinstance(rsshub, str):
        rsshub_url = rsshub
    else:
        rsshub_url = defaults.rsshub_url

    # --- retention_days ---
    ret = raw.get("retention_days") or raw.get("article_retention_days")
    if isinstance(ret, int) and ret > 0:
        retention_days = ret
    else:
        retention_days = defaults.retention_days

    # --- proxy ---
    proxy = raw.get("proxy")
    if isinstance(proxy, str) and proxy.strip():
        proxy = proxy.strip()
    else:
        proxy = defaults.proxy

    # --- sources ---
    sources: list[SourceEntry] = []
    raw_sources = raw.get("sources")
    if isinstance(raw_sources, dict):
        for domain, entries in raw_sources.items():
            if domain not in _VALID_DOMAINS:
                logger.warning(
                    "Unknown domain '%s' in config, skipping %d source(s)",
                    domain,
                    len(entries) if isinstance(entries, list) else 0,
                )
                continue
            if not isinstance(entries, list):
                continue
            for entry_raw in entries:
                if not isinstance(entry_raw, dict):
                    continue
                se = _dict_to_source_entry(entry_raw, domain)
                if se is not None:
                    sources.append(se)
    elif isinstance(raw_sources, list):
        # Flat list format (unusual but tolerate it)
        for entry_raw in raw_sources:
            if not isinstance(entry_raw, dict):
                continue
            domain = entry_raw.get("domain", "")
            if domain not in _VALID_DOMAINS:
                logger.warning("Unknown domain '%s' in flat source list, skipping", domain)
                continue
            se = _dict_to_source_entry(entry_raw, domain)
            if se is not None:
                sources.append(se)

    return Config(
        api_key_ref=api_key_ref,
        sources=sources,
        cost_ceiling_daily_tokens=cost_ceiling,
        weather_city=weather_city,
        hotkey_binding=hotkey_binding,
        window_position=window_position,
        worker_schedule=worker_schedule,
        rsshub_url=rsshub_url,
        retention_days=retention_days,
        proxy=proxy,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None) -> Config:
    """Load configuration from *path* (or auto-discover), never crashing.

    Resolution order when *path* is ``None``:
    1. ``config.yaml`` in the current working directory.
    2. ``%APPDATA%/news-agent/config.yaml``.
    3. Return ``get_default_config()``.

    If *path* is provided but the file is missing, a warning is logged and
    ``get_default_config()`` is returned (no exception).

    Corrupt YAML is caught, logged, and the same fallback applies.
    """
    resolved = _resolve_config_path(path)
    if resolved is None:
        if path is not None:
            logger.warning(
                "Config file not found at %s, using defaults", path
            )
        else:
            logger.info("No config file found, using built-in defaults")
        return get_default_config()

    raw = _parse_yaml_file(resolved)
    if raw is None:
        return get_default_config()

    if not isinstance(raw, dict):
        logger.warning(
            "Config at %s is not a mapping (got %s), using defaults",
            resolved,
            type(raw).__name__,
        )
        return get_default_config()

    return _raw_dict_to_config(raw)


def save_config(config: Config, path: Path | None = None) -> None:
    """Write *config* to a YAML file, domain-grouping the source list.

    If *path* is ``None``, the target is
    ``%APPDATA%/news-agent/config.yaml`` (parent directories are created
    as needed).  A UTC timestamp header comment is prepended.
    """
    target = path or _appdata_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    # Build domain-grouped source dict
    domain_sources: dict[str, list[dict[str, Any]]] = {}
    for se in config.sources:
        entry_dict: dict[str, Any] = {"type": se.type, "url": se.url}
        entry_dict.update(se.params)
        domain_sources.setdefault(se.domain, []).append(entry_dict)

    # Top-level config dict
    data: dict[str, Any] = {
        "api_key_ref": config.api_key_ref,
        "cost_ceiling_daily_tokens": config.cost_ceiling_daily_tokens,
        "weather_city": config.weather_city,
        "hotkey_binding": config.hotkey_binding,
        "window_position": dict(config.window_position),
        "worker_schedule": list(config.worker_schedule),
        "rsshub_url": config.rsshub_url,
        "retention_days": config.retention_days,
        "proxy": config.proxy,
        "sources": domain_sources,
    }

    header = (
        f"# news-agent config — generated at {datetime.now(timezone.utc).isoformat()}\n"
    )

    with target.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# CLI summary
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cfg = load_config()
    # Count sources per domain
    counts: dict[str, int] = {}
    for se in cfg.sources:
        counts[se.domain] = counts.get(se.domain, 0) + 1
    parts = [f"{d}: {counts.get(d, 0)}" for d in sorted(_VALID_DOMAINS)]
    print(f"Config loaded — {len(cfg.sources)} sources across {len(counts)} domains")
    print(", ".join(parts) if parts else "(no sources)")
