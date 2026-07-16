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
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from news_agent import db as _db
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


class _NewsRefreshRunner:
    """Run the worker in a separate process and expose its current state."""

    def __init__(self, on_success: Callable[[], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._status = "idle"
        self._message = ""
        self._on_success = on_success

    def set_on_success(self, callback: Callable[[], None]) -> None:
        self._on_success = callback

    def start(self) -> dict:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return {"started": False, "status": "running", "message": "刷新任务正在进行中"}

            command = self._worker_command()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
            except OSError as exc:
                self._status = "failed"
                self._message = str(exc)
                logger.warning("Could not start refresh worker", exc_info=True)
                return {"started": False, "status": "failed", "message": "无法启动刷新任务"}

            self._status = "running"
            self._message = "正在检索新闻并生成概要…"
            threading.Thread(target=self._watch, daemon=True, name="news-refresh-watch").start()
            return {"started": True, "status": self._status, "message": self._message}

    def status(self) -> dict:
        with self._lock:
            return {"status": self._status, "message": self._message}

    @staticmethod
    def _worker_command() -> list[str]:
        if getattr(sys, "frozen", False):
            worker = Path(sys.executable).with_name("NewsAgentWorker.exe")
            if worker.is_file():
                return [str(worker)]
        return [sys.executable, "-m", "news_agent.worker"]

    def _watch(self) -> None:
        process = self._process
        if process is None:
            return
        return_code = process.wait()
        callback: Callable[[], None] | None = None
        with self._lock:
            if return_code == 0:
                self._status = "completed"
                self._message = "刷新完成"
                callback = self._on_success
            else:
                self._status = "failed"
                self._message = "刷新失败，请查看日志"

        if callback is not None:
            try:
                callback()
            except Exception:
                logger.warning("Could not reload viewer after refresh", exc_info=True)


class ChatBridge:
    """Exposes a stable JSON-friendly surface to the webview JS side.

    Every public method must accept and return JSON-serialisable values
    (str/int/bool/list[...]/dict/None) so pywebview can marshal them
    to JavaScript.  No exceptions should escape — return error strings
    instead so the JS side always gets a value.
    """

    def __init__(
        self, db_path: Path | None = None, weather_city: str | None = None
    ) -> None:
        # If caller (viewer.create_window) passes a concrete path, use it.
        # Else, conversation.py's internal _resolve_db() handles the default.
        self._db_path = db_path
        self._weather_city = weather_city
        self._refresh_runner = _NewsRefreshRunner()
        self._session_id: str | None = None
        self._window_provider: Callable[[], object | None] | None = None

    def _conversation_db_path(self) -> Path:
        return (
            self._db_path
            or Path(os.environ.get("APPDATA", ""))
            / "news-agent"
            / "data"
            / "state.db"
        )

    def _ensure_session(self) -> str:
        if self._session_id is not None:
            return self._session_id
        path = self._conversation_db_path()
        _db.init_db(path)
        conn = _db.get_write_connection(path)
        try:
            sessions = _db.list_conversation_sessions(conn)
            if sessions:
                self._session_id = str(sessions[0]["id"])
            else:
                self._session_id = str(_db.create_conversation_session(conn)["id"])
            conn.commit()
        finally:
            conn.close()
        return self._session_id

    def set_refresh_callback(self, callback: Callable[[], None]) -> None:
        """Set the view reload callback run after a successful refresh."""
        self._refresh_runner.set_on_success(callback)

    def set_window_provider(self, callback: Callable[[], object | None]) -> None:
        """Set the lazy window provider used for native file dialogs."""
        self._window_provider = callback

    # -- application shortcuts --

    def list_shortcuts(self) -> list[dict]:
        """Return user-managed application shortcuts for the home page."""
        try:
            from news_agent.shortcuts import list_shortcuts_for_ui

            return list_shortcuts_for_ui()
        except Exception:
            logger.warning("list_shortcuts failed", exc_info=True)
            return []

    def choose_shortcut(self) -> dict:
        """Open a native application picker and save the selected target."""
        try:
            import webview

            from news_agent.shortcuts import add_shortcut

            window = self._window_provider() if self._window_provider else None
            if window is None:
                return {"added": False, "error": "应用窗口尚未就绪。"}
            selected = window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=False,
                file_types=("应用程序与快捷方式 (*.exe;*.lnk)",),
            )
            if not selected:
                return {"added": False, "cancelled": True}
            item = add_shortcut(selected[0])
            return {"added": True, "shortcut": item}
        except ValueError as exc:
            return {"added": False, "error": str(exc)}
        except Exception:
            logger.warning("choose_shortcut failed", exc_info=True)
            return {"added": False, "error": "无法添加该应用。"}

    def delete_shortcut(self, shortcut_id: str) -> dict:
        """Delete one application shortcut by its stored ID."""
        try:
            from news_agent.shortcuts import delete_shortcut

            deleted = delete_shortcut(str(shortcut_id))
            return {"deleted": deleted, "id": str(shortcut_id)}
        except Exception:
            logger.warning("delete_shortcut failed", exc_info=True)
            return {"deleted": False, "error": "无法删除快捷入口。"}

    def launch_shortcut(self, shortcut_id: str) -> dict:
        """Launch one stored application shortcut."""
        try:
            from news_agent.shortcuts import launch_shortcut

            return launch_shortcut(str(shortcut_id))
        except Exception:
            logger.warning("launch_shortcut failed", exc_info=True)
            return {"launched": False, "message": "无法启动该程序。"}

    def refresh_news(self) -> dict:
        """Start a background worker run for news retrieval and AI summaries."""
        return self._refresh_runner.start()

    def get_refresh_status(self) -> dict:
        """Return current manual-refresh state for the home-page button."""
        return self._refresh_runner.status()

    def get_current_weather(self) -> dict:
        """Fetch current weather without running the news/LLM refresh pipeline."""
        try:
            from news_agent.config import load_config
            from news_agent.fetchers.weather import fetch_weather

            city = self._weather_city or load_config().weather_city
            weather = fetch_weather(city, timeout=10.0)
            if weather is None:
                return {"success": False, "message": "天气更新暂时不可用"}
            return {"success": True, "weather": weather}
        except Exception:
            logger.warning("get_current_weather failed", exc_info=True)
            return {"success": False, "message": "天气更新暂时不可用"}

    def get_autostart_status(self) -> dict:
        """Return whether NewsAgent starts automatically after sign-in."""
        try:
            from news_agent.autostart import is_autostart_enabled

            return {"enabled": is_autostart_enabled()}
        except Exception as exc:
            logger.warning("get_autostart_status failed", exc_info=True)
            return {"enabled": False, "error": str(exc)}

    def set_autostart(self, enabled: bool) -> dict:
        """Enable or disable Windows sign-in startup and return actual state."""
        try:
            from news_agent.autostart import (
                disable_autostart,
                enable_autostart,
                is_autostart_enabled,
            )

            success = enable_autostart() if enabled else disable_autostart()
            return {"success": success, "enabled": is_autostart_enabled()}
        except Exception as exc:
            logger.warning("set_autostart(%s) failed", enabled, exc_info=True)
            return {"success": False, "enabled": not enabled, "error": str(exc)}

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
            return _send_message(
                stripped, db_path=self._db_path, session_id=self._ensure_session()
            )
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
            return _get_history(
                limit=limit, db_path=self._db_path, session_id=self._ensure_session()
            )
        except Exception:
            logger.warning("get_history failed", exc_info=True)
            return []

    def clear_history(self) -> int:
        """Delete all conversation rows.  Returns 0 on error."""
        try:
            return _clear_history(db_path=self._db_path, session_id=self._ensure_session())
        except Exception:
            logger.warning("clear_history failed", exc_info=True)
            return 0

    def list_conversations(self) -> list[dict]:
        """Return all saved conversations, newest first."""
        try:
            self._ensure_session()
            conn = _db.get_read_only_connection(self._conversation_db_path())
            try:
                sessions = _db.list_conversation_sessions(conn)
            finally:
                conn.close()
            active_id = self._ensure_session()
            for session in sessions:
                session["active"] = session["id"] == active_id
            return sessions
        except Exception:
            logger.warning("list_conversations failed", exc_info=True)
            return []

    def new_conversation(self) -> dict:
        """Create an independent empty conversation without deleting old ones."""
        try:
            path = self._conversation_db_path()
            _db.init_db(path)
            conn = _db.get_write_connection(path)
            try:
                session = _db.create_conversation_session(conn)
                conn.commit()
            finally:
                conn.close()
            self._session_id = str(session["id"])
            return session
        except Exception as exc:
            logger.warning("new_conversation failed", exc_info=True)
            return {"error": str(exc)}

    def select_conversation(self, session_id: str) -> dict:
        """Switch active AI context to an existing saved conversation."""
        try:
            self._ensure_session()
            conn = _db.get_read_only_connection(self._conversation_db_path())
            try:
                exists = _db.conversation_session_exists(conn, session_id)
            finally:
                conn.close()
            if not exists:
                return {"selected": False, "error": "conversation not found"}
            self._session_id = session_id
            return {"selected": True, "id": session_id}
        except Exception as exc:
            logger.warning("select_conversation failed", exc_info=True)
            return {"selected": False, "error": str(exc)}

    def delete_conversation(self, session_id: str) -> dict:
        """Delete a conversation and keep an active empty session available."""
        try:
            self._ensure_session()
            path = self._conversation_db_path()
            _db.init_db(path)
            conn = _db.get_write_connection(path)
            try:
                if not _db.conversation_session_exists(conn, session_id):
                    return {"deleted": False, "error": "conversation not found"}
                was_active = session_id == self._session_id
                deleted = _db.delete_conversation_session(conn, session_id)
                if was_active:
                    sessions = _db.list_conversation_sessions(conn)
                    replacement = (
                        sessions[0] if sessions else _db.create_conversation_session(conn)
                    )
                    self._session_id = str(replacement["id"])
                conn.commit()
            finally:
                conn.close()
            return {"deleted": deleted > 0, "id": session_id, "active_id": self._session_id}
        except Exception as exc:
            logger.warning("delete_conversation failed", exc_info=True)
            return {"deleted": False, "error": str(exc)}

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

    def import_skill(self, filename: str, content: str) -> dict:
        """Import an uploaded Markdown skill into the writable user directory."""
        try:
            from news_agent.agent.skills import import_skill as _import_skill

            result = _import_skill(filename, content)
            self.toggle_skill(str(result["name"]), True)
            result["enabled"] = True
            return result
        except Exception as exc:
            logger.warning("import_skill failed", exc_info=True)
            return {"error": str(exc)}

    def delete_skill(self, name: str) -> dict:
        """Delete an imported skill and remove its enabled-state entry."""
        try:
            from news_agent.agent.config import load_agent_config, save_agent_config
            from news_agent.agent.skills import delete_skill as _delete_skill

            if not _delete_skill(name):
                return {"deleted": False, "error": "built-in or missing skill"}
            cfg = load_agent_config()
            cfg.setdefault("skills_enabled", {}).pop(name, None)
            save_agent_config(cfg)
            return {"deleted": True, "name": name}
        except Exception as exc:
            logger.warning("delete_skill failed", exc_info=True)
            return {"deleted": False, "error": str(exc)}

    def save_system_prompt(self, prompt: str) -> dict:
        """Persist the optional base system prompt for the conversation agent."""
        try:
            from news_agent.agent.config import load_agent_config, save_agent_config

            if not isinstance(prompt, str) or len(prompt) > 50_000:
                return {"saved": False, "error": "system prompt is too long"}
            cfg = load_agent_config()
            cfg["system_prompt"] = prompt
            save_agent_config(cfg)
            return {"saved": True, "system_prompt": prompt}
        except Exception as exc:
            logger.warning("save_system_prompt failed", exc_info=True)
            return {"saved": False, "error": str(exc)}

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

    def test_mcp_server(self, server: dict) -> dict:
        """Run a non-destructive MCP initialize probe for one server."""
        try:
            from news_agent.agent.mcp_config import probe_mcp_server

            return probe_mcp_server(server)
        except Exception as exc:
            logger.warning("test_mcp_server failed", exc_info=True)
            return {"ok": False, "message": str(exc)}


# ── Smoke test (no real token consumption) ──────────────────────────

if __name__ == "__main__":
    bridge = ChatBridge(db_path=None)
    print("status:", bridge.get_status())
    print("history:", bridge.get_history(limit=2))
