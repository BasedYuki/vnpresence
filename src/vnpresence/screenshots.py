"""Screenshots taken while reading, kept per game.

Press the hotkey (F8 unless you changed it) while a session is running and the
game's window - only the game's, not the desktop around it - is saved into that
novel's gallery:

    %APPDATA%\\VNPresence\\screenshots\\<game id>\\2026-10-15 21-30-05.png

The hotkey only exists while a game is being tracked. Windows gives a
registered hotkey to one program and takes it from everyone else, so holding
F8 for the whole evening would quietly break F8 in every other program on the
machine.

Windows only. Everywhere else the hotkey is simply not registered and the
gallery is a folder you can still put pictures in.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .config import config_dir

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

#: Smaller than this and it is a tray icon or a tooltip, not the game.
MIN_WINDOW_SIDE = 120


# -- the gallery ----------------------------------------------------------
def gallery_dir(game_id: str) -> Path:
    return config_dir() / "screenshots" / game_id


def shots(game_id: str) -> list[Path]:
    """Every picture in a game's gallery, newest first."""
    folder = gallery_dir(game_id)
    if not folder.is_dir():
        return []
    found = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def next_name(folder: Path, when: float | None = None) -> Path:
    """``2026-10-15 21-30-05.png`` - sortable, readable, never overwriting.

    Two presses inside the same second get ``-2``, ``-3``: losing the second
    screenshot of a scene because it shared a timestamp with the first would
    be a strange way for a screenshot tool to behave.
    """
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(when or time.time()))
    candidate = folder / f"{stamp}.png"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stamp}-{n}.png"
        n += 1
    return candidate


# -- finding the game's window --------------------------------------------
@dataclass
class Window:
    hwnd: int
    pid: int
    title: str
    #: Client area in physical screen pixels: left, top, right, bottom.
    rect: tuple[int, int, int, int]

    @property
    def area(self) -> int:
        return max(self.rect[2] - self.rect[0], 0) * max(self.rect[3] - self.rect[1], 0)


def pick_game_window(windows: Iterable[Window]) -> Window | None:
    """The biggest real window - the game, not its launcher's splash.

    Emulators especially own several windows: the game list, a log, the
    render window. The one being read is reliably the largest.
    """
    real = [w for w in windows
            if (w.rect[2] - w.rect[0]) >= MIN_WINDOW_SIDE
            and (w.rect[3] - w.rect[1]) >= MIN_WINDOW_SIDE]
    return max(real, key=lambda w: w.area, default=None)


def windows_of(pids: set[int]) -> list[Window]:  # pragma: no cover - Windows only
    """Visible, not-minimised top-level windows owned by any of ``pids``."""
    if sys.platform != "win32" or not pids:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[Window] = []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in pids:
                return True
            rect = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return True
            # The client area - the game itself, without the title bar and
            # borders around it - converted to screen coordinates.
            corner = wintypes.POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(corner))
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            found.append(Window(
                int(hwnd or 0), int(pid.value), buffer.value,
                (corner.x, corner.y, corner.x + rect.right, corner.y + rect.bottom),
            ))
        except Exception:
            pass
        return True

    with _physical_pixels():
        user32.EnumWindows(callback(visit), 0)
    return found


class _physical_pixels:  # pragma: no cover - Windows only
    """Measure in real screen pixels for the duration of the block.

    A program that has not declared itself DPI-aware is lied to on a scaled
    display: at 125% Windows reports a 1920-wide window as 1536 wide. Pillow's
    grab works in real pixels, so a rectangle measured without this would cut
    the wrong part of the screen - a corner of the game, or half the desktop.
    """

    def __enter__(self):
        self._previous = None
        try:
            import ctypes

            user32 = ctypes.windll.user32
            user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            self._previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            self._previous = None
        return self

    def __exit__(self, *exc):
        if self._previous:
            try:
                import ctypes

                ctypes.windll.user32.SetThreadDpiAwarenessContext(
                    ctypes.c_void_p(self._previous))
            except Exception:
                pass
        return False


# -- taking the picture ---------------------------------------------------
def capture(game_id: str, pids: set[int], *,
            find: Callable[[set[int]], list[Window]] = windows_of,
            grab: Callable | None = None) -> Path | None:
    """Save the game's window into its gallery. Returns the file, or None."""
    window = pick_game_window(find(pids))
    if window is None:
        log.info("screenshot: no window belonging to the game is on screen")
        return None
    if grab is None:
        try:
            from PIL import ImageGrab
        except Exception:  # pragma: no cover - Pillow ships in the .exe
            return None

        def grab(rect):
            with _physical_pixels():
                return ImageGrab.grab(bbox=rect, all_screens=True)

    try:
        image = grab(window.rect)
        if image is None:
            return None
        folder = gallery_dir(game_id)
        folder.mkdir(parents=True, exist_ok=True)
        target = next_name(folder)
        image.save(target, "PNG")
        return target
    except Exception:
        log.warning("screenshot failed", exc_info=True)
        return None


# -- the hotkey -----------------------------------------------------------
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

_NAMED_KEYS = {
    "printscreen": 0x2C, "prtsc": 0x2C, "pause": 0x13, "scrolllock": 0x91,
    "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
}


class HotkeyError(ValueError):
    pass


def parse_hotkey(text: str) -> tuple[int, int]:
    """``"Ctrl+Shift+F8"`` -> (modifiers, virtual key). Raises HotkeyError."""
    parts = [p.strip().lower() for p in (text or "").replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise HotkeyError("no key given")
    mods = 0
    for part in parts[:-1]:
        flag = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT,
                "alt": MOD_ALT, "win": MOD_WIN}.get(part)
        if flag is None:
            raise HotkeyError(f"{part!r} is not a modifier (use Ctrl, Shift, Alt or Win)")
        mods |= flag
    key = parts[-1]
    if key == "f12":
        # Microsoft, on RegisterHotKey: "The F12 key is reserved for use by
        # the debugger at all times, so it should not be registered as a hot
        # key." Better to say so than to register it and have it misbehave.
        raise HotkeyError("F12 is reserved by Windows for debuggers - pick another key")
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return mods, 0x70 + int(key[1:]) - 1
    if len(key) == 1 and key.isalnum():
        if not mods:
            raise HotkeyError(
                f"{key.upper()} on its own would stop you typing it anywhere - add Ctrl or Alt")
        return mods, ord(key.upper())
    if key in _NAMED_KEYS:
        return mods, _NAMED_KEYS[key]
    raise HotkeyError(f"{text!r} is not a key VNPresence knows")


class Hotkey:  # pragma: no cover - needs a Windows message loop
    """A global hotkey, alive between start() and stop().

    RegisterHotKey delivers its message to the thread that registered it, so
    the key gets a thread of its own with a message loop, and stop() posts that
    thread a WM_QUIT.
    """

    def __init__(self, text: str, on_press: Callable[[], None]) -> None:
        self.mods, self.vk = parse_hotkey(text)
        self.text = text
        self.on_press = on_press
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._registered = threading.Event()
        self.error: str | None = None

    def start(self) -> bool:
        if sys.platform != "win32":
            self.error = "global hotkeys need Windows"
            return False
        self._thread = threading.Thread(target=self._loop, name="vnp-hotkey", daemon=True)
        self._thread.start()
        self._registered.wait(timeout=3.0)
        return self.error is None

    def _loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, self.mods | MOD_NOREPEAT, self.vk):
            self.error = (f"{self.text} is already taken by another program - "
                          "set screenshot_hotkey to something else in config.yaml")
            self._registered.set()
            return
        self._registered.set()
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    try:
                        self.on_press()
                    except Exception:
                        log.exception("screenshot hotkey handler failed")
        finally:
            user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if self._thread_id is not None:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
