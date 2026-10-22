"""Every time a game was played: when it started, when it ended, and how much
of that was actually reading.

The total in ``playtime.yaml`` answers "how long altogether"; this answers
"when". One JSON file per game in ``sessions/``, newest last, capped so a
game played every evening for years still loads instantly.

``counted`` is what the clock kept - focused, not idle - so a session that
ran three hours with the reader away for one shows 3h on the wall clock and
2h counted, and the page shows both.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .config import config_dir

log = logging.getLogger(__name__)

#: Plenty: two sessions a day for over two years.
KEEP = 1500
#: Shorter than this is a game opened by mistake, not a session.
MIN_COUNTED = 30.0


@dataclass(frozen=True)
class Session:
    start: _dt.datetime
    end: _dt.datetime
    counted: float  # seconds the clock kept

    @property
    def wall(self) -> float:
        return max((self.end - self.start).total_seconds(), 0.0)


def log_dir() -> Path:
    return config_dir() / "sessions"


def log_path(game_id: str) -> Path:
    return log_dir() / f"{game_id}.json"


def _stamp(when: _dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S")


def load(game_id: str) -> list[Session]:
    """Oldest first. Never raises; entries that do not parse are skipped."""
    try:
        raw = json.loads(log_path(game_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    out = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(Session(_dt.datetime.fromisoformat(item["start"]),
                               _dt.datetime.fromisoformat(item["end"]),
                               max(float(item["counted"]), 0.0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def record(game_id: str, start: float, end: float, counted: float) -> bool:
    """Add one session (times are Unix seconds). Never raises.

    Returns whether it was kept: a few seconds of a game that was closed
    straight away is not worth a line.
    """
    if counted < MIN_COUNTED or end <= start:
        return False
    sessions = load(game_id)
    sessions.append(Session(_dt.datetime.fromtimestamp(start).replace(microsecond=0),
                            _dt.datetime.fromtimestamp(end).replace(microsecond=0),
                            float(counted)))
    sessions = sessions[-KEEP:]
    data = [{"start": _stamp(s.start), "end": _stamp(s.end), "counted": round(s.counted, 1)}
            for s in sessions]
    path = log_path(game_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=0), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:  # pragma: no cover - disk trouble
        log.debug("could not write %s", path, exc_info=True)
        return False
    return True


def newest_first(game_id: str, limit: int | None = None) -> list[Session]:
    sessions = list(reversed(load(game_id)))
    return sessions if limit is None else sessions[:limit]


def describe(session: Session, now: _dt.datetime | None = None) -> tuple[str, str, str]:
    """(day, "21:04 - 23:40", "2h 31m") for one row of the list."""
    from .library_view import format_last_played
    from .stats import format_clock

    day = format_last_played(_stamp(session.start), now)
    if day not in ("Today", "Yesterday"):
        day = f"{session.start.strftime('%a')} {session.start.day} {session.start.strftime('%b')}"
        if now is not None and session.start.year != now.year:
            day += f" {session.start.year}"
    span = f"{session.start.strftime('%H:%M')} – {session.end.strftime('%H:%M')}"
    if session.end.date() != session.start.date():
        span += " (+1)"
    return day, span, format_clock(session.counted)
