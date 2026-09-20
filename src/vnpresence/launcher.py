"""Launching a visual novel and following the process that actually runs it.

Why this is not just ``Popen.wait()``: a large share of visual novels are
started through an intermediate process - Locale Emulator, a Japanese-locale
wrapper, a config/launcher .exe, or a packer stub. That first process exits
almost immediately while the real game keeps running under a different PID, so
naively waiting on it would end the presence a second after it appeared.

Strategy:
1. Start the configured executable.
2. Note every child/descendant it spawns.
3. If the started process dies within ``launcher_grace`` seconds, look for a
   surviving process that matches (in order): an explicit ``process_names``
   entry, the same executable path, or any executable inside the game folder.
4. Track whatever we found, and end the session when it is gone.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from .emulators import is_rom, matches_window, rom_kind
from .models import GameProfile
from .titlebar import titles_for

log = logging.getLogger(__name__)


class LaunchError(RuntimeError):
    pass


@dataclass
class TrackedGame:
    """A running game we follow until it exits."""

    pid: int
    name: str
    started_at: float

    def is_running(self) -> bool:
        try:
            process = psutil.Process(self.pid)
        except psutil.NoSuchProcess:
            return False
        try:
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except psutil.AccessDenied:
            # An elevated game we cannot inspect. It exists, so it is running.
            return True
        except psutil.NoSuchProcess:
            return False


#: How far up the parent chain :func:`belongs_to` will look. Deep enough for a
#: game that puts its window in a child process, short enough that it can never
#: wander up to explorer.exe and call the whole desktop part of the game.
MAX_ANCESTRY = 4


def belongs_to(pid: int | None, owner: int | None, *, depth: int = MAX_ANCESTRY) -> bool:
    """Is ``pid`` the game ``owner`` - or a process the game started?

    Asked of the window in front. A fair number of games are one process with
    one window, but plenty are not: an engine that spawns a renderer, a browser
    -based novel in its own child process, an emulator that opens its display
    separately. Comparing pids alone calls all of those "not the game", and
    then stops counting reading time while the reader is reading.
    """
    if pid is None or owner is None:
        return False
    if pid == owner:
        return True
    try:
        process = psutil.Process(pid)
        for _ in range(depth):
            process = process.parent()
            if process is None:
                return False
            if process.pid == owner:
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    return False


#: Windows: CreateProcess cannot elevate, so a game whose manifest asks for
#: administrator rights fails with this error until we go through the shell.
ERROR_ELEVATION_REQUIRED = 740

#: "%1 is not a valid Win32 application" - almost always a ROM or a disc image
#: handed over as if it were the game's executable.
ERROR_BAD_EXE_FORMAT = 193


class ElevatedLaunch:
    """Stand-in for Popen when the game was started through a UAC prompt.

    ShellExecute gives us no process handle, so we report "already exited" and
    let the process scan in :func:`resolve_tracked_process` find the game.
    """

    pid = -1
    needs_uac = True

    def poll(self) -> int:
        return 0


def launch(profile: GameProfile) -> subprocess.Popen | ElevatedLaunch:
    """Start the game executable, elevating through UAC if it demands it."""
    if not profile.path:
        raise LaunchError(f"{profile.title}: no executable path configured")
    exe = Path(profile.path).expanduser()
    if not exe.exists():
        raise LaunchError(f"executable not found: {exe}")
    if is_rom(exe):
        # Caught here rather than left to Windows, which answers "%1 is not a
        # valid Win32 application" - true, unhelpful, and the first thing a
        # reader sees after doing something entirely reasonable.
        raise LaunchError(
            f"{exe.name} is a {rom_kind(exe)}, not a program Windows can run.\n"
            "An emulated game is added by pointing at the emulator and saying "
            "which game it is loading:\n"
            f'  vnpresence add "C:\\path\\to\\Ryujinx.exe" --rom "{exe}"\n'
            "See docs/emulators or the Emulated visual novels section of the README."
        )

    cwd = profile.working_dir or str(exe.parent)
    command = [str(exe), *profile.args]
    log.info("launching %s", " ".join(command))
    kwargs: dict = {"cwd": cwd}
    if sys.platform == "win32":  # keep the game detached from our console
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        return subprocess.Popen(command, **kwargs)  # noqa: S603
    except OSError as exc:
        if getattr(exc, "winerror", None) == ERROR_ELEVATION_REQUIRED:
            return _launch_elevated(exe, profile.args, cwd)
        if getattr(exc, "winerror", None) == ERROR_BAD_EXE_FORMAT:
            raise LaunchError(
                f"{exe.name} is not a program Windows can run. If it is a game "
                "for an emulator, point at the emulator instead and pass the "
                "game with --rom; if it is a 16-bit or a non-Windows build, "
                "there is nothing VNPresence can do with it."
            ) from exc
        raise LaunchError(f"could not start {exe.name}: {exc}") from exc


def _launch_elevated(exe: Path, args: list[str], cwd: str) -> ElevatedLaunch:
    """Start a game that requires administrator rights (shows a UAC prompt)."""
    import ctypes  # Windows only, imported lazily

    params = subprocess.list2cmdline(args) if args else None
    log.info("%s requires elevation; asking Windows for it", exe.name)
    result = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None, "runas", str(exe), params, cwd, 1
    )
    if result <= 32:  # anything <= 32 is a failure code, 5 = prompt refused
        raise LaunchError(
            f"{exe.name} needs administrator rights and Windows refused the request "
            f"(code {result}). Approve the UAC prompt when it appears, or run "
            "VNPresence itself as administrator."
        )
    return ElevatedLaunch()


def resolve_tracked_process(
    profile: GameProfile,
    process: subprocess.Popen,
    *,
    poll_interval: float = 0.5,
    now: float | None = None,
) -> TrackedGame | None:
    """Return the process to follow, surviving intermediate launchers."""
    started_at = now or time.time()
    grace = max(profile.launcher_grace, 1.0)
    if getattr(process, "needs_uac", False):
        # The user still has to click through the UAC prompt.
        grace = max(grace, 60.0)
    deadline = started_at + grace
    descendants = _watch_descendants(process.pid)

    while time.time() < deadline:
        if process.poll() is None:  # still alive: it is the game itself
            descendants |= _watch_descendants(process.pid)
            time.sleep(poll_interval)
            continue
        # The process we started has exited. Someone else may be the game now.
        candidate = _find_candidate(profile, descendants)
        if candidate is not None:
            log.info("following process %s (pid %s)", candidate.name(), candidate.pid)
            return TrackedGame(candidate.pid, candidate.name(), started_at)
        time.sleep(poll_interval)

    if process.poll() is None:
        name = Path(profile.path).name
        return TrackedGame(process.pid, name, started_at)

    candidate = _find_candidate(profile, descendants)
    if candidate is not None:
        return TrackedGame(candidate.pid, candidate.name(), started_at)
    return None


def find_running(profile: GameProfile) -> TrackedGame | None:
    """Find an already-running instance of the game (used by ``attach``)."""
    candidate = _find_candidate(profile, set())
    if candidate is None:
        return None
    try:
        return TrackedGame(candidate.pid, candidate.name(), candidate.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


# -- internals ------------------------------------------------------------
def _split_path(raw: str) -> tuple[str, str]:
    """Return (folder, file name), lowercased, for a Windows *or* POSIX path.

    Done by hand rather than with pathlib so that a Windows path is still split
    correctly when the code runs (or is tested) on another platform.
    """
    normalised = raw.replace("/", "\\")
    head, _, tail = normalised.rpartition("\\")
    return head.lower(), tail.lower()


def _watch_descendants(pid: int) -> set[int]:
    if pid < 0:  # an elevated launch gives us no handle to look under
        return set()
    try:
        parent = psutil.Process(pid)
        return {child.pid for child in parent.children(recursive=True)}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return set()


def _find_candidate(profile: GameProfile, descendants: set[int]) -> psutil.Process | None:
    wanted_names = {n.lower() for n in profile.process_names}
    #: An emulated game is identified by what its emulator has loaded, not by
    #: the emulator's own name or path - those are the same for every game.
    wanted_window = profile.window_match
    exe_path = Path(profile.path).expanduser() if profile.path else None
    game_dir, exe_name = _split_path(profile.path or "")

    by_name: psutil.Process | None = None
    by_exe_name: psutil.Process | None = None
    by_path: psutil.Process | None = None
    by_folder: psutil.Process | None = None
    by_descendant: psutil.Process | None = None

    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = process.info
            name = (info.get("name") or "").lower()
            exe = (info.get("exe") or "").lower()
            if wanted_names and name in wanted_names and by_name is None:
                by_name = process
            # An elevated game hides its exe path from us, but not its name.
            if exe_name and name == exe_name and by_exe_name is None:
                by_exe_name = process
            if exe_path and exe == str(exe_path).lower() and by_path is None:
                by_path = process
            if game_dir and exe.startswith(game_dir) and name != exe_name and by_folder is None:
                by_folder = process
            if info["pid"] in descendants and by_descendant is None:
                by_descendant = process
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if wanted_window:
        # Everything found so far only says "the emulator is running". Which
        # game it has loaded is in the window title, so nothing counts until
        # that agrees - otherwise one emulator answers for a whole library.
        for candidate in (by_name, by_exe_name, by_path, by_folder, by_descendant):
            if candidate is None:
                continue
            if matches_window(wanted_window, titles_for(candidate.pid)):
                return candidate
        return None

    # Order matters. `process_names` is what someone typed on purpose, and a
    # descendant of the process we started is ours by construction. After that
    # the full path identifies a game exactly, while a bare file name does not:
    # every Science Adventure release ships a launcher with the same name, so
    # name-matching alone happily returns a different novel's launcher. The
    # name is still worth trying last, because an elevated process hides its
    # path from us and the name is then all there is.
    return by_name or by_descendant or by_path or by_exe_name or by_folder
