"""Undo time that was counted twice, once, after updating.

Before 0.18.1 the window's Play and the background auto-detect could both
track the same game at once, and each added the evening to the history: the
total and that day on the heatmap came out doubled. The cause is gone
(see :mod:`claims`); this finds what it left behind.

Two sessions of the same game that overlap in time cannot both be real - you
cannot play one novel twice at the same moment - and since 0.18 every session
is in the session log with its start, its end and what it counted. So for each
overlapping pair the smaller one is the duplicate: it comes out of the log,
its time comes off the day it was counted on, and the session count drops by
one. The total is corrected too, unless the reader already corrected it by
hand (a total lower than its own day-by-day history says exactly that).

It runs once, at start-up, and remembers that it did.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from . import session_log
from .config import config_dir
from .playtime import Playtime

log = logging.getLogger(__name__)

MARKER = "repaired-double-count-v1"
#: How much two sessions must overlap to be one evening counted twice: most
#: of the shorter one. A game closed at 22:00 and reopened at 22:01 is not.
OVERLAP_SHARE = 0.5


@dataclass(frozen=True)
class Fixed:
    game_id: str
    seconds: float
    sessions: int


def duplicates(sessions: list[session_log.Session]) -> list[session_log.Session]:
    """The sessions that are another session counted a second time."""
    ordered = sorted(sessions, key=lambda s: s.start)
    dropped: list[session_log.Session] = []
    kept: list[session_log.Session] = []
    for session in ordered:
        twin = next((k for k in kept if _overlap(k, session) >=
                     OVERLAP_SHARE * max(min(k.wall, session.wall), 1.0)), None)
        if twin is None:
            kept.append(session)
        elif session.counted <= twin.counted:
            dropped.append(session)
        else:
            kept.remove(twin)
            kept.append(session)
            dropped.append(twin)
    return dropped


def _overlap(a: session_log.Session, b: session_log.Session) -> float:
    start, end = max(a.start, b.start), min(a.end, b.end)
    return max((end - start).total_seconds(), 0.0)


def _marker_path():
    return config_dir() / ".repairs" / MARKER


def already_done() -> bool:
    return _marker_path().exists()


def repair(playtime: Playtime | None = None) -> list[Fixed]:
    """Find and undo double-counted sessions in every game. Never raises."""
    playtime = playtime or Playtime()
    fixed: list[Fixed] = []
    folder = session_log.log_dir()
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        game_id = path.stem
        try:
            sessions = session_log.load(game_id)
            extra = duplicates(sessions)
            if not extra:
                continue
            entry = playtime.get(game_id)
            hand_set = entry.seconds < sum(entry.days.values())
            seconds = 0.0
            for dup in extra:
                playtime.take_back(game_id, dup.counted, day=dup.start.date().isoformat(),
                                   sessions=1, total=not hand_set)
                seconds += dup.counted
            _rewrite_log(game_id, [s for s in sessions if s not in extra])
            fixed.append(Fixed(game_id, seconds, len(extra)))
            log.info("removed %d double-counted session(s) from %s", len(extra), game_id)
        except Exception:
            log.warning("could not check %s for double counting", game_id, exc_info=True)
    return fixed


def _rewrite_log(game_id: str, sessions: list[session_log.Session]) -> None:
    path = session_log.log_path(game_id)
    data = [{"start": s.start.strftime("%Y-%m-%dT%H:%M:%S"),
             "end": s.end.strftime("%Y-%m-%dT%H:%M:%S"),
             "counted": round(s.counted, 1)} for s in sessions]
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=0), encoding="utf-8")
    os.replace(temporary, path)


def repair_once() -> list[Fixed]:
    """:func:`repair`, the first time it is called on this computer only."""
    if already_done():
        return []
    fixed = repair()
    try:
        _marker_path().parent.mkdir(parents=True, exist_ok=True)
        _marker_path().write_text(json.dumps(
            [{"game": f.game_id, "seconds": round(f.seconds), "sessions": f.sessions}
             for f in fixed]), encoding="utf-8")
    except OSError:  # pragma: no cover
        log.debug("could not remember the repair", exc_info=True)
    return fixed
