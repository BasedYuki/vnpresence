"""Noticing that nobody is there.

The window in front answers "is the reader in the game?", and that is most of
the question - but not all of it. A novel left open on the monitor while its
reader makes dinner is still the window in front, and counting that hour as
reading is exactly the kind of quietly wrong number this project is trying not
to produce.

Windows keeps the answer ready: :c:func:`GetLastInputInfo` reports when any
keyboard or mouse input last reached the system, whichever program received it.
That is all that is read here - not what was typed, not where, not by which
program. There is no key logging and nothing to log.

Windows only, and dependency-free for the same reason as ``titlebar``.
Everywhere else this says "no idea", which the callers read as "keep counting"
rather than as a reason to stop.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

#: GetTickCount is a 32-bit millisecond counter that wraps back to zero about
#: every 49.7 days of uptime. The subtraction below is done inside that width
#: on purpose, so a wrap between the last input and now produces the small
#: positive number it should rather than a 49-day idle time.
TICK_WIDTH = 0xFFFFFFFF

#: Half the counter. Microsoft warns that the last-input tick "is not
#: guaranteed to be incremental" and "might be less than the tick count of a
#: prior event", so it can sit a few milliseconds *ahead* of the tick we read
#: right after it. Wrapping arithmetic turns that tiny negative into roughly
#: 49.7 days, which would report a reader who just clicked as having left the
#: building. Anything in the top half of the range is that, not a real idle:
#: nobody has a machine untouched for twenty-five days with a novel open.
TICK_BACKWARDS = TICK_WIDTH // 2


def supported() -> bool:
    return sys.platform == "win32"


def since(last_input_tick: int, now_tick: int) -> float:
    """Seconds between two 32-bit tick counts, both hazards handled.

    Separated from the API call so the arithmetic - the part that is wrong in
    a lot of idle-detection code - can be tested anywhere, including on the
    Linux machines this project's tests usually run on.
    """
    elapsed = (now_tick - last_input_tick) & TICK_WIDTH
    if elapsed > TICK_BACKWARDS:
        return 0.0  # the last input is "ahead" of now: it just happened
    return elapsed / 1000.0


def idle_seconds() -> float | None:
    """Seconds since the last keyboard or mouse input anywhere on this machine.

    ``None`` means there is no way to tell - not Windows, or the call failed.

    Three things it cannot see, all worth knowing about: input that went to a
    program running as administrator when VNPresence is not, input in another
    Windows session (Microsoft is explicit that this is "session-specific ...
    for only the session that invoked the function", which is the right answer
    here - the reader's own desktop), and a game being advanced by something
    other than the keyboard and mouse. A novel in auto mode, read with a
    controller, is the case that matters for this project, which is why the
    threshold that uses this number is generous and can be switched off.
    """
    if not supported():
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class LastInputInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        user32.GetLastInputInfo.restype = wintypes.BOOL
        user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInputInfo)]
        kernel32.GetTickCount.restype = wintypes.DWORD
        kernel32.GetTickCount.argtypes = []

        info = LastInputInfo()
        info.cbSize = ctypes.sizeof(LastInputInfo)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        return since(int(info.dwTime), int(kernel32.GetTickCount()))
    except Exception:  # pragma: no cover - defensive
        log.debug("could not read the last input time", exc_info=True)
        return None
