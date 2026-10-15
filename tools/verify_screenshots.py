"""Prove screenshots work on this machine: the window, the scaling, the key.

Three things only real Windows can answer, and every one of them fails
quietly when it is wrong:

1. finding a program's window and its client area through user32,
2. measuring it in real pixels on a scaled display (125%, 150%...) so the
   picture is of the window and not of a corner of the desktop,
3. the global hotkey - registered, delivered, and released afterwards.

It opens a small window of a known colour, photographs it, checks the photo is
that colour and that size, then asks you to press the key once.

    .venv\\Scripts\\python.exe tools\\verify_screenshots.py

Writes verify_screenshots_report.txt beside itself, and deletes the test
picture it took.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

REPORT = ROOT / "verify_screenshots_report.txt"
lines: list[str] = []
failures = 0
COLOUR = (200, 60, 60)  # the test window's background, #c83c3c


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def check(name: str, ok: bool, detail: str = "") -> bool:
    global failures
    failures += 0 if ok else 1
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}{('  - ' + detail) if detail else ''}")
    return ok


def finish() -> int:
    say()
    say("=" * 58)
    say("EVERYTHING PASSED" if not failures else f"{failures} CHECK(S) FAILED")
    say("=" * 58)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nreport written to {REPORT}")
    return 1 if failures else 0


def main() -> int:
    # A throwaway home, so the test picture never lands in a real gallery.
    home = ROOT / ".verify-screenshots-home"
    os.environ["VNPRESENCE_HOME"] = str(home)

    import tkinter as tk

    from PIL import Image

    from vnpresence import screenshots
    from vnpresence.config import AppConfig

    say(f"VNPresence screenshot verification - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    say(f"python {sys.version.split()[0]} on {sys.platform}")
    if sys.platform != "win32":
        say("Not Windows: the window search and the hotkey are Windows-only.")
        return finish()

    try:
        import ctypes

        scale = ctypes.windll.shcore.GetScaleFactorForDevice(0)
        say(f"Display scaling: {scale}%")
    except Exception:
        say("Display scaling: unknown")
    say()

    root = tk.Tk()
    root.title("VNPresence screenshot test")
    root.geometry("640x360+160+120")
    root.configure(background="#c83c3c")
    tk.Label(root, text="Screenshot test", bg="#c83c3c", fg="white",
             font=("Segoe UI", 22)).pack(expand=True)
    root.attributes("-topmost", True)
    for _ in range(10):
        root.update()
        time.sleep(0.05)

    # -- 1. finding the window --------------------------------------------
    say("1. Finding the window")
    found = screenshots.windows_of({os.getpid()})
    window = screenshots.pick_game_window(found)
    check("the test window is found by its process", window is not None,
          window.title if window else f"{len(found)} window(s), none big enough")
    if window is None:
        root.destroy()
        return finish()
    width = window.rect[2] - window.rect[0]
    height = window.rect[3] - window.rect[1]
    check("its client area has a believable size", width >= 600 and height >= 330,
          f"{width}x{height} real pixels (asked Tk for 640x360)")
    say()

    # -- 2. the picture ---------------------------------------------------
    say("2. Taking the picture")
    saved = screenshots.capture("verify", {os.getpid()})
    check("a picture was saved into the gallery", saved is not None and saved.is_file(),
          saved.name if saved else "")
    if saved is not None:
        with Image.open(saved) as image:
            check("it is exactly the window, not more, not less",
                  image.size == (width, height), f"{image.size[0]}x{image.size[1]}")
            middle = image.convert("RGB").getpixel((image.width // 8, image.height // 8))
            close = all(abs(a - b) <= 12 for a, b in zip(middle, COLOUR))
            check("it shows the window, not the desktop behind it", close,
                  f"pixel {middle}, expected about {COLOUR}")
    say()

    # -- 3. the key -------------------------------------------------------
    key = (AppConfig().screenshot_hotkey or "F8").strip()
    say(f"3. The hotkey  (press {key} now - you have 15 seconds)")
    pressed = threading.Event()
    hotkey = screenshots.Hotkey(key, pressed.set)
    started = hotkey.start()
    check(f"{key} could be registered", started, hotkey.error or "")
    if started:
        deadline = time.time() + 15
        while time.time() < deadline and not pressed.is_set():
            root.update()
            time.sleep(0.05)
        check(f"pressing {key} reached VNPresence", pressed.is_set(),
              "" if pressed.is_set() else "no press arrived in 15 seconds")
        hotkey.stop()
        again = screenshots.Hotkey(key, lambda: None)
        released = again.start()
        check(f"{key} is given back afterwards", released, again.error or "")
        if released:
            again.stop()

    root.destroy()
    shutil.rmtree(home, ignore_errors=True)
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
