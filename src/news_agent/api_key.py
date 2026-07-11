"""API key management via keyring + Windows Credential Manager with .env fallback.

Primary: keyring → Windows Credential Manager (``news-agent`` / ``deepseek_api_key``)
Fallback: %APPDATA%/news-agent/.env → ``DEEPSEEK_API_KEY=...``

NOTE: A restricted ACL on the .env file is recommended for production use
(e.g. ``icacls .env /inheritance:r /grant:r "%USERNAME%:(R)"``), but is not
enforced programmatically to avoid requiring administrator privileges.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import keyring
from dotenv import load_dotenv

KEYRING_SERVICE = "news-agent"
KEYRING_USERNAME = "deepseek_api_key"
ENV_FILE_NAME = ".env"
ENV_KEY_NAME = "DEEPSEEK_API_KEY"

_logger = logging.getLogger("news_agent")


def _env_file_path() -> Path:
    """Return the resolved path to the .env fallback file."""
    base = os.environ.get("APPDATA", str(Path.home() / ".config"))
    return Path(base) / "news-agent" / ENV_FILE_NAME


def get_api_key() -> str | None:
    """Retrieve the DeepSeek API key, trying keyring first then .env fallback.

    Returns:
        The API key string if found and non-empty, ``None`` if no key is
        configured.  Callers decide how to handle the missing-key case.
    """
    # 1. Try Windows Credential Manager via keyring
    try:
        key = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if key and key.strip():
            _logger.debug("API key loaded from keyring")
            return key.strip()
    except Exception:
        _logger.debug("keyring lookup failed, falling back to .env", exc_info=True)

    # 2. Try .env fallback
    env_path = _env_file_path()
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        key = os.environ.get(ENV_KEY_NAME)
        if key and key.strip():
            _logger.debug("API key loaded from .env fallback")
            return key.strip()

    _logger.debug("No API key found (checked keyring and .env)")
    return None


def set_api_key(key: str) -> None:
    """Store the API key in the system keyring (Windows Credential Manager).

    Args:
        key: The API key string to store. Trailing/leading whitespace is stripped.

    Raises:
        ValueError: If the key is empty after stripping whitespace.
    """
    trimmed = key.strip()
    if not trimmed:
        raise ValueError("API key cannot be empty")
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, trimmed)
    _logger.debug("API key stored in keyring")


def delete_api_key() -> None:
    """Remove the API key from the system keyring.

    If the key was already absent (``PasswordDeleteError``), the error is
    silently ignored — the desired state is already satisfied.

    If the .env fallback file still exists, a warning is emitted because
    the caller (e.g. an uninstaller) should delete the file separately.
    """
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        _logger.debug("API key deleted from keyring")
    except keyring.errors.PasswordDeleteError:
        _logger.debug("No API key in keyring to delete (already absent)")

    env_path = _env_file_path()
    if env_path.exists():
        _logger.warning(
            ".env fallback file still exists at %s — "
            "delete it separately to fully remove the key",
            env_path,
        )


def ensure_env_file_exists() -> Path:
    """Return the path to ``%APPDATA%/news-agent/.env``, creating it empty if missing.

    Intended for a future first-run setup flow that may populate the file later.
    """
    env_path = _env_file_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.touch(exist_ok=True)
    return env_path


# ---------------------------------------------------------------------------
# Ad-hoc status check (does NOT print the actual key value)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

    key = get_api_key()
    if key is None:
        print("Status: No API key configured (checked keyring + .env)")
        sys.exit(1)

    # Determine which source supplied the key without printing the key itself.
    try:
        kring_val = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if kring_val and kring_val.strip() == key:
            source = "keyring (Windows Credential Manager)"
        else:
            source = ".env fallback"
    except Exception:
        source = ".env fallback"

    print(f"Status: API key found via {source}")
