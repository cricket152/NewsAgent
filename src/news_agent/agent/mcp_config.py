# Main-process module — never import from worker.py
"""Persistence helper for ``%APPDATA%/news-agent/mcp_config.yaml``.

Mirrors ``agent_config.json``'s ``mcp_servers`` entry for users who prefer to
edit YAML directly.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from news_agent.logging_setup import get_logger

logger = get_logger()

_VALID_TRANSPORTS = frozenset({"stdio", "http"})
_REQUIRED_KEYS = frozenset({"name", "transport", "command_or_url"})


def get_mcp_config_path() -> Path:
    """Return the path to ``mcp_config.yaml`` under the AppData directory."""
    return Path(os.environ["APPDATA"]) / "news-agent" / "mcp_config.yaml"


def list_mcp_servers() -> list[dict]:
    """Load and validate the MCP server list from ``mcp_config.yaml``.

    Returns:
        List of ``{name, transport, command_or_url}`` dicts.  Entries missing
        required keys or using an unsupported transport are silently dropped.
        Returns ``[]`` when the file is missing, empty, or corrupt.
    """
    path = get_mcp_config_path()
    try:
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            return []
        raw = data.get("mcp_servers")
        if not isinstance(raw, list):
            return []
        result: list[dict] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            if not _REQUIRED_KEYS.issubset(entry.keys()):
                continue
            if entry.get("transport") not in _VALID_TRANSPORTS:
                continue
            result.append(
                {
                    "name": entry["name"],
                    "transport": entry["transport"],
                    "command_or_url": entry["command_or_url"],
                }
            )
        return result
    except (yaml.YAMLError, OSError):
        logger.warning("failed to load mcp_config.yaml", exc_info=True)
        return []


def save_mcp_servers(servers: list[dict]) -> None:
    """Write the MCP server list to ``mcp_config.yaml``.

    Invalid entries (missing keys / unsupported transport) are skipped with a
    warning.  The file is written with a descriptive comment header.
    """
    path = get_mcp_config_path()
    valid: list[dict] = []
    for entry in servers:
        if not isinstance(entry, dict):
            logger.warning("skipping non-dict mcp server entry: %r", entry)
            continue
        if not _REQUIRED_KEYS.issubset(entry.keys()):
            logger.warning("skipping mcp server entry missing keys: %r", entry)
            continue
        if entry.get("transport") not in _VALID_TRANSPORTS:
            logger.warning(
                "skipping mcp server entry with unsupported transport: %r", entry
            )
            continue
        valid.append(
            {
                "name": entry["name"],
                "transport": entry["transport"],
                "command_or_url": entry["command_or_url"],
            }
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "# MCP config — managed by news-agent\n"
        content += yaml.dump({"mcp_servers": valid}, allow_unicode=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError:
        logger.warning("failed to save mcp_config.yaml", exc_info=True)
