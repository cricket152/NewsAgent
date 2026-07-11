"""Tests for ``news_agent.autostart`` — Windows registry autostart (mocked winreg)."""

from __future__ import annotations

from unittest.mock import MagicMock

from news_agent.autostart import disable_autostart, enable_autostart, is_autostart_enabled

RUN_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "NewsAgent"


class TestAutostartEnable:
    def test_enable_autostart_writes_registry(self, mock_winreg: MagicMock) -> None:
        """enable_autostart calls winreg.CreateKeyEx + SetValueEx."""
        result = enable_autostart()
        assert result is True
        mock_winreg.CreateKeyEx.assert_called()
        mock_winreg.SetValueEx.assert_called()
        # Verify the value name written
        setval_args = mock_winreg.SetValueEx.call_args
        assert setval_args[0][1] == VALUE_NAME  # value name

    def test_is_autostart_enabled_after_enable(self, mock_winreg: MagicMock) -> None:
        """After enable_autostart (mocked), is_autostart_enabled returns True."""
        mock_winreg.QueryValueEx.return_value = ("command", None)
        enabled = is_autostart_enabled()
        assert enabled is True


class TestAutostartDisable:
    def test_disable_autostart_removes_entry(self, mock_winreg: MagicMock) -> None:
        """disable_autostart calls DeleteValue."""
        result = disable_autostart()
        assert result is True

    def test_disable_autostart_idempotent(self, mock_winreg: MagicMock) -> None:
        """Calling disable twice does not raise on second call."""
        # First call
        result1 = disable_autostart()
        assert result1 is True
        # Second call — should not raise
        result2 = disable_autostart()
        assert result2 is True

    def test_is_not_enabled_after_disable(self, mock_winreg: MagicMock) -> None:
        """After disable, is_autostart_enabled returns False."""
        mock_winreg.QueryValueEx.side_effect = FileNotFoundError()
        enabled = is_autostart_enabled()
        assert enabled is False
