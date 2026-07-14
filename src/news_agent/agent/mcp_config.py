# Main-process module — never import from worker.py
"""Persistence helper for ``%APPDATA%/news-agent/mcp_config.yaml``.

Mirrors ``agent_config.json``'s ``mcp_servers`` entry for users who prefer to
edit YAML directly.
"""

from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import threading
from pathlib import Path

import httpx
import yaml

from news_agent.logging_setup import get_logger

logger = get_logger()

_VALID_TRANSPORTS = frozenset({"stdio", "http"})
_REQUIRED_KEYS = frozenset({"name", "transport", "command_or_url"})


def get_mcp_config_path() -> Path:
    """Return the path to ``mcp_config.yaml`` under the AppData directory."""
    base = Path(os.environ.get("APPDATA", str(Path.home() / ".config")))
    return base / "news-agent" / "mcp_config.yaml"


def _initialize_request() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "news-agent", "version": "0.1.0"},
        },
    }


def _probe_http(url: str, timeout: float) -> dict:
    response = httpx.post(
        url,
        json=_initialize_request(),
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        payload_text = next(
            (line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")),
            "",
        )
        payload = json.loads(payload_text)
    else:
        payload = response.json()
    if not isinstance(payload, dict) or ("result" not in payload and "error" not in payload):
        raise RuntimeError("server returned an invalid MCP initialize response")
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    info = payload.get("result", {}).get("serverInfo", {})
    label = info.get("name") or "MCP server"
    return {"ok": True, "message": f"Connected to {label}", "server_info": info}


def _probe_stdio(command: str, timeout: float) -> dict:
    args = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        args = [
            arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] == '"' else arg
            for arg in args
        ]
    if not args:
        raise ValueError("stdio command is empty")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=flags,
    )
    output: queue.Queue[str] = queue.Queue(maxsize=1)

    def read_response() -> None:
        if process.stdout is not None:
            output.put(process.stdout.readline())

    try:
        if process.stdin is None:
            raise RuntimeError("could not open MCP stdio input")
        process.stdin.write(json.dumps(_initialize_request()) + "\n")
        process.stdin.flush()
        threading.Thread(target=read_response, daemon=True).start()
        try:
            line = output.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("MCP server did not answer initialize in time") from exc
        payload = json.loads(line)
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        info = payload.get("result", {}).get("serverInfo", {})
        return {
            "ok": True,
            "message": f"Connected to {info.get('name') or 'MCP server'}",
            "server_info": info,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def probe_mcp_server(server: dict, timeout: float = 8.0) -> dict:
    """Test one MCP server with the protocol initialize handshake."""
    if not isinstance(server, dict):
        return {"ok": False, "message": "invalid MCP server configuration"}
    transport = server.get("transport")
    target = str(server.get("command_or_url", "")).strip()
    if not target:
        return {"ok": False, "message": "command or URL is empty"}
    try:
        if transport == "http":
            return _probe_http(target, timeout)
        if transport == "stdio":
            return _probe_stdio(target, timeout)
        return {"ok": False, "message": f"unsupported transport: {transport}"}
    except Exception as exc:
        logger.warning("MCP probe failed for %s", server.get("name", "?"), exc_info=True)
        return {"ok": False, "message": str(exc)}


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
        raise
