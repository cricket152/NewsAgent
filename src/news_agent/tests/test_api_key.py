"""Tests for ``news_agent.api_key`` — keyring + .env fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from news_agent.api_key import (
    ENV_KEY_NAME,
    delete_api_key,
    ensure_env_file_exists,
    get_api_key,
    set_api_key,
)


class TestApiKeyRoundTrip:
    def test_get_set_delete_api_key_via_keyring(self, mock_keyring) -> None:
        mock_keyring.get_password.return_value = "test-api-key-123"

        # get
        key = get_api_key()
        assert key == "test-api-key-123"
        mock_keyring.get_password.assert_called_once()

        # set
        set_api_key("new-key-456")
        mock_keyring.set_password.assert_called_once()

        # delete
        delete_api_key()
        mock_keyring.delete_password.assert_called_once()


class TestApiKeyEnvFallback:
    def test_get_api_key_env_fallback(self, mock_keyring, tmp_path: Path) -> None:
        """When keyring raises, .env fallback is used."""
        mock_keyring.get_password.side_effect = RuntimeError("keyring unavailable")

        env_file = tmp_path / "AppData" / "news-agent" / ".env"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(f"{ENV_KEY_NAME}=env-fallback-key\n", encoding="utf-8")

        with patch("news_agent.api_key._env_file_path", return_value=env_file):
            # Need to clear os.environ first since dotenv may have already loaded
            import os
            os.environ.pop(ENV_KEY_NAME, None)
            key = get_api_key()
            assert key == "env-fallback-key"


class TestApiKeyValidation:
    def test_set_api_key_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            set_api_key("")

    def test_set_api_key_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            set_api_key("   \t  ")


class TestEnsureEnvFile:
    def test_ensure_env_file_exists_creates(self, tmp_path: Path) -> None:
        env_file = tmp_path / "AppData" / "news-agent" / ".env"
        with patch("news_agent.api_key._env_file_path", return_value=env_file):
            result = ensure_env_file_exists()
            assert result == env_file
            assert env_file.exists()
