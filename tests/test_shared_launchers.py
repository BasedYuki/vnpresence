"""Games that are started by the same executable.

Reported from the wild: "SciADV novels all read as CHAOS;HEAD NOAH". Every
Science Adventure release ships an identically named launcher, and matching a
running process by file name alone made whichever profile happened to load
first claim all of them. The path is what actually distinguishes them.
"""

from __future__ import annotations

import pytest

from vnpresence.config import AppConfig
from vnpresence.launcher import _find_candidate, find_running
from vnpresence.library import Library
from vnpresence.models import GameProfile
from vnpresence.watcher import LibraryWatcher

CHAOS = r"D:\Steam\steamapps\common\CHAOS;HEAD NOAH\LauncherC2.exe"
STEINS = r"D:\Steam\steamapps\common\STEINS;GATE\LauncherC2.exe"
ROBOTICS = r"D:\Steam\steamapps\common\ROBOTICS;NOTES ELITE\LauncherC2.exe"


class FakeProcess:
    """Just enough of psutil.Process for the matching code."""

    def __init__(self, pid, name, exe=""):
        self.pid = pid
        self.info = {"pid": pid, "name": name, "exe": exe}
        self._name = name

    def name(self):
        return self._name

    def create_time(self):
        return 0.0


@pytest.fixture()
def sciadv():
    library = Library()
    for game_id, title, path in (
        ("chaos-head-noah", "CHAOS;HEAD NOAH", CHAOS),
        ("steins-gate", "STEINS;GATE", STEINS),
        ("robotics-notes", "ROBOTICS;NOTES ELITE", ROBOTICS),
    ):
        library.save(GameProfile(id=game_id, title=title, path=path))
    return library


def running(*processes):
    """Patch psutil's process listing with a fixed set."""
    return lambda attrs=None: list(processes)


def test_the_bug_each_sciadv_game_is_itself(sciadv, monkeypatch):
    """Starting Steins;Gate must not publish CHAOS;HEAD NOAH."""
    watcher = LibraryWatcher(AppConfig(client_id="1"), sciadv)
    monkeypatch.setattr(
        "vnpresence.watcher.psutil.process_iter",
        running(FakeProcess(900, "LauncherC2.exe", STEINS)),
    )
    match = watcher.find_match()
    assert match is not None
    assert match.profile.title == "STEINS;GATE"


def test_every_one_of_them_resolves_to_its_own_novel(sciadv, monkeypatch):
    watcher = LibraryWatcher(AppConfig(client_id="1"), sciadv)
    for path, expected in (
        (CHAOS, "CHAOS;HEAD NOAH"),
        (STEINS, "STEINS;GATE"),
        (ROBOTICS, "ROBOTICS;NOTES ELITE"),
    ):
        monkeypatch.setattr(
            "vnpresence.watcher.psutil.process_iter",
            running(FakeProcess(900, "LauncherC2.exe", path)),
        )
        assert watcher.find_match().profile.title == expected


def test_a_name_shared_by_two_games_identifies_neither(sciadv, monkeypatch):
    """With no readable path, guessing would be a coin flip - so it does not."""
    watcher = LibraryWatcher(AppConfig(client_id="1"), sciadv)
    monkeypatch.setattr(
        "vnpresence.watcher.psutil.process_iter",
        running(FakeProcess(900, "LauncherC2.exe", "")),  # elevated: exe hidden
    )
    assert watcher.find_match() is None


def test_an_unambiguous_name_still_matches_without_a_path(monkeypatch):
    """One game, one launcher name: the name is enough and must keep working."""
    library = Library()
    library.save(GameProfile(id="clannad", title="Clannad", path=r"D:\VN\Clannad\Clannad.exe"))
    watcher = LibraryWatcher(AppConfig(client_id="1"), library)
    monkeypatch.setattr(
        "vnpresence.watcher.psutil.process_iter",
        running(FakeProcess(900, "Clannad.exe", "")),
    )
    assert watcher.find_match().profile.title == "Clannad"


def test_process_names_still_win_because_someone_typed_them(sciadv, monkeypatch):
    library = sciadv
    profile = library.get("chaos-head-noah")
    profile.process_names = ["chaos;head noah.exe"]
    library.save(profile)
    watcher = LibraryWatcher(AppConfig(client_id="1"), library)
    monkeypatch.setattr(
        "vnpresence.watcher.psutil.process_iter",
        running(FakeProcess(901, "CHAOS;HEAD NOAH.exe", "")),
    )
    assert watcher.find_match().profile.title == "CHAOS;HEAD NOAH"


# -- the same rule inside the launcher ------------------------------------
def test_attaching_picks_the_process_at_this_games_path(sciadv, monkeypatch):
    """Two launchers of the same name running at once; take the right one."""
    monkeypatch.setattr(
        "vnpresence.launcher.psutil.process_iter",
        running(
            FakeProcess(900, "LauncherC2.exe", CHAOS),
            FakeProcess(901, "LauncherC2.exe", STEINS),
        ),
    )
    tracked = find_running(sciadv.get("steins-gate"))
    assert tracked is not None and tracked.pid == 901


def test_the_bare_name_is_still_the_fallback_for_an_elevated_game(sciadv, monkeypatch):
    """An elevated process hides its path; the name is then all there is."""
    monkeypatch.setattr(
        "vnpresence.launcher.psutil.process_iter",
        running(FakeProcess(902, "LauncherC2.exe", "")),
    )
    found = _find_candidate(sciadv.get("steins-gate"), set())
    assert found is not None and found.pid == 902


# -- and the warning that stops it happening ------------------------------
def test_adding_a_second_game_with_the_same_launcher_is_flagged(sciadv):
    added = sciadv.get("steins-gate")
    clashes = sciadv.sharing_exe_name(added)
    assert {p.title for p in clashes} == {"CHAOS;HEAD NOAH", "ROBOTICS;NOTES ELITE"}


def test_a_game_with_its_own_executable_is_not_flagged(sciadv):
    own = GameProfile(
        id="chaos-head-noah-direct",
        title="CHAOS;HEAD NOAH",
        path=r"D:\Steam\steamapps\common\CHAOS;HEAD NOAH\CHAOS;HEAD NOAH.exe",
    )
    sciadv.save(own)
    assert sciadv.sharing_exe_name(own) == []


def test_a_game_never_clashes_with_itself(sciadv):
    """Neither by id nor by path - re-saving a profile must not warn about it."""
    same = GameProfile(id="chaos-head-noah", title="CHAOS;HEAD NOAH", path=CHAOS)
    clashes = sciadv.sharing_exe_name(same)
    assert "CHAOS;HEAD NOAH" not in {p.title for p in clashes}

    renamed = GameProfile(id="different-id", title="CHAOS;HEAD NOAH", path=CHAOS)
    assert "CHAOS;HEAD NOAH" not in {p.title for p in sciadv.sharing_exe_name(renamed)}


def test_only_a_library_of_one_launcher_is_clash_free():
    library = Library()
    only = GameProfile(id="clannad", title="Clannad", path=r"D:\VN\Clannad\Clannad.exe")
    library.save(only)
    assert library.sharing_exe_name(only) == []
