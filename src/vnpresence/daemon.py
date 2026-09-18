"""Running the watcher in the background, and stopping it again.

Holding a terminal open just to keep the presence alive is a nuisance, so the
watcher can detach itself: it records its pid, the shell prompt comes straight
back, and ``vnpresence stop`` ends it later.

The record stores the process creation time as well as the pid, because
Windows reuses pids freely - without that check, ``stop`` could one day kill
whatever unrelated program inherited the number.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import psutil

from .config import config_dir

log = logging.getLogger(__name__)

DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000


def pid_file() -> Path:
    return config_dir() / "watcher.pid"


# -- the record -----------------------------------------------------------
def write_record(pid: int | None = None) -> Path:
    pid = pid or os.getpid()
    try:
        started = psutil.Process(pid).create_time()
    except psutil.Error:
        started = 0.0
    path = pid_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "started": started}), encoding="utf-8")
    return path


def read_record() -> dict | None:
    path = pid_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and "pid" in data else None
    except Exception:
        return None


def clear_record() -> None:
    try:
        pid_file().unlink(missing_ok=True)
    except OSError:  # pragma: no cover - permissions
        log.debug("could not remove %s", pid_file(), exc_info=True)


def running_pid() -> int | None:
    """The pid of a live background watcher, or None (clearing stale records)."""
    record = read_record()
    if record is None:
        return None
    pid = int(record.get("pid", 0))
    started = float(record.get("started", 0.0))
    try:
        process = psutil.Process(pid)
        if started and abs(process.create_time() - started) > 1.0:
            raise psutil.NoSuchProcess(pid)  # the pid was recycled
    except psutil.NoSuchProcess:
        clear_record()
        return None
    except psutil.AccessDenied:
        return pid  # it exists; we simply cannot inspect it
    return pid


# -- starting and stopping ------------------------------------------------
def spawn_background(extra_args: list[str] | None = None) -> int:
    """Start ``vnpresence watch`` detached from this terminal, return its pid."""
    command = _self_command(["watch", *(extra_args or [])])
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)  # noqa: S603
    return process.pid


def stop_background(timeout: float = 10.0) -> int | None:
    """Stop a background watcher. Returns the pid it stopped, or None."""
    pid = running_pid()
    if pid is None:
        return None
    try:
        process = psutil.Process(pid)
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            process.kill()
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        log.warning("not allowed to stop pid %s", pid)
        return None
    clear_record()
    return pid


def _self_command(args: list[str]) -> list[str]:
    """How to run VNPresence again: the frozen exe, or this interpreter."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return [sys.executable, *args]
    return [sys.executable, "-m", "vnpresence", *args]
