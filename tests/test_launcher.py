"""Process tracking, including games that demand administrator rights."""

import psutil
import pytest

from vnpresence import launcher
from vnpresence.launcher import (
    ERROR_ELEVATION_REQUIRED,
    ElevatedLaunch,
    LaunchError,
    TrackedGame,
    _find_candidate,
    launch,
    resolve_tracked_process,
)
from vnpresence.models import GameProfile


class FakeProcess:
    """Enough of psutil.Process for the candidate scan."""

    def __init__(self, pid, name, exe=None, denied=False):
        self.pid = pid
        self._name = name
        self.info = {"pid": pid, "name": name, "exe": exe}
        self.denied = denied

    def name(self):
        return self._name

    def is_running(self):
        return True

    def status(self):
        if self.denied:
            raise psutil.AccessDenied(self.pid)
        return psutil.STATUS_RUNNING


def profile(**kwargs):
    base = {"id": "woh", "title": "Mahoutsukai no Yoru", "path": r"K:\Games\WoH\WoH.exe"}
    base.update(kwargs)
    return GameProfile(**base)


def test_elevated_game_is_found_by_name_when_its_path_is_hidden(monkeypatch):
    # An elevated process: Windows denies us its exe path, so `exe` comes back None.
    elevated = FakeProcess(42, "WoH.exe", exe=None)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [elevated])
    assert _find_candidate(profile(), set()) is elevated


def test_explicit_process_name_still_wins(monkeypatch):
    other = FakeProcess(1, "WoH.exe", exe=None)
    real = FakeProcess(2, "game_main.exe", exe=None)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [other, real])
    assert _find_candidate(profile(process_names=["game_main.exe"]), set()) is real


def test_no_match_returns_none(monkeypatch):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [FakeProcess(1, "chrome.exe")])
    assert _find_candidate(profile(), set()) is None


def test_access_denied_means_still_running(monkeypatch):
    denied = FakeProcess(42, "WoH.exe", denied=True)
    monkeypatch.setattr(psutil, "Process", lambda pid: denied)
    assert TrackedGame(42, "WoH.exe", 0.0).is_running() is True


def test_missing_process_is_not_running(monkeypatch):
    def boom(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", boom)
    assert TrackedGame(42, "WoH.exe", 0.0).is_running() is False


def test_elevation_error_falls_back_to_uac(monkeypatch, tmp_path):
    exe = tmp_path / "WoH.exe"
    exe.write_text("")
    called = {}

    def fake_popen(*args, **kwargs):
        error = OSError("elevation required")
        error.winerror = ERROR_ELEVATION_REQUIRED
        raise error

    def fake_elevated(path, args, cwd):
        called["path"] = path
        return ElevatedLaunch()

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(launcher, "_launch_elevated", fake_elevated)
    result = launch(profile(path=str(exe)))
    assert isinstance(result, ElevatedLaunch)
    assert called["path"] == exe


def test_other_launch_errors_are_reported(monkeypatch, tmp_path):
    exe = tmp_path / "WoH.exe"
    exe.write_text("")

    def fake_popen(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    with pytest.raises(LaunchError, match="could not start"):
        launch(profile(path=str(exe)))


def test_uac_launch_waits_longer_for_the_prompt(monkeypatch):
    found = FakeProcess(42, "WoH.exe", exe=None)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [found])
    tracked = resolve_tracked_process(
        profile(launcher_grace=1.0), ElevatedLaunch(), poll_interval=0.01
    )
    assert tracked is not None
    assert tracked.pid == 42


# -- whose window is that? -------------------------------------------------
def test_belongs_to_matches_the_process_itself():
    import os

    from vnpresence.launcher import belongs_to

    assert belongs_to(os.getpid(), os.getpid()) is True
    assert belongs_to(None, os.getpid()) is False
    assert belongs_to(os.getpid(), None) is False


def test_belongs_to_follows_the_parent_chain():
    """A game's window often belongs to a process the game started."""
    import os

    from vnpresence.launcher import belongs_to

    parent = os.getppid()
    assert belongs_to(os.getpid(), parent) is True


def test_belongs_to_gives_up_rather_than_walking_to_the_desktop():
    """Bounded on purpose: enough ancestry stops being 'the game'."""
    import os

    from vnpresence.launcher import belongs_to

    assert belongs_to(os.getpid(), os.getppid(), depth=0) is False


def test_belongs_to_survives_a_process_that_just_died():
    from vnpresence.launcher import belongs_to

    assert belongs_to(2**22 - 1, 1) is False
