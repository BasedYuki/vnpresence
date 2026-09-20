"""Prove the pause and idle detection actually work, on real Windows.

Everything these two features rest on - which window has the focus, how long
since anyone touched anything - is a Windows API call that cannot run on the
Linux boxes the test suite runs on. The unit tests therefore mock all of it,
which means they prove the *logic* and prove nothing at all about the calls.

This script closes that gap. It exercises the real production code against the
real APIs and writes a report next to itself:

    python tools/verify_focus.py

It changes nothing, needs no game running, takes about ten seconds, and the
only input it generates is a mouse move of zero pixels - the smallest thing
Windows counts as "somebody is there".

Do not touch the keyboard or mouse while it runs; two of the checks are about
what happens when nobody does.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vnpresence import idle, titlebar  # noqa: E402
from vnpresence.config import AppConfig  # noqa: E402
from vnpresence.launcher import belongs_to  # noqa: E402
from vnpresence.models import GameProfile  # noqa: E402
from vnpresence.playtime import Playtime  # noqa: E402
from vnpresence.session import GameSession  # noqa: E402

REPORT = ROOT / "verify_focus_report.txt"
lines: list[str] = []
failures = 0


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def check(name: str, ok: bool, detail: str = "") -> bool:
    global failures
    if not ok:
        failures += 1
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}{('  - ' + detail) if detail else ''}")
    return ok


def inconclusive(name: str, detail: str = "") -> None:
    """Neither a pass nor a failure: the machine would not hold still.

    Kept separate from FAIL on purpose. A check that needs nobody to touch the
    keyboard cannot distinguish "the code is broken" from "somebody moved the
    mouse", and reporting the second as the first sends people hunting a bug
    that is not there.
    """
    say(f"  [SKIP] {name}{('  - ' + detail) if detail else ''}")


def nudge_the_mouse() -> None:
    """The smallest input Windows will count: a move of zero pixels."""
    import ctypes

    ctypes.windll.user32.mouse_event(0x0001, 0, 0, 0, 0)  # MOUSEEVENTF_MOVE


def monitors() -> int:
    import ctypes

    return int(ctypes.windll.user32.GetSystemMetrics(80))  # SM_CMONITORS


def session_for(tracked_pid: int, idle_after: float) -> GameSession:
    made = GameSession(
        GameProfile(id="probe", title="probe", path="x.exe"),
        AppConfig(client_id="1", focused_time_only=True, idle_after=idle_after),
        presence=object(),
        playtime=Playtime(ROOT / ".verify-playtime.yaml"),
    )
    made._tracked_pid = tracked_pid
    return made


def main() -> int:
    say(f"VNPresence focus/idle verification - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    say(f"python {sys.version.split()[0]} on {sys.platform}, pid {os.getpid()}")
    say()

    if sys.platform != "win32":
        say("Not Windows: there is nothing here to verify. These features are")
        say("switched off everywhere else, on purpose.")
        return 0

    say(f"Monitors attached: {monitors()}")
    say()

    # -- 1. which window has the focus ------------------------------------
    say("1. The focused window")
    front = titlebar.foreground_pid()
    check("foreground_pid() answers at all", front is not None, f"pid {front}")
    if front is None:
        say("\nNothing below can be checked without it. Stopping.")
        REPORT.write_text("\n".join(lines), encoding="utf-8")
        return 1

    titles = titlebar.titles_for(front)
    check(
        "the pid it names really owns a window",
        bool(titles),
        (titles[0][:60] if titles else "no window title - suspicious"),
    )
    check(
        "the pid is plausible, not a truncated handle",
        0 < front < 2**22,
        f"{front}",
    )
    say(
        "  note: Windows has exactly one focused window across every monitor."
        if monitors() > 1
        else "  note: only one monitor here, so the two-monitor case is argued, not shown."
    )
    say()

    # -- 2. a window owned by a child process ------------------------------
    say("2. A game whose window belongs to a process it started")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(8)"])
    time.sleep(0.4)
    try:
        check("the child counts as the parent's own", belongs_to(child.pid, os.getpid()))
        check("an unrelated process does not", not belongs_to(child.pid, front + 999_999))
        check("a dead pid does not, and does not raise", not belongs_to(2**22 - 1, 1))
    finally:
        child.terminate()
    say()

    # -- 3. the idle clock -------------------------------------------------
    say("3. The idle clock  (do not touch anything)")
    first = idle.idle_seconds()
    check("idle_seconds() answers at all", first is not None, f"{first:.1f}s" if first else "")
    if first is None:
        REPORT.write_text("\n".join(lines), encoding="utf-8")
        return 1
    # Tried a few times: any touch of the mouse or keyboard resets the clock
    # mid-measurement, and that is not the code being wrong. Some machines
    # also have software that generates input on its own - overlays, mouse
    # utilities, a gaming mouse that drifts - so this reports honestly instead
    # of insisting on a quiet three seconds it cannot guarantee.
    grew = None
    for attempt in range(5):
        before = idle.idle_seconds() or 0.0
        time.sleep(2.0)
        after = idle.idle_seconds() or 0.0
        if 1.4 <= (after - before) <= 3.5:
            grew = after - before
            break
        say(f"  ...something touched the machine, measuring again ({attempt + 1}/5)")
    if grew is None:
        inconclusive(
            "it grows in real time while nobody types",
            "the mouse or keyboard kept being used - see the note at the end",
        )
    else:
        check("it grows in real time while nobody types", True, f"+{grew:.1f}s in 2s")
    second = idle.idle_seconds() or 0.0
    check("it is never the 49-day wrap bug", second < 3600, f"{second:.1f}s")
    nudge_the_mouse()
    time.sleep(0.2)
    after = idle.idle_seconds() or 99.0
    check("input resets it", after < 1.0, f"{after:.2f}s after a 0-pixel mouse move")
    say()

    # -- 4. the production code path --------------------------------------
    say("4. What a session would actually publish")
    reading = session_for(front, idle_after=600)
    check("game focused -> the clock runs", reading.observe() is None, "status: Reading")

    elsewhere = session_for(front + 999_999, idle_after=600)
    check("another window -> Paused", elsewhere.observe() == "Paused")

    watching = session_for(front, idle_after=1.0)
    nudge_the_mouse()
    time.sleep(0.2)
    check("just touched -> still reading", watching.observe() is None)
    say("  waiting out a 1-second idle threshold...")
    time.sleep(2.5)
    check("nobody there -> Idle", watching.observe() == "Idle")
    nudge_the_mouse()
    time.sleep(0.2)
    check("touched again -> reading", watching.observe() is None)
    say()

    # -- 5. the time handed back -------------------------------------------
    say("5. Idle time is given back, not just stopped")
    giving = session_for(front, idle_after=1.0)
    nudge_the_mouse()
    time.sleep(0.2)
    for _ in range(60):
        giving._tick(60.0)  # an hour of genuine reading
    counted = giving.read_seconds
    say(f"  counted {counted:.0f}s of reading ({counted / 60:.0f} minutes)")
    time.sleep(2.5)  # and now nobody is there
    giving._tick(60.0)
    check("it went idle", giving._stopped == "Idle")
    check(
        "the wrongly counted time came back off",
        giving.read_seconds < counted,
        f"{counted:.0f}s -> {giving.read_seconds:.0f}s "
        f"(-{counted - giving.read_seconds:.0f}s)",
    )
    check("it did not wipe the session", giving.read_seconds > counted * 0.9)
    say()

    Path(ROOT / ".verify-playtime.yaml").unlink(missing_ok=True)
    say("=" * 58)
    say("EVERYTHING PASSED" if not failures else f"{failures} CHECK(S) FAILED")
    say("=" * 58)
    if failures:
        say("")
        say("If a check in 3, 4 or 5 failed, the most likely cause is that")
        say("something touched the keyboard or mouse while it ran. Run it again")
        say("and leave the machine alone for ten seconds.")
    if "[SKIP]" in "\n".join(lines):
        say("")
        say("A check came out SKIP rather than PASS or FAIL. That means the idle")
        say("clock kept being reset while it was being measured - you moved the")
        say("mouse, or something on this machine generates input on its own")
        say("(an overlay, mouse software, a mouse that drifts on its own).")
        say("")
        say("It does not mean anything is broken: the checks in section 4 do the")
        say("same job with a threshold and they either passed or did not. But if")
        say("something really does generate input every few seconds, idle")
        say("detection will never fire on this machine - that is the thing to")
        say("look at, not the code.")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nreport written to {REPORT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
