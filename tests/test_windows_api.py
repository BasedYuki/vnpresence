"""The Windows calls, run on real Windows - by CI, on every push.

Every other test in this suite mocks ``foreground_pid`` and ``idle_seconds``,
which proves the logic around them and nothing whatsoever about the calls
themselves. That is a real gap: both are ctypes calls into user32, and the two
ways they go wrong - a window handle truncated to 32 bits, a tick counter that
wrapped - fail silently and look exactly like "nobody is there".

CI runs this file on windows-latest, so those calls are exercised for real on
every push. Everywhere else it skips: there is nothing to check.

A CI runner has no interactive desktop, so the foreground window is usually
absent. That is the point of half of these: the absence has to arrive as
``None`` and be handled, not as a crash or as a bogus pid.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import psutil
import pytest

from vnpresence import idle, titlebar
from vnpresence.config import AppConfig
from vnpresence.launcher import belongs_to
from vnpresence.models import GameProfile
from vnpresence.playtime import Playtime
from vnpresence.session import GameSession

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="these are the Windows-only calls"
)

#: Windows pids are multiples of 4 and stay far below this. The real check is
#: pid_exists; this only catches a number that is not a pid at all.
PLAUSIBLE_PID = 2**31


def test_both_modules_agree_they_are_supported():
    assert titlebar.supported() is True
    assert idle.supported() is True


# -- the focused window ----------------------------------------------------
def test_foreground_pid_answers_without_raising():
    """None is a legitimate answer; a crash or a mangled number is not."""
    pid = titlebar.foreground_pid()
    assert pid is None or isinstance(pid, int)


def test_the_pid_is_a_real_process_not_a_truncated_handle():
    pid = titlebar.foreground_pid()
    if pid is None:
        pytest.skip("no foreground window on this runner, which is normal")
    assert 0 < pid < PLAUSIBLE_PID
    assert psutil.pid_exists(pid)


def test_enumerating_windows_never_raises():
    found = titlebar.titles_by_pid()
    assert isinstance(found, dict)
    assert all(isinstance(k, int) and isinstance(v, list) for k, v in found.items())
    assert titlebar.titles_for(2**22 - 1) == []  # a pid that owns nothing


# -- the idle clock --------------------------------------------------------
def test_the_real_clock_never_comes_back_as_the_wrap_value():
    """The bug this guards against looks exactly like "nobody is there"."""
    for _ in range(20):  # sampled, because it is a race by nature
        quiet = idle.idle_seconds()
        assert quiet is not None
        assert quiet < 24 * 24 * 3600  # never the 49.7-day wrap
        time.sleep(0.02)


def test_the_idle_clock_is_readable_and_sane():
    quiet = idle.idle_seconds()
    assert quiet is not None
    assert quiet >= 0
    # The wrap bug shows up as a number near 49.7 days. A runner that really
    # had been untouched that long would not be running this.
    assert quiet < 30 * 24 * 3600


def test_the_idle_clock_moves_with_the_wall_clock():
    """Nothing touches a CI runner, so it should climb by roughly the sleep."""
    first = idle.idle_seconds()
    assert first is not None
    time.sleep(2.0)
    second = idle.idle_seconds()
    assert second is not None
    assert second > first
    assert 1.0 <= (second - first) <= 5.0


# -- the family walk -------------------------------------------------------
def test_belongs_to_follows_a_real_windows_process_tree():
    """A game's window is often owned by a process the game started."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        time.sleep(0.5)
        assert belongs_to(child.pid, os.getpid()) is True
        # A pid nothing in this tree can possibly be. Deliberately not the
        # System process: on a CI runner that really is an ancestor.
        assert belongs_to(child.pid, child.pid + 999_999) is False
    finally:
        child.terminate()
        child.wait(timeout=10)


# -- the whole decision, on real Windows -----------------------------------
def _session(tracked_pid, tmp_path, **config_kwargs):
    made = GameSession(
        GameProfile(id="probe", title="probe", path="x.exe"),
        AppConfig(client_id="1", focused_time_only=True, **config_kwargs),
        presence=object(),
        playtime=Playtime(tmp_path / "playtime.yaml"),
    )
    made._tracked_pid = tracked_pid
    return made


def test_a_game_that_is_not_the_focused_window_reads_as_paused(tmp_path):
    front = titlebar.foreground_pid()
    if front is None:
        pytest.skip("no foreground window on this runner, which is normal")
    # Some pid that is certainly not the window in use.
    session = _session(front + 999_999, tmp_path, idle_after=0)
    assert session.observe() == "Paused"


def test_an_untouched_machine_reads_as_idle(tmp_path):
    """Nothing has touched this runner, so a one-second threshold must trip."""
    front = titlebar.foreground_pid() or os.getpid()
    session = _session(front, tmp_path, idle_after=1.0)
    if session.look_at_focus() is False:
        pytest.skip("this runner has a foreground window we do not own")
    time.sleep(1.5)
    assert session.observe() == "Idle"


def test_idle_detection_switched_off_means_the_clock_runs(tmp_path):
    front = titlebar.foreground_pid() or os.getpid()
    session = _session(front, tmp_path, idle_after=0)
    if session.look_at_focus() is False:
        pytest.skip("this runner has a foreground window we do not own")
    assert session.observe() is None
