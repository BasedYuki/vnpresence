"""Guessing a game's name from where it lives on disk.

Visual novels rarely name their executable after the game. They name it after
the engine - ``SiglusEngine_SteamEN.exe``, ``reallive.exe``, ``kirikiri.exe`` -
or after nothing at all (``game.exe``, ``start.exe``). Searching VNDB for that
finds nothing, and the presence ends up saying "SiglusEngine_SteamEN".

The folder almost always carries the real name, so when the file name looks
like an engine or a placeholder, the folder wins.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Engines whose name commonly ends up on the executable.
ENGINES = {
    "siglus",
    "siglusengine",
    "reallive",
    "realive",
    "kirikiri",
    "krkr",
    "krkrz",
    "nscripter",
    "onscripter",
    "ethornell",
    "bgi",
    "majiro",
    "artemis",
    "catsystem",
    "cs2",
    "rio",
    "yuris",
    "ryukishi",
    "tyranobuilder",
    "renpy",
    "unity",
    "unityplayer",
    "rpgvx",
    "rpgmaker",
    "adobeair",
}

#: Names that say nothing about which game this is.
PLACEHOLDERS = {
    "game",
    "games",
    "start",
    "startup",
    "launcher",
    "launch",
    "main",
    "play",
    "player",
    "run",
    "app",
    "application",
    "client",
    "config",
    "setup",
    "install",
    "bootstrap",
    "exe",
    "win",
    "win32",
    "win64",
    "x64",
    "x86",
    "bin",
    "data",
    "system",
    "engine",
    "release",
    "final",
    "steam",
    "english",
    "patch",
    "full",
}


def _normalise(name: str) -> str:
    """Lowercase, letters and digits only - for comparing against the lists."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def is_uninformative(name: str) -> bool:
    """True when this name does not identify a game."""
    flat = _normalise(name)
    if not flat or len(flat) <= 2:
        return True
    if flat in PLACEHOLDERS or flat in ENGINES:
        return True
    # "SiglusEngine_SteamEN", "kirikiri2", "game_main"...
    if any(engine in flat for engine in ENGINES):
        return True
    # A name made only of placeholder words: "game_start", "main-launcher"
    parts = [p for p in re.split(r"[\s_\-.]+", name.lower()) if p]
    return bool(parts) and all(_normalise(p) in PLACEHOLDERS for p in parts if _normalise(p))


def tidy(name: str) -> str:
    """Turn a folder or file name into something worth showing a person.

    Order matters: version numbers are stripped while the dots are still there,
    otherwise "Muv-Luv v1.2" turns into "Muv-Luv v1 2".
    """
    text = re.sub(r"[\[(][^\])]*[\])]", " ", name)  # drop [English], (v1.02)
    text = re.sub(r"\bv?\d+(?:\.\d+)+\b", " ", text)  # drop 1.0.3 / v2.1
    text = re.sub(r"\s[vV]\d+\b", " ", text)  # drop a trailing " v2"
    text = text.replace("_", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text or name


def guess_title(path: str | Path, *, max_levels: int = 3) -> str:
    """Best guess at the game's name for a given executable path.

    Uses the file name when it says something, otherwise walks up the folders
    until one does - so ``K:\\Games\\Rewrite\\bin\\SiglusEngine.exe`` becomes
    "Rewrite", not "SiglusEngine".
    """
    path = Path(str(path).replace("\\", "/"))
    if not is_uninformative(path.stem):
        return tidy(path.stem)

    for parent in list(path.parents)[:max_levels]:
        name = parent.name
        if not name:  # a drive root or "/"
            break
        if not is_uninformative(name):
            return tidy(name)

    return tidy(path.stem)
