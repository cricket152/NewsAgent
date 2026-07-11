# Main-process module — never import from worker.py
"""System tray icon with pystray — provides context menu with callbacks."""

from __future__ import annotations

from typing import Callable

import pystray
from PIL import Image, ImageDraw

from news_agent.logging_setup import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

APP_NAME = "NewsAgent"
DEFAULT_BG_COLOR = "#2d8a3c"
ICON_SIZE = 64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_default_icon() -> Image.Image:
    """Generate a 64×64 solid-color icon with a white "N" letter centred."""
    img = Image.new("RGB", (ICON_SIZE, ICON_SIZE), DEFAULT_BG_COLOR)
    draw = ImageDraw.Draw(img)
    text = "N"
    bbox = draw.textbbox((0, 0), text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (ICON_SIZE - text_w) // 2
    y = (ICON_SIZE - text_h) // 2
    draw.text((x, y), text, fill="white")
    return img


def _build_menu(
    on_show: Callable[[], None],
    on_quit: Callable[[], None],
    on_settings: Callable[[], None] | None = None,
) -> pystray.Menu:
    """Build the tray context menu with three items."""
    settings_cb: Callable[[], None] = (
        on_settings if on_settings is not None else lambda: None
    )
    return pystray.Menu(
        pystray.MenuItem("今日播报", on_show, default=True),
        pystray.MenuItem("设置", settings_cb),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", on_quit),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_tray_icon(
    on_show: Callable[[], None],
    on_quit: Callable[[], None],
    on_settings: Callable[[], None] | None = None,
    icon_image: Image.Image | None = None,
) -> pystray.Icon:
    """Build a :class:`pystray.Icon` with a context menu.  Does **not** run the event loop.

    Args:
        on_show: Callback for "今日播报" menu item (also the default / left-click action).
        on_quit: Callback for "退出" menu item.
        on_settings: Optional callback for "设置" menu item; no-op when ``None``.
        icon_image: Optional 64×64 icon; a teal-green "N" default is generated when
            ``None``.

    Returns:
        A :class:`pystray.Icon` configured but not yet visible / running.
    """
    menu = _build_menu(on_show, on_quit, on_settings)
    image = icon_image if icon_image is not None else _make_default_icon()

    icon = pystray.Icon(
        name=APP_NAME,
        icon=image,
        title=f"{APP_NAME} 今日播报",
        menu=menu,
    )
    icon.visible = False  # caller controls when to show
    logger.debug("tray icon created (not visible)")
    return icon


def run_tray(icon: pystray.Icon) -> None:
    """Run the pystray event loop (blocking on Windows).

    Sets the icon visible via a *setup* hook that fires after the native
    window is created but before the message loop starts.
    """

    def _on_ready(tray_icon: pystray.Icon) -> None:
        tray_icon.visible = True

    logger.info("tray icon running …")
    icon.run(setup=_on_ready)


def stop_tray(icon: pystray.Icon) -> None:
    """Stop the tray icon event loop and hide the icon."""
    icon.stop()
    icon.visible = False
    logger.info("tray stopped")


def update_icon_image(icon: pystray.Icon, image: Image.Image) -> None:
    """Replace the tray icon image at runtime."""
    icon.icon = image


def update_tooltip(icon: pystray.Icon, text: str) -> None:
    """Change the tray icon tooltip text."""
    icon.title = text


# ---------------------------------------------------------------------------
# Smoke test (does NOT block)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _icon = create_tray_icon(
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    print("OK")
