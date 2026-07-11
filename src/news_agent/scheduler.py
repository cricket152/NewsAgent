"""Windows Task Scheduler management for the news-agent worker process.

Registers / unregisters daily scheduled tasks (default 06:00 and 18:00) that
invoke ``pythonw.exe worker.py`` directly — the Task Scheduler triggers the
Worker process independently of the main GUI process.  PID-lock overlap
protection is handled by ``worker.py`` itself.

Pure CLI module: never imports GUI libraries (webview / tkinter / pystray).
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from news_agent.config import load_config
from news_agent.logging_setup import get_logger

logger = get_logger()

TASK_NAME_PREFIX = "NewsAgentWorker"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_pythonw() -> Path:
    """Return the absolute path to a non-console Python executable.

    - **PyInstaller-frozen** exe: ``sys.executable`` as-is (already no-console).
    - **Development** CPython: derive ``pythonw.exe`` from ``sys.executable``.
      Falls back to ``sys.executable`` with a warning if ``pythonw.exe`` is
      missing.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable)

    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.is_file():
        return pythonw

    logger.warning(
        "pythonw.exe not found, using python.exe (console may flash)"
    )
    return exe


def _resolve_worker_py() -> Path:
    """Return absolute path to ``worker.py`` (sibling of this module)."""
    return (Path(__file__).parent / "worker.py").resolve()


def _build_task_xml(
    task_name: str,
    pythonw_path: Path,
    worker_py_path: Path,
    schedule_time: str,
) -> str:
    """Build a Task Scheduler XML definition string for a daily trigger task.

    The XML enables ``StartWhenAvailable`` (so a missed 06:00 run fires at
    next boot), ``ExecutionTimeLimit=PT15M``, ``MultipleInstancesPolicy=IgnoreNew``,
    and allows execution on battery power.
    """
    hour, minute = schedule_time.split(":")
    start_boundary = f"2020-01-01T{hour.zfill(2)}:{minute.zfill(2)}:00"

    cmd = _xml_escape(str(pythonw_path))
    args = _xml_escape(str(worker_py_path))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Task version="1.2"'
        ' xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Author>NewsAgent</Author>\n"
        f"    <Description>NewsAgent Worker — Daily news fetch at {schedule_time}</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <CalendarTrigger>\n"
        f"      <StartBoundary>{start_boundary}</StartBoundary>\n"
        "      <ScheduleByDay>\n"
        "        <DaysInterval>1</DaysInterval>\n"
        "      </ScheduleByDay>\n"
        "    </CalendarTrigger>\n"
        "  </Triggers>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>\n"
        "    <Priority>7</Priority>\n"
        "  </Settings>\n"
        "  <Actions Context=\"Author\">\n"
        "    <Exec>\n"
        f"      <Command>{cmd}</Command>\n"
        f"      <Arguments>\"{args}\"</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>"
    )


def _build_task_name(schedule_time: str) -> str:
    """Return ``NewsAgentWorker_HH:MM`` for a given ``HH:MM`` time string."""
    return f"{TASK_NAME_PREFIX}_{schedule_time}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_worker_tasks(schedule_times: list[str] | None = None) -> bool:
    """Register daily Windows Task Scheduler entries for the Worker process.

    Creates one scheduled task per *schedule_times* entry using XML-based
    registration (so ``StartWhenAvailable=True`` and other advanced settings
    are honoured).

    Args:
        schedule_times: ``HH:MM`` strings, e.g. ``["06:00", "18:00"]``.
            Defaults to ``config.worker_schedule``.

    Returns:
        ``True`` if every task was registered successfully.
    """
    if schedule_times is None:
        try:
            config = load_config()
            schedule_times = list(config.worker_schedule)
        except Exception:
            logger.warning(
                "Could not load config, using default schedule", exc_info=True
            )
            schedule_times = ["06:00", "18:00"]

    pythonw_path = _resolve_pythonw()
    worker_py_path = _resolve_worker_py()

    all_ok = True
    for schedule_time in schedule_times:
        task_name = _build_task_name(schedule_time)
        xml_content = _build_task_xml(
            task_name, pythonw_path, worker_py_path, schedule_time
        )

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".xml",
                delete=False,
                encoding="utf-8",
            ) as f:
                f.write(xml_content)
                tmp_path = Path(f.name)

            result = subprocess.run(
                [
                    "schtasks",
                    "/Create",
                    "/XML",
                    str(tmp_path),
                    "/TN",
                    task_name,
                    "/F",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )

            if result.returncode == 0:
                logger.info("Registered task %s at %s", task_name, schedule_time)
            else:
                logger.error(
                    "Failed to register task %s: %s",
                    task_name,
                    result.stderr.strip() or result.stdout.strip(),
                )
                all_ok = False

        except FileNotFoundError:
            logger.error("schtasks.exe not found — not on Windows?")
            return False
        except subprocess.TimeoutExpired:
            logger.error("schtasks timed out for task %s", task_name)
            all_ok = False
        except Exception:
            logger.exception("Failed to register task %s", task_name)
            all_ok = False
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    return all_ok


def unregister_worker_tasks() -> bool:
    """Remove all NewsAgentWorker scheduled tasks.  **Idempotent.**

    Returns:
        ``True`` even if the tasks were already absent (the goal — no
        worker tasks — is already satisfied).
    """
    # Discover which task names to delete: try config, fall back to defaults
    try:
        config = load_config()
        schedule_times = list(config.worker_schedule)
    except Exception:
        schedule_times = ["06:00", "18:00"]

    all_ok = True
    for schedule_time in schedule_times:
        task_name = _build_task_name(schedule_time)
        try:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", task_name, "/F"],
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
                check=True,
            )
            logger.info("Unregistered task %s", task_name)
        except FileNotFoundError:
            logger.warning("schtasks.exe not found — cannot unregister")
            return True  # idempotent
        except subprocess.TimeoutExpired:
            logger.error("schtasks timed out for task %s", task_name)
            all_ok = False
        except subprocess.CalledProcessError:
            # Task doesn't exist — that's the desired state
            logger.debug("Task %s not found (already removed)", task_name)
        except Exception:
            logger.exception("Failed to unregister task %s", task_name)
            all_ok = False

    return all_ok


def is_worker_registered() -> bool:
    """Check whether **any** NewsAgentWorker task exists in Task Scheduler.

    Returns:
        ``True`` if at least one worker task is registered.
    """
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
    except FileNotFoundError:
        logger.warning("schtasks.exe not found")
        return False
    except subprocess.TimeoutExpired:
        logger.error("schtasks timed out during query")
        return False

    if result.returncode != 0:
        return False

    try:
        reader = csv.reader(io.StringIO(result.stdout))
        header = next(reader, None)
        if header is None:
            return False
        try:
            name_col = header.index("TaskName")
        except ValueError:
            return False
        for row in reader:
            if len(row) > name_col and TASK_NAME_PREFIX in row[name_col]:
                return True
    except Exception:
        logger.warning("Failed to parse schtasks query output", exc_info=True)

    return False


def get_worker_tasks() -> list[dict[str, str]]:
    """Return details for each registered NewsAgentWorker task.

    Returns:
        List of ``{"name": str, "status": str, "next_run": str,
        "schedule": str}`` dicts.  Empty list on failure or when no
        worker tasks are registered.
    """
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
    except Exception:
        logger.warning("Failed to query schtasks", exc_info=True)
        return []

    if result.returncode != 0:
        return []

    tasks: list[dict[str, str]] = []
    try:
        reader = csv.reader(io.StringIO(result.stdout))
        header = next(reader, None)
        if header is None:
            return []

        col_map = {name: idx for idx, name in enumerate(header)}
        name_idx = col_map.get("TaskName")
        status_idx = col_map.get("Status")
        next_run_idx = col_map.get("Next Run Time")

        if name_idx is None:
            return []

        for row in reader:
            if len(row) <= name_idx:
                continue
            raw_name: str = row[name_idx]
            if TASK_NAME_PREFIX not in raw_name:
                continue

            task_name = raw_name.strip("\\").strip('"')
            status = (
                row[status_idx].strip('"')
                if status_idx is not None and len(row) > status_idx
                else "Unknown"
            )
            next_run = (
                row[next_run_idx].strip('"')
                if next_run_idx is not None and len(row) > next_run_idx
                else "N/A"
            )

            # Derive schedule label from task name: "NewsAgentWorker_06:00" → "06:00"
            time_part = task_name[len(TASK_NAME_PREFIX) :].lstrip("_")
            schedule = f"Daily at {time_part}" if time_part else "Daily"

            tasks.append(
                {
                    "name": task_name,
                    "status": status,
                    "next_run": next_run,
                    "schedule": schedule,
                }
            )
    except Exception:
        logger.warning("Failed to parse schtasks query output", exc_info=True)

    return tasks


# ---------------------------------------------------------------------------
# CLI (no side-effects on import)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NewsAgent Task Scheduler")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--register", action="store_true", help="Register worker tasks"
    )
    group.add_argument(
        "--unregister", action="store_true", help="Unregister worker tasks"
    )
    group.add_argument(
        "--status", action="store_true", help="Print detailed task status"
    )
    args = parser.parse_args()

    if args.register:
        ok = register_worker_tasks()
        print("Registration", "succeeded" if ok else "failed (see log)")
    elif args.unregister:
        ok = unregister_worker_tasks()
        print("Unregistration", "succeeded" if ok else "had issues (see log)")
    else:
        # Default / --status: print current state
        print(f"Any worker registered: {is_worker_registered()}")
        for task in get_worker_tasks():
            print(
                f"  {task['name']}: status={task['status']},"
                f" next={task['next_run']}, schedule={task['schedule']}"
            )
