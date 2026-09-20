"""Visual novels that run inside an emulator.

Plenty of visual novels never left the PSP, the PS2, the PS3 or the Vita, and
are read through RPCS3, PPSSPP, PCSX2 and friends. Those break every assumption
the rest of VNPresence makes: the running process is the *emulator*, one
executable stands in for a whole library, and the path on disk is the same for
every game.

What does identify the game is the window title, which every one of these
writes and keeps current:

    RPCS3     FPS: 59.94 | Vulkan | 0.0.42-20024 Alpha | Muv-Luv [BLJM60123]
    PPSSPP    ULJM05800 : Steins;Gate
    PCSX2     Clannad
    Ryujinx   Ryujinx 1.1.1 - Steins;Gate Elite v1.0.0 (01001B300B9BE000)

So a profile for an emulated game carries a ``window_match``: a piece of text
that has to appear in the emulator's window title for that game to count. The
disc serial is the better thing to put there - it is unique, it never changes
with a translation patch, and it survives the emulator rewording its own title
bar - but a distinctive part of the name works too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Executables that run other people's games. Matched on the file name, so
#: rpcs3.exe and rpcs3 (Linux) are the same entry.
EMULATORS: dict[str, str] = {
    "rpcs3": "RPCS3 (PlayStation 3)",
    "ppsspp": "PPSSPP (PSP)",
    "ppssppwindows": "PPSSPP (PSP)",
    "ppssppwindows64": "PPSSPP (PSP)",
    "pcsx2": "PCSX2 (PlayStation 2)",
    "pcsx2-qt": "PCSX2 (PlayStation 2)",
    "pcsx2-qtx64": "PCSX2 (PlayStation 2)",
    "pcsx2-qtx64-avx2": "PCSX2 (PlayStation 2)",
    "vita3k": "Vita3K (PS Vita)",
    "ryujinx": "Ryujinx (Switch)",
    "yuzu": "yuzu (Switch)",
    "citra": "Citra (3DS)",
    "citra-qt": "Citra (3DS)",
    "lime3ds": "Lime3DS (3DS)",
    "azahar": "Azahar (3DS)",
    "melonds": "melonDS (DS)",
    "desmume": "DeSmuME (DS)",
    "duckstation": "DuckStation (PlayStation)",
    "duckstation-qt-x64-releaseltcg": "DuckStation (PlayStation)",
    "mgba": "mGBA (Game Boy Advance)",
    "visualboyadvance-m": "VisualBoyAdvance-M (Game Boy Advance)",
    "snes9x": "Snes9x (Super Famicom)",
    "retroarch": "RetroArch",
    "xemu": "xemu (Xbox)",
    "flycast": "Flycast (Dreamcast)",
    "redream": "redream (Dreamcast)",
}

#: Disc and title serials, as they appear in a title bar. Worth pulling out
#: separately: it is the one part of the line that identifies a game exactly.
#: Four letters and five digits covers every Sony serial there is - BLJM60123,
#: NPEB01234, ULJM05800, SLPM-66408, PCSG00123 - without needing a table of
#: region codes that would go out of date. Switch title ids are 16 hex digits.
#: Game files, not programs. Somebody who has just set up an emulator points
#: VNPresence at the thing they think of as the game - the ROM - and Windows
#: answers "%1 is not a valid Win32 application", which explains nothing to
#: anyone. Recognising the extension turns that into an answer.
ROM_SUFFIXES: dict[str, str] = {
    ".xci": "Switch cartridge dump",
    ".nsp": "Switch package",
    ".nsz": "Switch package (compressed)",
    ".xcz": "Switch cartridge dump (compressed)",
    ".3ds": "3DS ROM",
    ".cci": "3DS ROM",
    ".cia": "3DS installable",
    ".nds": "DS ROM",
    ".gba": "Game Boy Advance ROM",
    ".gbc": "Game Boy Color ROM",
    ".sfc": "Super Famicom ROM",
    ".smc": "Super Famicom ROM",
    ".n64": "Nintendo 64 ROM",
    ".z64": "Nintendo 64 ROM",
    ".v64": "Nintendo 64 ROM",
    ".gcm": "GameCube disc image",
    ".rvz": "Wii/GameCube disc image",
    ".wbfs": "Wii disc image",
    ".wud": "Wii U disc image",
    ".wux": "Wii U disc image",
    ".iso": "disc image",
    ".cso": "compressed disc image",
    ".chd": "compressed disc image",
    ".pbp": "PSP package",
    ".vpk": "Vita package",
    ".cue": "disc index",
    ".gdi": "Dreamcast disc index",
    ".cdi": "Dreamcast disc image",
    ".mdf": "disc image",
    ".nrg": "disc image",
    ".xbe": "Xbox executable",
    ".pkg": "package",
    ".rom": "ROM",
    ".zip": "archive",
    ".7z": "archive",
}


def is_rom(path: str | None) -> bool:
    """Is this a game file rather than something Windows can run?"""
    if not path:
        return False
    return Path(path).suffix.lower() in ROM_SUFFIXES


def rom_kind(path: str | None) -> str:
    """What to call it when explaining the mistake."""
    if not path:
        return "a game file"
    return ROM_SUFFIXES.get(Path(path).suffix.lower(), "a game file")


SERIAL = re.compile(r"\b([A-Z]{4}-?\d{5}|[0-9A-F]{16})\b", re.IGNORECASE)

_NAMES = "|".join(sorted((re.escape(n) for n in set(EMULATORS)), key=len, reverse=True))

#: The emulator naming itself at the front ("Ryujinx 1.1.1 - ", "Vita3K 0.1.9 | ")
#: or at the back ("Steins;Gate - PPSSPP v1.17.1"). Matched against the list of
#: emulators rather than "a word and a version", which also ate the first word
#: of games called things like "Chaos;Head 1.0".
#: "Ryujinx 1.1.1 - " : the name, its version, and the separator after it.
_LEADING_STRICT = re.compile(rf"^\s*({_NAMES})\b[^|:]*?\s*[-|:]\s*", re.IGNORECASE)
#: "PPSSPP v1.17.1" with nothing after it: the name and a version, no separator.
_LEADING_LOOSE = re.compile(rf"^\s*({_NAMES})\b\s*v?[\d.+-]*\s*", re.IGNORECASE)
_TRAILING_EMULATOR = re.compile(rf"\s*[-|]\s*({_NAMES})\b[\s\w.+-]*$", re.IGNORECASE)


def _strip_emulator(text: str) -> str:
    """Take the emulator's own name off the front, version and all."""
    stripped = _LEADING_STRICT.sub("", text, count=1)
    if stripped == text:  # no separator to anchor on
        stripped = _LEADING_LOOSE.sub("", text, count=1)
    return stripped.strip()

#: Bits emulators put in the title that are about the emulator, not the game.
_NOISE = (
    re.compile(r"^FPS:\s*[\d.]+\s*\|\s*", re.IGNORECASE),  # RPCS3 leads with it
    re.compile(r"\b(vulkan|opengl|direct3d\d*|d3d\d*|null)\b\s*\|\s*", re.IGNORECASE),
    re.compile(r"\b\d+\.\d+\.\d+[\w.-]*\s*(alpha|beta)?\s*\|\s*", re.IGNORECASE),
    re.compile(r"\s*\(instance:?\s*\d+\)\s*$", re.IGNORECASE),  # PPSSPP, 2nd copy
    re.compile(r"\s*\bv\d+\.\d+(\.\d+)*\b", re.IGNORECASE),  # Ryujinx game version
    re.compile(r"\s*\|\s*\d+\s*x\s*\d+\s*$"),  # a resolution at the end
    re.compile(r"\s*\[(paused|running|fast\s*forward)\]\s*", re.IGNORECASE),
)


def is_emulator(process_name: str) -> bool:
    """Is this executable an emulator rather than a game?"""
    stem = (process_name or "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    if stem.lower().endswith(".exe"):
        stem = stem[:-4]
    return stem.lower() in EMULATORS


def label(process_name: str) -> str | None:
    stem = (process_name or "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    if stem.lower().endswith(".exe"):
        stem = stem[:-4]
    return EMULATORS.get(stem.lower())


def serial_in(title: str) -> str | None:
    """The disc or title serial in a window title, if there is one."""
    found = SERIAL.search(title or "")
    return found.group(1).upper() if found else None


def game_name(title: str) -> str:
    """The game's name, with the emulator's own noise taken out.

    Only as good as the title bar it is given - this is for suggesting a name
    when adding a game, not for deciding anything. What decides is the
    ``window_match`` the reader confirms.
    """
    text = (title or "").strip()
    if not text:
        return ""

    # "ULJM05800 : Steins;Gate" - PPSSPP leads with the serial.
    lead = re.match(r"^\s*([A-Z0-9-]{8,12})\s*:\s*(.+)$", text)
    if lead:
        text = lead.group(2)

    # Take the emulator's own name off first: once the version has been
    # stripped as noise there is no separator left to recognise it by.
    text = _strip_emulator(text)
    text = _TRAILING_EMULATOR.sub("", text)

    for pattern in _NOISE:
        text = pattern.sub(" ", text)

    text = _strip_emulator(text)
    text = SERIAL.sub("", text)
    text = re.sub(r"[\[\](){}]", " ", text)
    text = re.sub(r"\s*[-|:]\s*$", "", text.strip())
    text = re.sub(r"^\s*[-|:]\s*", "", text)
    text = " ".join(text.split())
    # What is left of "RPCS3 v0.0.42-20024" is a version fragment, not a game.
    return text if re.search(r"[A-Za-z]{2}", text) else ""


def matches_window(window_match: str, titles: list[str]) -> bool:
    """Is the wanted game the one currently loaded?

    Case-insensitive substring, because what the reader has to type is then a
    serial copied off the title bar or a word out of the game's name - not a
    regular expression.
    """
    wanted = " ".join((window_match or "").split()).casefold()
    if not wanted:
        return False
    return any(wanted in " ".join(t.split()).casefold() for t in titles)


def suggest_match(title: str) -> str:
    """What to put in ``window_match`` for the game in this title bar.

    The serial when the emulator offers one - it is exact and it outlives
    translation patches and title-bar rewordings - and the name otherwise.
    """
    return serial_in(title) or game_name(title)


@dataclass
class Running:
    """An emulator that is open right now, and what it has loaded."""

    pid: int
    process: str
    emulator: str
    title: str

    @property
    def game(self) -> str:
        return game_name(self.title)

    @property
    def serial(self) -> str | None:
        return serial_in(self.title)

    @property
    def match(self) -> str:
        return suggest_match(self.title)

    @property
    def loaded(self) -> bool:
        """Is a game actually running, or is this just an open emulator?"""
        return bool(self.game or self.serial)


def running(titles: dict[int, list[str]] | None = None) -> list[Running]:
    """Every emulator open right now, with the game it is running.

    This is what turns "set window_match to something" into "press 2": the
    reader starts the game, runs this, and the serial is on screen ready to be
    copied.
    """
    import psutil  # local: emulators.py is imported by code that never scans

    from .titlebar import titles_by_pid

    windows = titles_by_pid() if titles is None else titles
    found: list[Running] = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            name = process.info.get("name") or ""
            pid = process.info["pid"]
        except Exception:
            continue
        emulator = label(name)
        if emulator is None:
            continue
        for title in windows.get(pid, []) or [""]:
            found.append(Running(pid=pid, process=name, emulator=emulator, title=title))
    # An emulator with a game loaded is more useful than one sitting idle.
    return sorted(found, key=lambda item: (not item.loaded, item.emulator))
