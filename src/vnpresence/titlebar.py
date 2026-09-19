"""Reading the titles of other programs' windows.

An emulator is one executable that runs hundreds of different games, so the
process name says nothing about what is being read. The window title does:
every emulator puts the loaded game in it, and most put its disc serial there
too.

Windows only, and deliberately dependency-free - ``ctypes`` talks to user32
directly rather than adding pywin32 to a project whose whole appeal is a single
.exe with nothing to install. Everywhere else this returns nothing, which the
callers treat as "no extra information", not as a failure.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

#: Titles shorter than this are chrome, not information ("", "PPSSPP").
MIN_TITLE = 3


def supported() -> bool:
    return sys.platform == "win32"


def titles_by_pid() -> dict[int, list[str]]:
    """Every visible window title on screen, grouped by the process that owns it.

    One pass over the window list serves the whole library, the same way one
    pass over the process table does - a reader with thirty games should not
    cost thirty enumerations.
    """
    if not supported():
        return {}
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # pragma: no cover - not Windows
        return {}

    found: dict[int, list[str]] = {}
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        callback_type = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def visit(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length < MIN_TITLE:
                    return True
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                found.setdefault(int(pid.value), []).append(buffer.value)
            except Exception:  # a window that died mid-enumeration
                pass
            return True

        user32.EnumWindows(callback_type(visit), 0)
    except Exception:  # pragma: no cover - defensive
        log.debug("could not enumerate windows", exc_info=True)
        return {}
    return found


def titles_for(pid: int) -> list[str]:
    """The window titles belonging to one process."""
    return titles_by_pid().get(pid, [])


def foreground_pid() -> int | None:
    """Which process owns the window being used right now.

    ``None`` means "no idea" - not Windows, or the call failed - and callers
    must read it that way. Treating an unknown as "not focused" would quietly
    stop counting anyone's reading time on a platform where this cannot work.
    """
    if not supported():
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:  # pragma: no cover - defensive
        log.debug("could not read the foreground window", exc_info=True)
        return None
