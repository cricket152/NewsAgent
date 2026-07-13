# Main-process module — never import from worker.py
"""pywebview window with Edge WebView2 backend for daily digest and chat UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2
import webview

from news_agent.chat_bridge import ChatBridge
from news_agent.logging_setup import get_logger

if TYPE_CHECKING:
    from news_agent.config import Config

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

APP_NAME = "news-agent"
STATE_FILENAME = "latest_state.json"
TEMPLATE_DIR = Path(__file__).parent / "templates"
DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 600

logger = get_logger()

# Windows DWM attributes used to keep the native title bar aligned with the
# application's light interface. Unsupported attributes are ignored safely on
# older Windows builds.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
COLORREF_WHITE = 0x00FFFFFF
COLORREF_BLACK = 0x00000000

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_current_window: webview.Window | None = None
_chat_bridge: ChatBridge | None = None
_jinja_env: jinja2.Environment | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_state_dir() -> Path:
    """Return ``%APPDATA%/news-agent/`` (falls back to ``~/.config/news-agent/``)."""
    base = os.environ.get("APPDATA", str(Path.home() / ".config"))
    return Path(base) / APP_NAME


def _get_env() -> jinja2.Environment:
    """Return the module-level Jinja2 ``Environment`` (lazy-init singleton)."""
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=jinja2.select_autoescape(["html"]),
        )
    return _jinja_env


def _get_chat_bridge(db_path: Path | None = None) -> ChatBridge:
    """Return the module-level :class:`ChatBridge` singleton.

    Constructed once on first call; subsequent calls ignore *db_path*.
    """
    global _chat_bridge
    if _chat_bridge is None:
        _chat_bridge = ChatBridge(db_path=db_path)
        logger.debug("ChatBridge initialised")
    return _chat_bridge


def refresh_window() -> None:
    """Render the latest worker bundle into the already-open viewer window."""
    window = get_window()
    if window is None:
        return
    window.load_html(render_html(load_bundle()))


def _apply_light_title_bar(window: webview.Window) -> None:
    """Force a white Windows title bar with dark caption text.

    pywebview follows the operating-system app theme by default, which gives
    this otherwise light interface a black native title bar when Windows uses
    dark mode. DWM color attributes are best-effort so older Windows versions
    continue to work without affecting window creation.
    """
    if os.name != "nt":
        return

    native = getattr(window, "native", None)
    handle = getattr(native, "Handle", None)
    if handle is None:
        logger.debug("Native window handle unavailable; title bar unchanged")
        return

    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(handle.ToInt32())
        dwm_set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        dwm_set_window_attribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]

        for attribute, color in (
            (DWMWA_USE_IMMERSIVE_DARK_MODE, 0),
            (DWMWA_CAPTION_COLOR, COLORREF_WHITE),
            (DWMWA_TEXT_COLOR, COLORREF_BLACK),
        ):
            value = ctypes.c_int(color)
            dwm_set_window_attribute(
                hwnd,
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
    except Exception:
        logger.debug("Unable to apply light native title bar", exc_info=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_bundle(state_path: Path | None = None) -> dict | None:
    """Read the daily bundle JSON from *state_path* or the default location.

    Default path: ``%APPDATA%/news-agent/latest_state.json``.

    Returns ``None`` (with a logged warning) when the file is missing,
    unreadable, or contains invalid JSON — never raises.
    """
    path = state_path or (_get_state_dir() / STATE_FILENAME)
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("Bundle file not found: %s", path)
        return None
    except json.JSONDecodeError:
        logger.warning("Bundle file contains invalid JSON: %s", path, exc_info=True)
        return None
    except OSError:
        logger.warning("Cannot read bundle file: %s", path, exc_info=True)
        return None


def render_html(bundle: dict | None) -> str:
    """Render ``daily.html`` Jinja2 template with *bundle* as context.

    When *bundle* is ``None`` an empty ``dict`` is substituted — the
    template uses ``|default`` guards for every top-level key, so
    ``UndefinedError`` is never raised.
    """
    env = _get_env()
    template = env.get_template("daily.html")
    return template.render(**(bundle or {}))


def create_window(
    config: Config | None = None, db_path: Path | None = None
) -> webview.Window | None:
    """Create a pywebview window displaying the daily briefing.

    Calls :func:`load_bundle` and :func:`render_html` internally.  Window
    geometry is taken from ``config.window_position`` when *config* is
    provided (``x`` or ``y`` equal to ``-1`` means centred).

    Does **not** call :func:`webview.start` — the caller owns the GUI event
    loop.

    Returns the new :class:`webview.Window` instance.
    """
    global _current_window

    bundle = load_bundle()
    html = render_html(bundle)

    # --- JS API bridge for chat tab ---
    bridge = _get_chat_bridge(db_path=db_path)
    bridge.set_refresh_callback(refresh_window)

    # --- Resolve window geometry ---
    width = DEFAULT_WIDTH
    height = DEFAULT_HEIGHT
    x: int | None = None  # None → centred
    y: int | None = None

    if config is not None:
        wp = config.window_position
        width = int(wp.get("w", DEFAULT_WIDTH) or DEFAULT_WIDTH)
        height = int(wp.get("h", DEFAULT_HEIGHT) or DEFAULT_HEIGHT)
        rx = int(wp.get("x", -1) or -1)
        ry = int(wp.get("y", -1) or -1)
        if rx >= 0:
            x = rx
        if ry >= 0:
            y = ry

    window = webview.create_window(
        title="今日播报 NewsAgent",
        html=html,
        width=width,
        height=height,
        x=x,
        y=y,
        on_top=False,
        js_api=bridge,
    )
    if window is not None:
        window.events.shown += lambda: _apply_light_title_bar(window)
    _current_window = window
    return window


def get_window() -> webview.Window | None:
    """Return the most recently created window, or ``None``."""
    return _current_window


def show_window(window: webview.Window | None = None) -> None:
    """Show *window*, creating one via :func:`create_window` if none exists."""
    if window is None:
        window = get_window()
    if window is None:
        window = create_window()
    if window is not None:
        window.show()


def hide_window(window: webview.Window | None = None) -> None:
    """Hide *window* (falls back to :func:`get_window`)."""
    if window is None:
        window = get_window()
    if window is not None:
        window.hide()


def destroy_window(window: webview.Window | None = None) -> None:
    """Destroy *window* and clear the internal module-level reference.

    Falls back to :func:`get_window` when *window* is ``None``.  Any
    exception during ``window.destroy()`` is logged and not re-raised.
    """
    global _current_window

    if window is None:
        window = get_window()
    if window is not None:
        try:
            window.destroy()
        except Exception:
            logger.warning("Error destroying window", exc_info=True)
    _current_window = None


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    bundle_path = _get_state_dir() / STATE_FILENAME
    print(f"Bundle path: {bundle_path}")

    # load_bundle — returns None when file doesn't exist
    bundle = load_bundle()
    print(f"load_bundle result: {type(bundle).__name__}")

    # render_html with empty dict — must not raise Jinja2 UndefinedError
    html = render_html({})
    print(f"render_html({{}}) length: {len(html)} chars")

    # render_html with None — same behaviour
    html2 = render_html(None)
    print(f"render_html(None) length: {len(html2)} chars")

    print("OK")
