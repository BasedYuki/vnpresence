"""How long each game has been read, across every session.

Discord shows how long the *current* session has been running, which says
nothing about the forty hours that came before it. So every session adds what
it read to a small file, and the total is what the presence shows: a fact the
program actually knows, rather than a guess at how far through the story that
puts you.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import config_dir

log = logging.getLogger(__name__)

@dataclass
class Entry:
    """What is known about one game's reading history."""

    seconds: float = 0.0
    sessions: int = 0
    last_played: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seconds": round(self.seconds, 1),
            "sessions": self.sessions,
            "last_played": self.last_played,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Entry:
        if not isinstance(data, dict):
            return cls()
        try:
            seconds = float(data.get("seconds") or 0.0)
        except (TypeError, ValueError):
            seconds = 0.0
        try:
            sessions = int(data.get("sessions") or 0)
        except (TypeError, ValueError):
            sessions = 0
        return cls(
            seconds=max(seconds, 0.0),
            sessions=max(sessions, 0),
            last_played=str(data.get("last_played") or ""),
        )


class Playtime:
    """The reading history, stored as one small YAML file.

    Every call re-reads the file before writing it. The background watcher and a
    manually started session can both be running, and re-reading means the
    second one to finish adds to the first one's total instead of overwriting
    it. Losing a few seconds in a genuine race is not worth a lock file.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "playtime.yaml")

    # -- reading ----------------------------------------------------------
    def load(self) -> dict[str, Entry]:
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): Entry.from_dict(v) for k, v in raw.items()}

    def get(self, game_id: str) -> Entry:
        return self.load().get(game_id, Entry())

    def total(self, game_id: str) -> float:
        """Seconds read across all previous sessions."""
        return self.get(game_id).seconds

    def set(self, game_id: str, seconds: float) -> Entry:
        """Replace a game's total outright.

        For the hours read before VNPresence existed. No visual novel engine
        exposes its play time in any portable way - the ones that record it at
        all keep it inside an engine-specific save format, and Ren'Py's is a
        pickle, which cannot be read from outside without running whatever is
        in it. So the honest import is the reader typing the number they can
        see on their own save screen.
        """
        entries = self.load()
        entry = entries.get(game_id, Entry())
        entry.seconds = max(float(seconds), 0.0)
        entries[game_id] = entry
        self._save(entries)
        return entry

    # -- writing ----------------------------------------------------------
    def add(self, game_id: str, seconds: float, *, new_session: bool = False) -> Entry:
        """Add time to a game. Never raises - this must not end a session.

        A negative amount takes time back off, which is not an oddity but a
        requirement: idle time is only ever recognised after it has already
        been written down, and a total that can only go up would keep every
        minute of every evening the reader walked away from. The total itself
        never goes below zero.
        """
        seconds = float(seconds)
        entries = self.load()
        entry = entries.get(game_id, Entry())
        entry.seconds = max(entry.seconds + seconds, 0.0)
        if new_session:
            entry.sessions += 1
        entry.last_played = time.strftime("%Y-%m-%dT%H:%M:%S")
        entries[game_id] = entry
        self._save(entries)
        return entry

    def _save(self, entries: dict[str, Entry]) -> None:
        data = {k: v.to_dict() for k, v in sorted(entries.items())}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Write beside the real file and swap it in: a crash mid-write then
            # costs one session's time instead of the whole history.
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
            os.replace(temporary, self.path)
        except OSError:  # pragma: no cover - disk trouble
            log.debug("could not write %s", self.path, exc_info=True)


# -- how it reads on the card --------------------------------------------
def format_reading_time(seconds: float | None) -> str | None:
    """``45000`` -> ``"12h 30m read"``, for the presence line.

    Deliberately coarser than the session timer: it is written out again every
    fifteen seconds, and a number that ticks over every second would make the
    whole line flicker for anyone watching. Under a minute reads as nothing at
    all rather than "0m".
    """
    if not seconds or seconds < 60:
        return None
    hours, minutes = divmod(int(seconds) // 60, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m read"
    if hours:
        return f"{hours}h read"
    return f"{minutes}m read"


def parse_duration(text: str) -> float:
    """Read a human-typed play time as seconds.

    Accepts what someone would actually type off a save screen: ``50h``,
    ``50h 30m``, ``90m``, ``50:30``, or a bare ``50`` meaning fifty hours -
    nobody seeds a library with fifty seconds.
    """
    text = text.strip().lower()
    if not text:
        raise ValueError("no time given")

    clock = re.fullmatch(r"(\d+):([0-5]?\d)", text)
    if clock:
        return int(clock.group(1)) * 3600 + int(clock.group(2)) * 60

    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text) * 3600  # a bare number is hours

    total = 0.0
    matched = False
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hm])", text):
        total += float(amount) * (3600 if unit == "h" else 60)
        matched = True
    if not matched:
        raise ValueError(f"{text!r} is not a play time (try 50h, 50h 30m, 90m or 50:30)")
    return total
