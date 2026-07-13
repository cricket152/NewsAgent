# Main-process module — never import from worker.py
"""pywebview JS API bridge exposing conversation functions to the daily.html chat tab.

Single instance per viewer window — constructed lazily by
``viewer._get_chat_bridge()``.  Every public method accepts and returns
JSON-serialisable values (str/int/bool/list[...]/dict/None) so pywebview
can marshal them to JavaScript.  Method names are fixed per the daily.html
JS contract:

* ``send_message(text: str) -> str``
* ``get_history(limit: int = 50) -> list[dict]``
* ``clear_history() -> int``
* ``get_status() -> dict``
"""

from __future__ import annotations

import os
from pathlib import Path

from news_agent.agent.conversation import (
    clear_history as _clear_history,
)
from news_agent.agent.conversation import (
    get_history as _get_history,
)
from news_agent.agent.conversation import (
    send_message as _send_message,
)
from news_agent.llm import get_today_remaining_tokens as _get_today_remaining_tokens
from news_agent.logging_setup import get_logger

logger = get_logger()


class ChatBridge:
    """Exposes a stable JSON-friendly surface to the webview JS side.

    Every public method must accept and return JSON-serialisable values
    (str/int/bool/list[...]/dict/None) so pywebview can marshal them
    to JavaScript.  No exceptions should escape — return error strings
    instead so the JS side always gets a value.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        # If caller (viewer.create_window) passes a concrete path, use it.
        # Else, conversation.py's internal _resolve_db() handles the default.
        self._db_path = db_path

    # -- public JS API surface (names fixed by daily.html contract) --

    def send_message(self, text: str) -> str:
        """Send user input to the conversational agent and return its reply.

        Degraded-path returns:
        * ``"请输入有效内容。"`` on empty/whitespace input.
        * ``"AI 服务暂时不可用，请稍后重试。"`` on any unhandled error.
        """
        stripped = text.strip()
        if not stripped:
            return "请输入有效内容。"

        try:
            return _send_message(stripped, db_path=self._db_path)
        except ValueError as exc:
            logger.warning("send_message validation error: %s", exc)
            return str(exc)
        except Exception:
            logger.warning("send_message failed", exc_info=True)
            return "AI 服务暂时不可用，请稍后重试。"

    def get_history(self, limit: int = 50) -> list[dict]:
        """Return recent conversation messages, oldest → newest.

        Returns an empty list on error.
        """
        if limit < 1:
            return []
        try:
            return _get_history(limit=limit, db_path=self._db_path)
        except Exception:
            logger.warning("get_history failed", exc_info=True)
            return []

    def clear_history(self) -> int:
        """Delete all conversation rows.  Returns 0 on error."""
        try:
            return _clear_history(db_path=self._db_path)
        except Exception:
            logger.warning("clear_history failed", exc_info=True)
            return 0

    def get_status(self) -> dict:
        """Lightweight readiness probe — checks whether the LLM budget is available.

        Returns ``{"ready": bool, "message": str}``.
        """
        try:
            db = (
                self._db_path
                or Path(os.environ.get("APPDATA", ""))
                / "news-agent"
                / "data"
                / "state.db"
            )
            remaining = _get_today_remaining_tokens(db)
            if remaining > 0:
                return {"ready": True, "message": "在线"}
            return {"ready": False, "message": "今日AI额度已用完"}
        except Exception:
            logger.warning("get_status probe failed", exc_info=True)
            return {"ready": False, "message": "状态不可用"}

    # ── Skill management ────────────────────────────────────────────────

    def list_skills(self) -> list[dict]:
        """Return all prompt-skill ``.md`` files in the skills directory.

        Returns a (possibly empty) list of ``{name, description, path}`` dicts.
        """
        try:
            from news_agent.agent.skills import list_skills as _list_skills
            return _list_skills()
        except Exception:
            logger.warning("list_skills failed", exc_info=True)
            return []

    def toggle_skill(self, name: str, enabled: bool) -> dict:
        """Enable or disable a prompt-skill by name in ``agent_config.json``.

        Returns ``{"name": str, "enabled": bool}`` on success, or an error dict
        on failure.
        """
        try:
            from news_agent.agent.config import load_agent_config, save_agent_config

            cfg = load_agent_config()
            skills: dict = cfg.setdefault("skills_enabled", {})
            skills[name] = enabled
            save_agent_config(cfg)
            return {"name": name, "enabled": enabled}
        except Exception as exc:
            logger.warning("toggle_skill(%r) failed", name, exc_info=True)
            return {"name": name, "enabled": False, "error": str(exc)}

    # ── Agent config management ─────────────────────────────────────────

    def get_agent_config(self) -> dict:
        """Return the full ``agent_config.json`` dict, or ``{}`` on error."""
        try:
            from news_agent.agent.config import load_agent_config
            return load_agent_config()
        except Exception:
            logger.warning("get_agent_config failed", exc_info=True)
            return {}

    def save_agent_config(self, config: dict) -> dict:
        """Persist *config* to ``agent_config.json`` and return it.

        On error the returned dict gains an ``"error"`` key.
        """
        try:
            from news_agent.agent.config import save_agent_config as _save_cfg
            _save_cfg(config)
            return config
        except Exception as exc:
            logger.warning("save_agent_config failed", exc_info=True)
            result = dict(config)
            result["error"] = str(exc)
            return result

    # ── MCP server management ───────────────────────────────────────────

    def list_mcp_servers(self) -> list[dict]:
        """Return the MCP server list from ``mcp_config.yaml``, or ``[]``."""
        try:
            from news_agent.agent.mcp_config import list_mcp_servers as _list_mcp
            return _list_mcp()
        except Exception:
            logger.warning("list_mcp_servers failed", exc_info=True)
            return []

    def save_mcp_servers(self, servers: list[dict]) -> list[dict]:
        """Persist *servers* to ``mcp_config.yaml`` and return the re-read list.

        Returns ``[]`` on error.
        """
        try:
            from news_agent.agent.mcp_config import list_mcp_servers as _list_mcp
            from news_agent.agent.mcp_config import save_mcp_servers as _save_mcp

            _save_mcp(servers)
            return _list_mcp()
        except Exception:
            logger.warning("save_mcp_servers failed", exc_info=True)
            return []


# ── Smoke test (no real token consumption) ──────────────────────────

if __name__ == "__main__":
    bridge = ChatBridge(db_path=None)
    print("status:", bridge.get_status())
    print("history:", bridge.get_history(limit=2))
