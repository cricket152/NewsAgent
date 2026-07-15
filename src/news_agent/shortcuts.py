"""Persistent, user-managed Windows application shortcuts."""

from __future__ import annotations

import base64
import ctypes
import io
import json
import os
import uuid
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from PIL import Image

from news_agent.logging_setup import get_logger

logger = get_logger()

ALLOWED_SUFFIXES = {".exe", ".lnk"}
MAX_SHORTCUTS = 24
ICON_SIZE = 40


def get_shortcuts_path() -> Path:
    """Return the per-user shortcut configuration path."""
    base = Path(os.environ.get("APPDATA", str(Path.home() / ".config")))
    return base / "news-agent" / "shortcuts.json"


def _validate_stored_item(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    shortcut_id = value.get("id")
    name = value.get("name")
    target = value.get("path")
    if not all(isinstance(item, str) and item.strip() for item in (shortcut_id, name, target)):
        return None
    if Path(target).suffix.lower() not in ALLOWED_SUFFIXES:
        return None
    return {"id": shortcut_id.strip(), "name": name.strip()[:80], "path": target.strip()}


def load_shortcuts(path: Path | None = None) -> list[dict[str, str]]:
    """Load and validate saved shortcuts, returning an empty list on failure."""
    config_path = path or get_shortcuts_path()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not load application shortcuts", exc_info=True)
        return []
    if not isinstance(raw, list):
        return []
    items = [item for value in raw if (item := _validate_stored_item(value))]
    return items[:MAX_SHORTCUTS]


def save_shortcuts(items: list[dict[str, str]], path: Path | None = None) -> None:
    """Atomically persist a validated shortcut list."""
    config_path = path or get_shortcuts_path()
    validated = [item for value in items if (item := _validate_stored_item(value))]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=config_path.parent,
        delete=False,
        prefix="shortcuts_",
        suffix=".tmp",
    )
    try:
        json.dump(validated[:MAX_SHORTCUTS], temporary, ensure_ascii=False, indent=2)
        temporary.flush()
        os.fsync(temporary.fileno())
    finally:
        temporary.close()
    try:
        os.replace(temporary.name, config_path)
    except OSError:
        Path(temporary.name).unlink(missing_ok=True)
        raise


def _normalise_target(target: str | Path) -> Path:
    path = Path(target).expanduser()
    if not path.is_absolute():
        raise ValueError("请选择本机应用程序或快捷方式。")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("仅支持 .exe 和 .lnk 文件。")
    if not path.is_file():
        raise ValueError("所选程序不存在或无法访问。")
    return path


def add_shortcut(
    target: str | Path,
    *,
    name: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Add a shortcut and return its UI representation."""
    target_path = _normalise_target(target)
    items = load_shortcuts(path)
    target_key = os.path.normcase(str(target_path.resolve(strict=False)))
    if any(
        os.path.normcase(str(Path(item["path"]).resolve(strict=False))) == target_key
        for item in items
    ):
        raise ValueError("该应用已在快捷入口中。")
    if len(items) >= MAX_SHORTCUTS:
        raise ValueError(f"快捷入口最多添加 {MAX_SHORTCUTS} 个应用。")

    display_name = (name or target_path.stem).strip()[:80]
    if not display_name:
        raise ValueError("应用名称不能为空。")
    item = {"id": uuid.uuid4().hex, "name": display_name, "path": str(target_path)}
    items.append(item)
    save_shortcuts(items, path)
    return shortcut_for_ui(item)


def delete_shortcut(shortcut_id: str, path: Path | None = None) -> bool:
    """Delete a saved shortcut by ID."""
    items = load_shortcuts(path)
    remaining = [item for item in items if item["id"] != shortcut_id]
    if len(remaining) == len(items):
        return False
    save_shortcuts(remaining, path)
    return True


def launch_shortcut(shortcut_id: str, path: Path | None = None) -> dict[str, Any]:
    """Launch one stored shortcut without accepting an arbitrary command."""
    item = next((value for value in load_shortcuts(path) if value["id"] == shortcut_id), None)
    if item is None:
        return {"launched": False, "message": "快捷入口不存在。"}
    try:
        target = _normalise_target(item["path"])
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise OSError("unsupported platform")
        startfile(str(target))
        return {"launched": True, "id": shortcut_id}
    except (OSError, ValueError):
        logger.warning("Could not launch shortcut %s", shortcut_id, exc_info=True)
        return {"launched": False, "message": "程序已移动、删除或无法启动。"}


def list_shortcuts_for_ui(path: Path | None = None) -> list[dict[str, Any]]:
    """Return saved shortcuts with availability and display icons."""
    return [shortcut_for_ui(item) for item in load_shortcuts(path)]


def shortcut_for_ui(item: dict[str, str]) -> dict[str, Any]:
    target = Path(item["path"])
    try:
        available = target.is_file()
    except OSError:
        available = False
    result: dict[str, Any] = {
        "id": item["id"],
        "name": item["name"],
        "available": available,
    }
    if available:
        result["icon"] = _icon_data_url(str(target))
    else:
        result["icon"] = None
    return result


@lru_cache(maxsize=64)
def _icon_data_url(target: str) -> str | None:
    """Extract a Windows shell icon and return it as a PNG data URL."""
    if os.name != "nt":
        return None
    try:
        image = _extract_windows_icon(target)
        output = io.BytesIO()
        image.save(output, format="PNG")
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception:
        logger.debug("Could not extract shortcut icon: %s", target, exc_info=True)
        return None


def _extract_windows_icon(target: str) -> Image.Image:
    """Render the Windows shell icon for *target* into an RGBA Pillow image."""

    class SHFILEINFO(ctypes.Structure):
        _fields_ = [
            ("hIcon", ctypes.c_void_p),
            ("iIcon", ctypes.c_int),
            ("dwAttributes", ctypes.c_ulong),
            ("szDisplayName", ctypes.c_wchar * 260),
            ("szTypeName", ctypes.c_wchar * 80),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_ulong),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", ctypes.c_ushort),
            ("biBitCount", ctypes.c_ushort),
            ("biCompression", ctypes.c_ulong),
            ("biSizeImage", ctypes.c_ulong),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", ctypes.c_ulong),
            ("biClrImportant", ctypes.c_ulong),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_ulong * 3)]

    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32.SHGetFileInfoW.restype = ctypes.c_void_p
    user32.GetDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.SelectObject.restype = ctypes.c_void_p

    info = SHFILEINFO()
    flags = 0x000000100 | 0x000000000  # SHGFI_ICON | SHGFI_LARGEICON
    if not shell32.SHGetFileInfoW(
        target, 0, ctypes.byref(info), ctypes.sizeof(info), flags
    ) or not info.hIcon:
        raise OSError("SHGetFileInfoW failed")

    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bits = ctypes.c_void_p()
    bitmap_info = BITMAPINFO()
    bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bitmap_info.bmiHeader.biWidth = ICON_SIZE
    bitmap_info.bmiHeader.biHeight = -ICON_SIZE
    bitmap_info.bmiHeader.biPlanes = 1
    bitmap_info.bmiHeader.biBitCount = 32
    bitmap = gdi32.CreateDIBSection(
        screen_dc, ctypes.byref(bitmap_info), 0, ctypes.byref(bits), None, 0
    )
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.DrawIconEx(
            memory_dc, 0, 0, info.hIcon, ICON_SIZE, ICON_SIZE, 0, None, 0x0003
        ):
            raise OSError("DrawIconEx failed")
        pixels = ctypes.string_at(bits, ICON_SIZE * ICON_SIZE * 4)
        return Image.frombuffer(
            "RGBA", (ICON_SIZE, ICON_SIZE), pixels, "raw", "BGRA", 0, 1
        ).copy()
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)
        user32.DestroyIcon(info.hIcon)
