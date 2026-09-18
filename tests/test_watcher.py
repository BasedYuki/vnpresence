"""Auto-detect mode."""

import psutil
import pytest

from vnpresence.config import AppConfig
from vnpresence.library import Library
from vnpresence.models import GameProfile, PrivacyMode
from vnpresence.watcher import LibraryWatcher


class FakeProcess:
    def __init__(self, pid, name):
        self.pid = pid
        self.info = {"pid": pid, "name": name}


@pytest.fixture()
def library(tmp_path):
    lib = Library(tmp_path / "games")
    lib.save(
        GameProfile(id="woh", title="Mahoutsukai no Yoru", path=r"K:\Games\WoH\WoH.exe")
    )
    lib.save(
        GameProfile(
            id="somevn",
            title="Some VN",
            path=r"D:\VN\SomeVN\Launcher.exe",
            process_names=["somevn_main.exe"],
        )
    )
    return lib


def watcher(library, **kwargs):
    return LibraryWatcher(config=AppConfig(client_id="1"), library=library, **kwargs)


def running(monkeypatch, *names):
    processes = [FakeProcess(i, name) for i, name in enumerate(names, start=100)]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: processes)


def test_match_by_executable_name(library, monkeypatch):
    running(monkeypatch, "chrome.exe", "WoH.exe")
    match = watcher(library).find_match()
    assert match is not None
    assert match.profile.id == "woh"
    assert match.pid == 101


def test_match_by_declared_process_name(library, monkeypatch):
    # The launcher is not running; the real process is.
    running(monkeypatch, "somevn_main.exe")
    match = watcher(library).find_match()
    assert match is not None
    assert match.profile.id == "somevn"


def test_nothing_running_is_not_a_match(library, monkeypatch):
    running(monkeypatch, "explorer.exe", "discord.exe")
    assert watcher(library).find_match() is None


def test_games_set_to_off_are_not_watched(library, monkeypatch):
    profile = library.get("woh")
    profile.privacy = PrivacyMode.OFF
    library.save(profile)
    running(monkeypatch, "WoH.exe")
    watch = watcher(library)
    assert [p.id for p in watch.watchable()] == ["somevn"]
    assert watch.find_match() is None


def test_empty_library_matches_nothing(tmp_path, monkeypatch):
    running(monkeypatch, "WoH.exe")
    assert watcher(Library(tmp_path / "none")).find_match() is None


def test_matching_is_case_insensitive(library, monkeypatch):
    running(monkeypatch, "woh.EXE")
    assert watcher(library).find_match().profile.id == "woh"


def test_a_failing_session_does_not_kill_the_watcher(library, monkeypatch):
    running(monkeypatch, "WoH.exe")
    events = []

    class Boom:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, **kwargs):
            raise RuntimeError("game vanished")

        def stop(self):
            pass

    monkeypatch.setattr("vnpresence.watcher.GameSession", Boom)
    watcher(library).run(on_event=lambda kind, msg: events.append((kind, msg)), once=True)
    kinds = [kind for kind, _ in events]
    assert "detected" in kinds
    assert "error" in kinds  # reported, not raised
