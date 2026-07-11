"""Tests for ``news_agent.uninstaller`` — clean uninstall flow (all mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from news_agent.uninstaller import is_installed, uninstall_quiet


class TestUninstallQuiet:
    def test_uninstall_quiet_all_steps_attempted(self) -> None:
        """All 4 uninstall steps are attempted."""
        with patch(
            "news_agent.autostart.disable_autostart", return_value=True
        ) as mock_auto:
            with patch(
                "news_agent.scheduler.unregister_worker_tasks", return_value=True
            ) as mock_sched:
                with patch("news_agent.uninstaller.shutil.rmtree") as mock_rmtree:
                    with patch("pathlib.Path.unlink"):
                        result = uninstall_quiet()

        assert "steps" in result
        # All 4 steps should be marked OK
        for step in result["steps"]:
            assert step["ok"] is True, f"Step {step['action']} failed: {step.get('error')}"

        mock_auto.assert_called_once()
        mock_sched.assert_called_once()
        mock_rmtree.assert_called_once()


class TestIsInstalled:
    def test_is_installed_autostart_true(self) -> None:
        """is_installed returns True when autostart is enabled."""
        with patch(
            "news_agent.autostart.is_autostart_enabled", return_value=True
        ):
            with patch(
                "news_agent.scheduler.is_worker_registered", return_value=False
            ):
                with patch(
                    "news_agent.uninstaller._get_appdata_path"
                ) as mock_appdata:
                    mock_path = MagicMock()
                    mock_path.exists.return_value = False
                    mock_appdata.return_value = mock_path
                    assert is_installed() is True

    def test_is_installed_scheduler_true(self) -> None:
        """is_installed returns True when scheduler is registered."""
        with patch(
            "news_agent.autostart.is_autostart_enabled", return_value=False
        ):
            with patch(
                "news_agent.scheduler.is_worker_registered", return_value=True
            ):
                with patch(
                    "news_agent.uninstaller._get_appdata_path"
                ) as mock_appdata:
                    mock_path = MagicMock()
                    mock_path.exists.return_value = False
                    mock_appdata.return_value = mock_path
                    assert is_installed() is True

    def test_is_installed_appdata_exists(self) -> None:
        """is_installed returns True when APPDATA dir exists."""
        with patch(
            "news_agent.autostart.is_autostart_enabled", return_value=False
        ):
            with patch(
                "news_agent.scheduler.is_worker_registered", return_value=False
            ):
                with patch(
                    "news_agent.uninstaller._get_appdata_path"
                ) as mock_appdata:
                    mock_path = MagicMock()
                    mock_path.exists.return_value = True
                    mock_appdata.return_value = mock_path
                    assert is_installed() is True

    def test_is_installed_none(self) -> None:
        """is_installed returns False when nothing is present."""
        with patch(
            "news_agent.autostart.is_autostart_enabled", return_value=False
        ):
            with patch(
                "news_agent.scheduler.is_worker_registered", return_value=False
            ):
                with patch(
                    "news_agent.uninstaller._get_appdata_path"
                ) as mock_appdata:
                    mock_path = MagicMock()
                    mock_path.exists.return_value = False
                    mock_appdata.return_value = mock_path
                    assert is_installed() is False
