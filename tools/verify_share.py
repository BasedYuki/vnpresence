"""Prove the screenshot tools work on this machine: Copy, Share, Show in folder.

The parts only real Windows can answer:

1. Copy  - the picture lands on the clipboard as a bitmap and as PNG.
2. Share - the Windows share sheet opens over our window, and Windows takes
           the picture from us when it asks for it.
3. Show in folder - Explorer opens with the file selected.

It makes a red test picture in a throwaway folder, runs each one, and asks you
two yes/no questions about what you saw.

    .venv\\Scripts\\python.exe tools\\verify_share.py

Writes verify_share_report.txt beside itself.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

REPORT = ROOT / "verify_share_report.txt"
lines: list[str] = []
failures = 0


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
    home = ROOT / ".verify-share-home"
    os.environ["VNPRESENCE_HOME"] = str(home)

    import ctypes
    import tkinter as tk
    from tkinter import messagebox

    from PIL import Image

    from vnpresence import shell

    say(f"VNPresence screenshot tools verification - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    build = sys.getwindowsversion().build if sys.platform == "win32" else "-"
    say(f"python {sys.version.split()[0]} on {sys.platform}, Windows build {build}")
    if sys.platform != "win32":
        say("Not Windows: these are Windows features.")
        return finish()

    home.mkdir(parents=True, exist_ok=True)
    picture = home / "share test.png"
    Image.new("RGB", (640, 360), (200, 60, 60)).save(picture)

    root = tk.Tk()
    root.title("VNPresence share test")
    root.geometry("480x200+200+160")
    tk.Label(root, text="VNPresence share test", font=("Segoe UI", 16)).pack(expand=True)
    for _ in range(10):
        root.update()
        time.sleep(0.03)
    say()

    # -- 1. copy ---------------------------------------------------------------
    say("1. Copy")
    try:
        shell.copy_image(picture)
        copied = True
        detail = ""
    except Exception as exc:
        copied, detail = False, repr(exc)
    check("the picture was put on the clipboard", copied, detail)
    if copied:
        user32 = ctypes.WinDLL("user32")
        user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
        png = user32.RegisterClipboardFormatW("PNG")
        check("as a bitmap (what Paint and Word paste)",
              bool(user32.IsClipboardFormatAvailable(shell.CF_DIB)))
        check("and as PNG (what Discord and browsers paste)",
              bool(png and user32.IsClipboardFormatAvailable(png)))
    say()

    # -- 2. share --------------------------------------------------------------
    say("2. Share")
    hwnd = shell.toplevel_hwnd(root)
    try:
        shell.share_image(picture, hwnd, title="VNPresence share test")
        opened, detail = True, ""
    except Exception as exc:
        opened, detail = False, repr(exc)
    check("Windows agreed to open the share sheet", opened, detail)
    if opened:
        # The question box keeps Windows' messages flowing, which is when the
        # sheet asks us for the picture.
        seen = messagebox.askyesno(
            "VNPresence share test",
            "A Windows share window should have opened, showing a RED picture and "
            "apps to share it with.\n\nDid it? (Close the share window first, then answer.)",
            parent=root)
        sharer = shell._sharers.get(hwnd)
        handed = getattr(sharer, "handed_over", 0)
        check("Windows asked for the picture and got it", handed > 0,
              getattr(sharer, "last_error", "") or f"{handed} time(s)")
        check("you saw the share window with the picture", seen)
    say()

    # -- 3. show in folder -----------------------------------------------------
    say("3. Show in folder")
    shell.show_in_folder(picture)
    time.sleep(1.5)
    seen = messagebox.askyesno(
        "VNPresence share test",
        "An Explorer window should have opened with “share test.png” selected.\n\n"
        "Did it?", parent=root)
    check("Explorer opened on the file", seen)

    root.destroy()
    time.sleep(0.5)
    shutil.rmtree(home, ignore_errors=True)
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
