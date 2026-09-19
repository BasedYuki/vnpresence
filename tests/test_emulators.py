"""Visual novels read through an emulator.

The awkward shape of this: the running process is RPCS3, and RPCS3 is also the
process for every other game its owner has. The only thing that says which game
is loaded is the window title, so these tests are mostly about reading real
title bars correctly and about never letting an emulator answer for a game it
is not running.

The title strings below are the formats the emulators actually use - RPCS3's
comes from its own default, ``FPS: %F | %R | %V | %T [%t]``, and PPSSPP's from
``<DISC_ID> : <title>`` in Core/System.cpp.
"""

from __future__ import annotations

import pytest

from vnpresence import emulators
from vnpresence.config import AppConfig
from vnpresence.library import Library
from vnpresence.models import GameProfile
from vnpresence.watcher import LibraryWatcher

RPCS3 = "FPS: 59.94 | Vulkan | 0.0.42-20024 Alpha | Muv-Luv Alternative [BLJM60123]"
PPSSPP = "ULJM05800 : Steins;Gate"
PCSX2 = "Clannad"
RYUJINX = "Ryujinx 1.1.1 - Steins;Gate Elite v1.0.0 (01001B300B9BE000)"
VITA3K = "Vita3K 0.1.9 | Kanojo, Okarishimasu (PCSG01234)"


# -- knowing an emulator when you see one ---------------------------------
@pytest.mark.parametrize(
    "name",
    ["rpcs3.exe", "RPCS3.EXE", "ppsspp.exe", "PPSSPPWindows64.exe", "pcsx2-qt.exe",
     "ryujinx.exe", "vita3k.exe", r"C:\Emulators\RPCS3\rpcs3.exe"],
)
def test_emulators_are_recognised(name):
    assert emulators.is_emulator(name)


@pytest.mark.parametrize(
    "name",
    ["SiglusEngine.exe", "game.exe", "Clannad.exe", "reallive.exe", "", "rpcs3game.exe"],
)
def test_ordinary_games_are_not(name):
    assert not emulators.is_emulator(name)


def test_an_emulator_is_named_for_the_reader():
    assert "PlayStation 3" in emulators.label("rpcs3.exe")
    assert emulators.label("clannad.exe") is None


# -- reading the title bar -------------------------------------------------
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (RPCS3, "Muv-Luv Alternative"),
        (PPSSPP, "Steins;Gate"),
        (PPSSPP + " (instance: 2)", "Steins;Gate"),  # a second PPSSPP window
        (PCSX2, "Clannad"),
        (RYUJINX, "Steins;Gate Elite"),
        (VITA3K, "Kanojo, Okarishimasu"),
        ("Higurashi no Naku Koro ni Kizuna [ULJM05633]", "Higurashi no Naku Koro ni Kizuna"),
        ("Umineko - PCSX2 2.1.0", "Umineko"),
    ],
)
def test_the_game_is_read_out_of_the_title(title, expected):
    assert emulators.game_name(title) == expected


@pytest.mark.parametrize(
    "idle",
    ["PPSSPP v1.17.1", "RPCS3 v0.0.42-20024", "melonDS 0.9.5", "", "   "],
)
def test_an_emulator_with_nothing_loaded_reads_as_nothing(idle):
    """Otherwise the reader would be offered "v0.0.42" as a game name."""
    assert emulators.game_name(idle) == ""


@pytest.mark.parametrize(
    ("title", "serial"),
    [
        (RPCS3, "BLJM60123"),
        (PPSSPP, "ULJM05800"),
        (RYUJINX, "01001B300B9BE000"),
        (VITA3K, "PCSG01234"),
        ("Clannad [SLPM-66408]", "SLPM-66408"),
        ("FPS: 60.00 | OpenGL | 0.0.33 Alpha | Steins;Gate [NPEB01234]", "NPEB01234"),
    ],
)
def test_the_serial_is_picked_out(title, serial):
    assert emulators.serial_in(title) == serial


def test_a_title_with_no_serial_has_none():
    assert emulators.serial_in(PCSX2) is None


def test_the_serial_is_what_gets_suggested():
    """It is exact, and it survives a translation patch renaming the game."""
    assert emulators.suggest_match(RPCS3) == "BLJM60123"
    assert emulators.suggest_match(PCSX2) == "Clannad"  # nothing better on offer


# -- deciding whether the right game is loaded ----------------------------
def test_the_serial_matches_its_own_window():
    assert emulators.matches_window("BLJM60123", [RPCS3])
    assert emulators.matches_window("bljm60123", [RPCS3])  # case does not matter


def test_another_games_serial_does_not():
    assert not emulators.matches_window("BLJM99999", [RPCS3])


def test_part_of_a_name_works_too():
    assert emulators.matches_window("Muv-Luv", [RPCS3])
    assert emulators.matches_window("clannad", [PCSX2])


def test_an_empty_match_never_matches():
    """Otherwise a profile with no window set would claim every emulator."""
    assert not emulators.matches_window("", [RPCS3])
    assert not emulators.matches_window("   ", [RPCS3])


def test_nothing_matches_when_the_emulator_has_no_windows():
    assert not emulators.matches_window("BLJM60123", [])


# -- the whole thing, through the watcher ---------------------------------
class FakeProcess:
    def __init__(self, pid, name, exe=""):
        self.pid = pid
        self.info = {"pid": pid, "name": name, "exe": exe}


@pytest.fixture()
def rpcs3_library():
    """Two PS3 novels, one emulator - the case this feature exists for."""
    library = Library()
    library.save(GameProfile(
        id="muv-luv", title="Muv-Luv Alternative",
        path=r"C:\Emulators\RPCS3\rpcs3.exe", window_match="BLJM60123",
    ))
    library.save(GameProfile(
        id="steins-gate", title="STEINS;GATE",
        path=r"C:\Emulators\RPCS3\rpcs3.exe", window_match="NPEB01234",
    ))
    return library


def watcher_for(library):
    return LibraryWatcher(AppConfig(client_id="1"), library)


def test_the_loaded_game_is_the_one_that_matches(rpcs3_library, monkeypatch):
    monkeypatch.setattr(
        "vnpresence.watcher.psutil.process_iter",
        lambda attrs=None: [FakeProcess(700, "rpcs3.exe", r"C:\Emulators\RPCS3\rpcs3.exe")],
    )
    monkeypatch.setattr("vnpresence.watcher.titles_by_pid", lambda: {700: [RPCS3]})
    assert watcher_for(rpcs3_library).find_match().profile.title == "Muv-Luv Alternative"


def test_loading_the_other_game_switches_which_one_is_found(rpcs3_library, monkeypatch):
    other = "FPS: 60.00 | Vulkan | 0.0.42 Alpha | STEINS;GATE [NPEB01234]"
    monkeypatch.setattr(
        "vnpresence.watcher.psutil.process_iter",
        lambda attrs=None: [FakeProcess(700, "rpcs3.exe", r"C:\Emulators\RPCS3\rpcs3.exe")],
    )
    monkeypatch.setattr("vnpresence.watcher.titles_by_pid", lambda: {700: [other]})
    assert watcher_for(rpcs3_library).find_match().profile.title == "STEINS;GATE"


def test_an_idle_emulator_publishes_nothing(rpcs3_library, monkeypatch):
    """RPCS3 open on its game list is not "reading Muv-Luv Alternative"."""
    monkeypatch.setattr(
        "vnpresence.watcher.psutil.process_iter",
        lambda attrs=None: [FakeProcess(700, "rpcs3.exe", r"C:\Emulators\RPCS3\rpcs3.exe")],
    )
    monkeypatch.setattr("vnpresence.watcher.titles_by_pid", lambda: {700: ["RPCS3 v0.0.42"]})
    assert watcher_for(rpcs3_library).find_match() is None


def test_an_ordinary_game_still_matches_without_any_windows(monkeypatch):
    """The window lookup is extra information, never a new requirement."""
    library = Library()
    library.save(GameProfile(id="clannad", title="Clannad", path=r"D:\VN\Clannad\game.exe"))
    monkeypatch.setattr(
        "vnpresence.watcher.psutil.process_iter",
        lambda attrs=None: [FakeProcess(800, "game.exe", r"D:\VN\Clannad\game.exe")],
    )
    monkeypatch.setattr("vnpresence.watcher.titles_by_pid", lambda: {})
    assert watcher_for(library).find_match().profile.title == "Clannad"


def test_the_window_list_is_only_asked_for_when_it_is_needed(monkeypatch):
    """Enumerating every window on screen is not free; skip it for a plain library."""
    library = Library()
    library.save(GameProfile(id="clannad", title="Clannad", path=r"D:\VN\Clannad\game.exe"))
    monkeypatch.setattr(
        "vnpresence.watcher.psutil.process_iter",
        lambda attrs=None: [FakeProcess(800, "game.exe", r"D:\VN\Clannad\game.exe")],
    )
    monkeypatch.setattr(
        "vnpresence.watcher.titles_by_pid",
        lambda: pytest.fail("no emulated game in the library - do not enumerate windows"),
    )
    assert watcher_for(library).find_match() is not None


# -- the profile key -------------------------------------------------------
def test_window_match_survives_a_save_and_load():
    library = Library()
    library.save(GameProfile(
        id="muv-luv", title="Muv-Luv", path="/rpcs3.exe", window_match="BLJM60123"
    ))
    assert library.get("muv-luv").window_match == "BLJM60123"


def test_a_profile_without_one_is_unchanged():
    """The key must stay out of the YAML of every ordinary game."""
    profile = GameProfile(id="clannad", title="Clannad", path="/c.exe")
    assert "window_match" not in profile.to_dict()
