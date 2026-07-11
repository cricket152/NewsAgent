"""Clean uninstall flow for the NewsAgent desktop application.

Removes four categories of artefacts in order:
1. Autostart registration (HKCU Run key) via ``news_agent.autostart.disable_autostart()``
2. Task Scheduler worker entries via ``news_agent.scheduler.unregister_worker_tasks()``
3. Start Menu shortcut (``%APPDATA%/Microsoft/Windows/Start Menu/Programs/NewsAgent.lnk``)
4. Application data directory (``%APPDATA%/news-agent/``) — DB, config, logs, caches

Every step is attempted even if earlier steps fail.  The module provides both an
interactive ``uninstall()`` (asks ``input()``) and a programmatic ``uninstall_quiet()``.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from news_agent.logging_setup import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _get_appdata_path() -> Path:
    """Return ``%APPDATA%/news-agent/`` directory path."""
    return Path(os.environ["APPDATA"]) / "news-agent"


def _get_shortcut_path() -> Path:
    """Return Start Menu NewsAgent shortcut path (may not exist)."""
    return (
        Path(os.environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "NewsAgent.lnk"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_installed() -> bool:
    """Return ``True`` if any NewsAgent artefact is present on this system.

    Checks three signals:
    * Autostart Run key value (``is_autostart_enabled``)
    * At least one NewsAgentWorker Task Scheduler task (``is_worker_registered``)
    * ``%APPDATA%/news-agent/`` directory exists on disk
    """
    # 1. Registry Run key
    try:
        from news_agent.autostart import is_autostart_enabled

        if is_autostart_enabled():
            return True
    except Exception:
        logger.debug("is_installed: autostart check failed", exc_info=True)

    # 2. Task Scheduler worker tasks
    try:
        from news_agent.scheduler import is_worker_registered

        if is_worker_registered():
            return True
    except Exception:
        logger.debug("is_installed: scheduler check failed", exc_info=True)

    # 3. AppData directory on disk
    if _get_appdata_path().exists():
        return True

    return False


# ---------------------------------------------------------------------------
# Internal: step collection & execution
# ---------------------------------------------------------------------------


def _collect_steps() -> list[dict]:
    """Build the list of planned uninstall steps (not yet executed).

    Each step dict has keys: ``action``, ``target``, ``ok`` (initially False),
    ``error`` (initially None).
    """
    steps: list[dict] = []

    steps.append(
        {
            "action": "disable_autostart",
            "target": r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run\NewsAgent",
            "ok": False,
            "error": None,
        }
    )

    steps.append(
        {
            "action": "unregister_tasks",
            "target": "Task Scheduler NewsAgentWorker_*",
            "ok": False,
            "error": None,
        }
    )

    shortcut_path = _get_shortcut_path()
    steps.append(
        {
            "action": "delete_shortcut",
            "target": str(shortcut_path),
            "ok": False,
            "error": None,
        }
    )

    appdata_path = _get_appdata_path()
    steps.append(
        {
            "action": "delete_appdata",
            "target": str(appdata_path),
            "ok": False,
            "error": None,
        }
    )

    return steps


def _execute_steps(steps: list[dict]) -> list[dict]:
    """Execute every uninstall step in-place, updating ``ok`` and ``error``.

    Returns the same list for convenience.
    """
    logger.info("Starting uninstall sequence…")

    # --- 1. Disable autostart (Registry Run key) ---------------------------
    try:
        from news_agent.autostart import disable_autostart

        ok = disable_autostart()
        steps[0]["ok"] = ok
        if not ok:
            steps[0]["error"] = "disable_autostart() returned False"
        else:
            logger.info("Autostart disabled")
    except Exception as exc:
        steps[0]["error"] = str(exc)
        logger.error("Failed to disable autostart: %s", exc)

    # --- 2. Unregister Task Scheduler worker tasks -------------------------
    try:
        from news_agent.scheduler import unregister_worker_tasks

        ok = unregister_worker_tasks()
        steps[1]["ok"] = ok
        if not ok:
            steps[1]["error"] = (
                "unregister_worker_tasks() returned False "
                "(some tasks may have had issues)"
            )
        else:
            logger.info("Worker tasks unregistered")
    except Exception as exc:
        steps[1]["error"] = str(exc)
        logger.error("Failed to unregister worker tasks: %s", exc)

    # --- 3. Delete Start Menu shortcut -------------------------------------
    shortcut_path = _get_shortcut_path()
    try:
        shortcut_path.unlink(missing_ok=True)
        steps[2]["ok"] = True
        logger.info("Start Menu shortcut deleted: %s", shortcut_path)
    except Exception as exc:
        steps[2]["error"] = str(exc)
        logger.error("Failed to delete shortcut %s: %s", shortcut_path, exc)

    # --- 4. Delete %APPDATA%/news-agent/ directory -------------------------
    appdata_path = _get_appdata_path()
    try:
        shutil.rmtree(appdata_path, ignore_errors=True)
        steps[3]["ok"] = True
        logger.info("AppData directory removed: %s", appdata_path)
    except Exception as exc:
        steps[3]["error"] = str(exc)
        logger.error("Failed to remove AppData directory %s: %s", appdata_path, exc)

    all_ok = all(s["ok"] for s in steps)
    logger.info("Uninstall complete – success=%s", all_ok)

    return steps


# ---------------------------------------------------------------------------
# Public uninstall functions
# ---------------------------------------------------------------------------


def uninstall() -> dict:
    """Interactive uninstall: print planned actions, ask for confirmation.

    Returns:
        ``{"steps": [...], "success": bool}`` summary dict.  Each step is
        ``{"action": str, "target": str, "ok": bool, "error": str | None}``.
    """
    steps = _collect_steps()

    print("The following items will be removed:\n")
    for i, step in enumerate(steps, 1):
        print(f"  {i}. [{step['action']}] {step['target']}")
    print()

    try:
        answer = input("Proceed with uninstall? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer not in ("y", "yes"):
        print("Uninstall cancelled.")
        for s in steps:
            s["error"] = "cancelled by user"
        return {"steps": steps, "success": False}

    steps = _execute_steps(steps)
    return {"steps": steps, "success": all(s["ok"] for s in steps)}


def uninstall_quiet() -> dict:
    """Programmatic uninstall — no prompts, execute all steps immediately.

    Returns:
        ``{"steps": [...], "success": bool}`` summary dict.  Each step is
        ``{"action": str, "target": str, "ok": bool, "error": str | None}``.
    """
    steps = _collect_steps()
    _execute_steps(steps)
    return {"steps": steps, "success": all(s["ok"] for s in steps)}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NewsAgent Uninstaller")
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation (quiet mode)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned steps without making any changes",
    )
    args = parser.parse_args()

    if args.dry_run:
        steps = _collect_steps()
        print("DRY RUN — the following would be removed:\n")
        for i, step in enumerate(steps, 1):
            print(f"  {i}. [{step['action']}] {step['target']}")
        print("\nNo changes were made.")
        raise SystemExit(0)

    result = uninstall_quiet() if args.yes else uninstall()

    # Print summary
    print("\nUninstall summary:")
    all_ok = True
    for step in result["steps"]:
        status = "OK" if step["ok"] else "FAIL"
        if step.get("error"):
            print(f"  [{step['action']}] {status}: {step['error']}")
        else:
            print(f"  [{step['action']}] {status}")

    print(
        f"\nOverall: {'SUCCESS' if result['success'] else 'FAILED (some steps had issues)'}"
    )
    raise SystemExit(0 if result["success"] else 1)
