# Main-process module — Windows-only, never import from worker.py
"""Windows Registry autostart management (HKCU Run key, pythonw.exe, --autostart flag).

Uses the Registry Run key (NOT the Startup folder) to avoid the
up-to-10-minute SmartScreen delay on Windows 10/11.  The registry value
invokes the app via **pythonw.exe** (no console flash) with ``--autostart``.
"""

from __future__ import annotations

import shlex
import sys
import winreg
from pathlib import Path

from news_agent.logging_setup import get_logger

logger = get_logger()

APP_NAME = "NewsAgent"
VALUE_NAME = "NewsAgent"
RUN_KEY_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
STARTUP_APPROVED_PATH = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_pythonw() -> Path:
    """Return the absolute path to a non-console Python executable.

    - PyInstaller-frozen exe: return ``sys.executable`` as-is (already no-console).
    - Normal CPython install: derive ``pythonw.exe`` from ``sys.executable``.
      Falls back to ``sys.executable`` with a warning if ``pythonw.exe`` is missing.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable)

    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.is_file():
        return pythonw

    logger.warning(
        "pythonw.exe not found, using python.exe (console may flash on boot)"
    )
    return exe


def _resolve_main_py() -> Path:
    """Return absolute path to ``main.py`` (sibling of this module)."""
    return (Path(__file__).parent / "main.py").resolve()


def _build_command(pythonw: Path, main_py: Path) -> str:
    """Build the Run-key value string: ``"<pythonw>" "<main.py>" --autostart``.

    Paths are always wrapped in double-quotes for safety, even when they
    contain no spaces.
    """
    return f'"{pythonw}" "{main_py}" --autostart'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enable_autostart() -> bool:
    """Write the NewsAgent autostart entry to HKCU Run and clear stale
    StartupApproved state.

    Returns:
        ``True`` on success, ``False`` if a registry error occurs.
    """
    try:
        pythonw = _resolve_pythonw()
        main_py = _resolve_main_py()
        command = _build_command(pythonw, main_py)

        # 1. Set the Run key value ------------------------------------------
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        )
        try:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        finally:
            winreg.CloseKey(key)

        # 2. Clear stale StartupApproved state (Windows "Enabled" toggle) ----
        try:
            approved_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                STARTUP_APPROVED_PATH,
                0,
                winreg.KEY_SET_VALUE,
            )
        except FileNotFoundError:
            logger.debug("StartupApproved\\Run key not present (normal)")
        else:
            try:
                winreg.DeleteValue(approved_key, VALUE_NAME)
                logger.debug("Cleared stale StartupApproved state")
            except FileNotFoundError:
                logger.debug("No stale StartupApproved entry to clear")
            finally:
                winreg.CloseKey(approved_key)

        logger.info("autostart enabled: %s", command)
        return True

    except OSError:
        logger.error("Failed to enable autostart", exc_info=True)
        return False


def disable_autostart() -> bool:
    """Remove the NewsAgent autostart entry from HKCU Run.

    Returns:
        ``True`` if the entry was removed or was already absent;
        ``False`` on unexpected registry errors.
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        )
    except FileNotFoundError:
        logger.debug("Run key not present — autostart already disabled")
        return True

    try:
        try:
            winreg.DeleteValue(key, VALUE_NAME)
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        logger.debug("autostart not enabled (value missing)")
        return True
    except OSError:
        logger.error("Failed to disable autostart", exc_info=True)
        return False

    logger.info("autostart disabled")
    return True


def is_autostart_enabled() -> bool:
    """Check whether the NewsAgent Run key value is present and non-empty.

    Returns:
        ``True`` if a non-empty autostart value exists, ``False`` otherwise.
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ
        )
    except FileNotFoundError:
        return False

    try:
        try:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value and value.strip())
        except FileNotFoundError:
            return False
    except OSError:
        logger.warning("Failed to read autostart registry value", exc_info=True)
        return False
    finally:
        winreg.CloseKey(key)


def get_autostart_command() -> tuple[str, str, str] | None:
    """Return the stored autostart command components, if any.

    Returns:
        ``(pythonw_path, script_path, extra_args_string)`` on success, e.g.
        ``("C:\\...\\pythonw.exe", "C:\\...\\main.py", "--autostart")``.
        ``None`` if autostart is not enabled or the stored value cannot be
        parsed.
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ
        )
    except FileNotFoundError:
        return None

    try:
        try:
            raw, _ = winreg.QueryValueEx(key, VALUE_NAME)
        except FileNotFoundError:
            return None
    except OSError:
        logger.warning("Failed to read autostart registry value", exc_info=True)
        return None
    finally:
        winreg.CloseKey(key)

    logger.debug("stored command: %s", raw)

    try:
        parts = shlex.split(raw.strip())
    except ValueError:
        logger.warning("Could not parse stored autostart command: %r", raw)
        return None

    if len(parts) < 2:
        return None

    pythonw_path = parts[0]
    script_path = parts[1]
    extra_args = " ".join(parts[2:]) if len(parts) > 2 else ""

    return (pythonw_path, script_path, extra_args)


# ---------------------------------------------------------------------------
# Smoke test (no side-effects — does NOT write to the registry)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(is_autostart_enabled())
    print(get_autostart_command())
    print("OK")
