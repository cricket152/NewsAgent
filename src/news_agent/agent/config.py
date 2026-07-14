# Main-process module — never import from worker.py
"""Persistent agent-level config at ``%APPDATA%/news-agent/agent_config.json``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from news_agent.logging_setup import get_logger

logger = get_logger()


def _default_config() -> dict:
    return {"skills_enabled": {}, "mcp_servers": [], "system_prompt": ""}


def get_agent_config_path() -> Path:
    """Return the path to ``agent_config.json`` under the AppData directory."""
    return Path(os.environ["APPDATA"]) / "news-agent" / "agent_config.json"


def load_agent_config() -> dict:
    """Load agent config from disk.

    Returns:
        Parsed config dict, or ``{"skills_enabled": {}, "mcp_servers": []}``
        when the file is missing / unreadable / not valid JSON.
    """
    path = get_agent_config_path()
    try:
        if not path.exists():
            return _default_config()
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        logger.warning("failed to load agent_config, using defaults", exc_info=True)
        return _default_config()


def save_agent_config(cfg: dict) -> None:
    """Atomically write *cfg* to ``agent_config.json``.

    Uses a temporary file + ``os.replace`` so readers never see a partial file.
    """
    path = get_agent_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            prefix="agent_config_",
            suffix=".tmp",
        )
        try:
            json.dump(cfg, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        finally:
            tmp.close()
        os.replace(tmp.name, path)
    except OSError:
        logger.warning("failed to save agent_config", exc_info=True)


def get_enabled_skills() -> dict[str, bool]:
    """Convenience helper — read ``skills_enabled`` from ``agent_config.json``.

    Returns:
        Dict of ``{skill_name: enabled_bool}``.  Empty dict when unavailable.
    """
    cfg = load_agent_config()
    return cfg.get("skills_enabled", {})


def get_mcp_servers_from_agent_config() -> list[dict]:
    """Return the ``mcp_servers`` list stored in ``agent_config.json``.

    Returns:
        List of MCP server dicts, or ``[]`` when unavailable.
    """
    cfg = load_agent_config()
    return cfg.get("mcp_servers", [])
