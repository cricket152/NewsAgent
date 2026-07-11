"""Tests for ``news_agent.scheduler`` — Task Scheduler (mocked subprocess)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from news_agent.scheduler import (
    is_worker_registered,
    register_worker_tasks,
    unregister_worker_tasks,
)


class TestRegister:
    def test_register_worker_tasks_calls_schtasks(self, mock_subprocess: MagicMock) -> None:
        """register_worker_tasks calls schtasks /Create twice for 2 times."""
        mock_subprocess.return_value = MagicMock(returncode=0)

        with patch("news_agent.scheduler._resolve_pythonw", return_value="pythonw.exe"):
            with patch("news_agent.scheduler._resolve_worker_py", return_value="worker.py"):
                result = register_worker_tasks(["06:00", "18:00"])

        assert result is True
        assert mock_subprocess.call_count == 2
        # Both calls should be schtasks /Create /XML
        for c in mock_subprocess.call_args_list:
            args = c[0][0]
            assert "schtasks" in args[0]
            assert "/Create" in args


class TestUnregister:
    def test_unregister_worker_tasks_calls_schtasks_delete(
        self, mock_subprocess: MagicMock
    ) -> None:
        """unregister_worker_tasks calls schtasks /Delete twice."""
        mock_subprocess.return_value = MagicMock(returncode=0)

        result = unregister_worker_tasks()

        assert result is True
        assert mock_subprocess.call_count == 2
        for c in mock_subprocess.call_args_list:
            args = c[0][0]
            assert "schtasks" in args[0]
            assert "/Delete" in args

    def test_unregister_idempotent_on_error(self, mock_subprocess: MagicMock) -> None:
        """When schtasks raises CalledProcessError, returns True (idempotent)."""
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "schtasks")

        result = unregister_worker_tasks()
        assert result is True


class TestIsRegistered:
    def test_is_worker_registered_true(self, mock_subprocess: MagicMock) -> None:
        """Returns True when CSV output contains NewsAgentWorker."""
        mock_result = MagicMock(returncode=0)
        mock_result.stdout = "TaskName\r\nNewsAgentWorker_06:00\r\n"
        mock_subprocess.return_value = mock_result

        result = is_worker_registered()
        assert result is True

    def test_is_worker_registered_false(self, mock_subprocess: MagicMock) -> None:
        """Returns False when no NewsAgentWorker in output."""
        mock_result = MagicMock(returncode=0)
        mock_result.stdout = "TaskName\r\nSomeOtherTask\r\n"
        mock_subprocess.return_value = mock_result

        result = is_worker_registered()
        assert result is False
