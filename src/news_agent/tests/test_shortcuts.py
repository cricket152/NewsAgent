"""Tests for user-managed application shortcuts."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from news_agent.chat_bridge import ChatBridge
from news_agent.shortcuts import (
    add_shortcut,
    delete_shortcut,
    launch_shortcut,
    list_shortcuts_for_ui,
    load_shortcuts,
)
from news_agent.viewer import render_html


def _make_executable(tmp_path: Path, name: str = "Sample App.exe") -> Path:
    executable = tmp_path / name
    executable.write_bytes(b"MZ")
    return executable


def test_add_list_delete_shortcut(tmp_path: Path) -> None:
    config_path = tmp_path / "shortcuts.json"
    executable = _make_executable(tmp_path)

    added = add_shortcut(executable, path=config_path)
    listed = list_shortcuts_for_ui(config_path)

    assert added["name"] == "Sample App"
    assert "path" not in added
    assert listed[0]["id"] == added["id"]
    assert "path" not in listed[0]
    assert listed[0]["available"] is True
    assert delete_shortcut(added["id"], config_path) is True
    assert load_shortcuts(config_path) == []


def test_add_shortcut_rejects_duplicate_and_unsupported_file(tmp_path: Path) -> None:
    config_path = tmp_path / "shortcuts.json"
    executable = _make_executable(tmp_path)
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("not an app", encoding="utf-8")

    add_shortcut(executable, path=config_path)
    with pytest.raises(ValueError, match="已在快捷入口"):
        add_shortcut(executable, path=config_path)
    with pytest.raises(ValueError, match="仅支持"):
        add_shortcut(unsupported, path=config_path)


def test_load_shortcuts_ignores_invalid_entries(tmp_path: Path) -> None:
    config_path = tmp_path / "shortcuts.json"
    config_path.write_text(
        json.dumps(
            [
                {"id": "ok", "name": "Valid", "path": "C:\\Apps\\Valid.exe"},
                {"id": "bad", "name": "Text", "path": "C:\\Apps\\note.txt"},
                {"name": "Missing ID", "path": "C:\\Apps\\Missing.exe"},
            ]
        ),
        encoding="utf-8",
    )

    assert load_shortcuts(config_path) == [
        {"id": "ok", "name": "Valid", "path": "C:\\Apps\\Valid.exe"}
    ]


def test_launch_shortcut_uses_only_saved_target(tmp_path: Path) -> None:
    config_path = tmp_path / "shortcuts.json"
    executable = _make_executable(tmp_path)
    added = add_shortcut(executable, path=config_path)

    with patch("news_agent.shortcuts.os.startfile", create=True) as startfile:
        result = launch_shortcut(added["id"], config_path)

    assert result["launched"] is True
    startfile.assert_called_once_with(str(executable))
    assert launch_shortcut("unknown", config_path)["launched"] is False


def test_bridge_chooses_lists_and_deletes_shortcut(tmp_path: Path) -> None:
    executable = _make_executable(tmp_path)

    class FakeWindow:
        def create_file_dialog(self, *args: object, **kwargs: object) -> list[str]:
            return [str(executable)]

    bridge = ChatBridge()
    bridge.set_window_provider(FakeWindow)

    added = bridge.choose_shortcut()
    listed = bridge.list_shortcuts()
    deleted = bridge.delete_shortcut(added["shortcut"]["id"])

    assert added["added"] is True
    assert listed[0]["name"] == "Sample App"
    assert deleted["deleted"] is True


def test_bridge_choose_shortcut_handles_cancel() -> None:
    class FakeWindow:
        def create_file_dialog(self, *args: object, **kwargs: object) -> None:
            return None

    bridge = ChatBridge()
    bridge.set_window_provider(FakeWindow)

    assert bridge.choose_shortcut() == {"added": False, "cancelled": True}


def test_list_shortcuts_includes_extracted_icon(tmp_path: Path) -> None:
    config_path = tmp_path / "shortcuts.json"
    executable = _make_executable(tmp_path)
    add_shortcut(executable, path=config_path)

    icon = "data:image/png;base64,cG5n"
    with patch("news_agent.shortcuts._icon_data_url", return_value=icon):
        listed = list_shortcuts_for_ui(config_path)

    assert listed[0]["icon"] == icon


def test_shortcut_template_has_no_letter_icon_fallback() -> None:
    html = render_html({})

    assert "shortcutMonogram" not in html
    assert "shortcut-monogram" not in html
    assert "shortcut-fallback-icon" in html


def test_template_refreshes_current_weather_without_refreshing_news() -> None:
    html = render_html({})

    assert "get_current_weather" in html
    assert "window.setInterval(refreshCurrentWeather, 10 * 60 * 1000)" in html
    assert "if (!document.hidden) refreshCurrentWeather()" in html
    assert "renderCurrentWeather" in html


def test_bridge_fetches_current_weather_for_configured_city() -> None:
    weather = {"current": {"temperature": 30.5}}
    bridge = ChatBridge(weather_city="Shanghai")

    with patch("news_agent.fetchers.weather.fetch_weather", return_value=weather) as fetch:
        result = bridge.get_current_weather()

    assert result == {"success": True, "weather": weather}
    fetch.assert_called_once_with("Shanghai", timeout=10.0)
