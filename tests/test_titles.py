"""Guessing a game's name from its path - real cases from the wild."""

import pytest

from vnpresence.titles import guess_title, is_uninformative, tidy


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # The case that shipped a presence saying "SiglusEngine_SteamEN"
        (r"K:\Games\Rewrite\SiglusEngine_SteamEN.exe", "Rewrite"),
        # Engines, one level deeper
        (r"D:\VN\Little Busters\bin\reallive.exe", "Little Busters"),
        (r"C:\Games\Fate Stay Night\kirikiri.exe", "Fate Stay Night"),
        (r"D:\VN\Umineko\win32\game.exe", "Umineko"),
        # A file name that does identify the game: keep it
        (r"K:\Games\Witch on the Holy Night\WoH.exe", "WoH"),
        (r"D:\VN\Steins Gate\SteinsGate.exe", "SteinsGate"),
        # Tidying
        (r"D:\VN\Clannad_Full_Voice\game.exe", "Clannad Full Voice"),
        (r"D:\VN\Muv-Luv v1.2\siglus.exe", "Muv-Luv"),
        (r"D:\VN\Saya no Uta [English]\start.exe", "Saya no Uta"),
        # POSIX paths work too
        ("/home/me/vn/Tsukihime/game.exe", "Tsukihime"),
    ],
)
def test_guess_title(path, expected):
    assert guess_title(path) == expected


def test_falls_back_to_the_file_name_when_nothing_helps():
    # Every part is uninformative: better a weak name than a crash.
    assert guess_title(r"C:\games\game.exe") in {"game", "games"}


@pytest.mark.parametrize(
    "name",
    ["SiglusEngine_SteamEN", "reallive", "game", "start", "win32", "kirikiri2", "x"],
)
def test_uninformative_names(name):
    assert is_uninformative(name) is True


@pytest.mark.parametrize("name", ["Rewrite", "WoH", "Steins;Gate", "Muv-Luv Alternative"])
def test_informative_names(name):
    assert is_uninformative(name) is False


def test_tidy_cleans_decoration():
    assert tidy("Clannad_Full_Voice") == "Clannad Full Voice"
    assert tidy("Rewrite [English Patch]") == "Rewrite"
    assert tidy("Muv-Luv v1.2") == "Muv-Luv"
