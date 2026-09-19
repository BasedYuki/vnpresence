"""How long each game has been read, and the progress that follows from it.

Discord shows how long the *current* session has been running, which says
nothing about how far into a 60-hour novel someone is. To answer that, the time
has to be remembered across sessions, so every session adds what it read to a
small file and the percentage is computed from the total.

The percentage is an estimate and is presented as one. VNDB publishes the
average play time its users report for a novel (``length_minutes``); when a
novel has no such votes, the rough length bucket is used instead, which is a far
coarser guess. Reading speed varies enormously between people, routes get
skipped and text gets re-read, so the number is a rough sense of where someone
is - not a save-file-accurate figure, and it never pretends to be one.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import config_dir

log = logging.getLogger(__name__)

#: Minutes to assume for each VNDB length bucket when nobody has voted on the
#: actual play time. These are the middle of each published range; bucket 5 is
#: open-ended (> 50h), so 60h is a deliberately conservative floor.
BUCKET_MINUTES = {1: 60, 2: 360, 3: 1200, 4: 2400, 5: 3600}


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

    # -- writing ----------------------------------------------------------
    def add(self, game_id: str, seconds: float, *, new_session: bool = False) -> Entry:
        """Add time to a game. Never raises - this must not end a session."""
        seconds = max(float(seconds), 0.0)
        entries = self.load()
        entry = entries.get(game_id, Entry())
        entry.seconds += seconds
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


# -- the estimate ---------------------------------------------------------
def expected_minutes(length_minutes: int | None, bucket: int | None = None) -> int | None:
    """How long this novel is expected to take, in minutes."""
    if length_minutes and length_minutes > 0:
        return int(length_minutes)
    if bucket in BUCKET_MINUTES:
        return BUCKET_MINUTES[bucket]
    return None


def fraction(seconds_read: float, length_minutes: int | None) -> float | None:
    """Progress as 0.0-1.0, or ``None`` when the novel's length is unknown.

    Capped at 1.0: somebody who has read for longer than average is finishing,
    not 140% done.
    """
    if not length_minutes or length_minutes <= 0 or seconds_read <= 0:
        return None
    return min(seconds_read / (length_minutes * 60), 1.0)


def percent(value: float | None) -> str | None:
    """Format a fraction for the activity: ``0.337`` -> ``"34%"``.

    Anything above zero shows at least 1%, so the number appears as soon as a
    session starts instead of sitting on a silent "0%" for the first half hour.
    """
    if value is None:
        return None
    number = round(value * 100)
    if number <= 0:
        number = 1
    return f"{min(number, 100)}%"
