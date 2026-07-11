# Main-process module — never import from worker.py
"""Main process entry point — tray + viewer + --autostart flag orchestration.

Responsibilities
----------------
1. Parse ``--autostart`` CLI flag.
2. Enforce single-instance via Windows named mutex ``Global\\NewsAgentTray``.
3. Initialise logging, config, and the SQLite state database.
4. Create a tray icon (pystray) running in a background daemon thread.
5. Create the pywebview viewer window and register the close-prevention
   handler (X-click → hide instead of destroy).
6. Register a global hotkey listener (configurable via ``hotkey_binding``,
   default ``Ctrl+Alt+N``).
7. If ``--autostart`` is set, show the daily window immediately (popup-at-boot).
8. Enter the webview event loop via ``webview.start()`` (blocks main thread).
9. On tray "退出" → save position, destroy window, stop tray → loop exits →
   final cleanup.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import threading
from pathlib import Path

import webview

from news_agent import autostart, config, db, tray, viewer
from news_agent.logging_setup import get_logger, setup_logging

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

APP_NAME = "news-agent"
MUTEX_NAME = r"Global\NewsAgentTray"
ERROR_ALREADY_EXISTS = 183

logger: logging.Logger | None = None  # set after setup_logging in main()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags.

    Returns:
        Namespace with ``autostart: bool`` — ``True`` when the process was
        launched by the Windows Registry Run key (i.e. at user logon).
    """
    parser = argparse.ArgumentParser(prog="news-agent", description="NewsAgent tray application")
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Launch as autostart (show daily window immediately)",
    )
    return parser.parse_args(argv)


def _ensure_single_instance() -> bool:
    """Attempt to acquire the single-instance Windows named mutex.

    Returns:
        ``True`` when this is the first/only instance (mutex acquired).
        ``False`` when another instance is already running — the caller
        should log at INFO level and exit gracefully with code 0.
    """
    mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_err = ctypes.GetLastError()
    if last_err == ERROR_ALREADY_EXISTS:
        if mutex_handle:
            ctypes.windll.kernel32.CloseHandle(mutex_handle)
        lgr = get_logger()
        lgr.info("Another instance already running — exiting")
        return False
    return True


def _normalize_hotkey(hotkey_str: str) -> str:
    """Convert a human-readable hotkey string to pynput ``GlobalHotKeys`` format.

    Example: ``"ctrl+alt+n"`` → ``"<ctrl>+<alt>+n"``.

    Supports: ctrl/control, alt, shift, win/super/cmd, and single-character keys.
    """
    parts = [p.strip() for p in hotkey_str.strip().lower().split("+")]
    normalized: list[str] = []
    for part in parts:
        if part in ("ctrl", "control"):
            normalized.append("<ctrl>")
        elif part == "alt":
            normalized.append("<alt>")
        elif part == "shift":
            normalized.append("<shift>")
        elif part in ("win", "super", "cmd"):
            normalized.append("<cmd>")
        elif len(part) == 1:
            normalized.append(part)
        else:
            normalized.append(part)  # pass through unknown tokens
    return "+".join(normalized)


def _resolve_db_path() -> Path:
    """Return ``%APPDATA%\\news-agent\\data\\state.db`` (falls back to
    ``~/.config/news-agent/data/state.db`` on non-Windows)."""
    base = os.environ.get("APPDATA", str(Path.home() / ".config"))
    return Path(base) / APP_NAME / "data" / "state.db"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Launch the NewsAgent tray + viewer application.

    Called automatically by the ``news-agent`` console script defined in
    ``pyproject.toml``.  Handles init, tray, hotkey, viewer lifecycle,
    and graceful shutdown.

    Returns:
        Exit code (0 on success, 1 on init failure, 0 on duplicate-instance
        graceful exit).
    """
    global logger  # noqa: PLW0603

    # ── 1. Parse CLI ──────────────────────────────────────────────────────
    args = parse_args(argv)

    # ── 2. Logging ────────────────────────────────────────────────────────
    setup_logging("main")
    logger = get_logger()
    logger.info("NewsAgent starting (PID=%d, autostart=%s)", os.getpid(), args.autostart)

    # ── 3. Autostart status check (log-only, no functional impact) ────────
    try:
        autostart_enabled = autostart.is_autostart_enabled()
        logger.info("Autostart registry entry: %s", "enabled" if autostart_enabled else "absent")
    except Exception:
        logger.debug("Could not check autostart status", exc_info=True)

    # ── 4. Single-instance enforcement ────────────────────────────────────
    if not _ensure_single_instance():
        return 0

    # ── 5. Load configuration ─────────────────────────────────────────────
    try:
        cfg = config.load_config()
    except Exception:
        logger.error("Failed to load config", exc_info=True)
        return 1

    # Apply proxy if configured (httpx + openai SDK both respect these env vars)
    if cfg.proxy:
        os.environ["HTTP_PROXY"] = cfg.proxy
        os.environ["HTTPS_PROXY"] = cfg.proxy
        logger.info("Using proxy: %s", cfg.proxy)

    # ── 6. Initialise database ────────────────────────────────────────────
    db_path = _resolve_db_path()
    try:
        db.init_db(db_path)
        logger.debug("Database initialised at %s", db_path)
    except Exception:
        logger.error("Failed to initialise database at %s", db_path, exc_info=True)
        return 1

    # ── 7. Build tray callbacks (closures over icon, cfg, listener) ───────
    icon: ctypes.c_void_p | None = None  # type: ignore[assignment]
    listener: object | None = None  # pynput GlobalHotKeys listener

    def on_show() -> None:
        """Handle tray "今日播报" / left-click — show (or create) the viewer."""
        try:
            viewer.show_window()
        except Exception:
            logger.warning("Failed to show window via tray", exc_info=True)

    def on_settings() -> None:
        """Handle tray "设置" menu item (no-op stub for MVP)."""
        logger.info("Settings menu clicked (TBD)")

    def on_quit() -> None:
        """Handle tray "退出" menu item — save state, destroy window, stop tray.

        Runs from the tray daemon thread, so all operations must be
        thread-safe.  Destroying the window causes :func:`webview.start` to
        return on the main thread, which then performs final cleanup.
        """
        logger.info("Shutting down via tray menu …")
        nonlocal_listener = listener  # Capture current value

        # 7a. Save window position to config ----------------------------------
        win = viewer.get_window()
        if win is not None:
            try:
                cfg.window_position = {
                    "x": int(win.x),
                    "y": int(win.y),
                    "w": int(win.width),
                    "h": int(win.height),
                }
                config.save_config(cfg)
                logger.info("Window position saved: %s", cfg.window_position)
            except Exception:
                logger.warning("Failed to save window position on quit", exc_info=True)

        # 7b. Stop hotkey listener (prevent callbacks after window destroyed) --
        if nonlocal_listener is not None:
            try:
                nonlocal_listener.stop()
                logger.debug("Hotkey listener stopped")
            except Exception:
                logger.warning("Failed to stop hotkey listener", exc_info=True)

        # 7c. Destroy the viewer window (unblocks webview.start() on main) ----
        viewer.destroy_window()

        # 7d. Stop the tray icon event loop -----------------------------------
        if icon is not None:
            try:
                tray.stop_tray(icon)
            except Exception:
                logger.warning("Failed to stop tray", exc_info=True)

    # ── 8. Create tray icon and start in daemon thread ────────────────────
    icon = tray.create_tray_icon(
        on_show=on_show,
        on_quit=on_quit,
        on_settings=on_settings,
    )
    tray_thread = threading.Thread(
        target=tray.run_tray,
        args=(icon,),
        daemon=True,
        name="tray-loop",
    )
    tray_thread.start()
    logger.debug("Tray daemon thread started")

    # ── 9. Create viewer window (main thread) ─────────────────────────────
    viewer.create_window(cfg)
    win = viewer.get_window()
    logger.debug("Viewer window created")

    # ── 10. Window close behavior: X → hide, not destroy ──────────────────
    if win is not None:

        def _on_closing() -> bool:
            """Prevent window destruction on X-click; hide instead."""
            logger.debug("Window closing intercepted → hiding")
            viewer.hide_window(win)
            return False  # False = cancel the close / prevent destruction

        win.events.closing += _on_closing

    # ── 11. Global hotkey listener ────────────────────────────────────────
    try:
        from pynput import keyboard  # noqa: PLC0415

        normalized = _normalize_hotkey(cfg.hotkey_binding)
        listener = keyboard.GlobalHotKeys({normalized: lambda: viewer.show_window()})
        listener.start()
        logger.info("Global hotkey registered: %s → %s", cfg.hotkey_binding, normalized)
    except ImportError:
        logger.warning("pynput unavailable, hotkey disabled")
    except Exception:
        logger.warning("Failed to register global hotkey", exc_info=True)

    # ── 12. Autostart popup-at-boot ───────────────────────────────────────
    if args.autostart:
        viewer.show_window()
        logger.info("Showing daily window (--autostart mode)")

    # ── 13. Enter webview GUI event loop (BLOCKS until all windows destroyed)
    #
    # TODO(mvp): Consider a brief splash screen (≤1000 ms) before start()
    # to bridge the WebView2 cold-start delay.  Skipped for now — the delay
    # is acceptable and splash adds complexity without user-facing value.
    logger.info("Entering webview event loop")
    webview.start()

    # ── 14. Post-event-loop cleanup (window destroyed by on_quit) ─────────
    # Listener and tray are already stopped by on_quit; guard double-stop.
    if listener is not None:
        try:
            listener.stop()
        except Exception:
            logger.debug("Listener already stopped (expected)")

    if icon is not None:
        try:
            tray.stop_tray(icon)
        except Exception:
            logger.debug("Tray already stopped (expected)")

    logger.info("Shutdown complete")
    return 0


# ---------------------------------------------------------------------------
# Console script entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
