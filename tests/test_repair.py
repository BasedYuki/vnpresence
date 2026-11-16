"""Taking back an evening that the window and auto-detect both counted."""

from __future__ import annotations

import datetime as dt
import time

from vnpresence import repair, session_log
from vnpresence.playtime import Entry, Playtime


def at(day: int, hour: int, minute: int = 0) -> float:
    return time.mktime((2026, 11, day, hour, minute, 0, 0, 0, -1))


def doubled_evening(clock: Playtime) -> None:
    """What 0.18.0 wrote for one evening of 1h 24m with Play + auto-detect."""
    session_log.record("tsuki", at(15, 21, 0), at(15, 22, 30), 84 * 60)  # Play
    session_log.record("tsuki", at(15, 21, 1), at(15, 22, 30), 83 * 60)  # watcher
    clock._save({"tsuki": Entry(seconds=167 * 60, sessions=2, last_played="x",
                                days={"2026-11-15": 167 * 60})})


def test_the_twin_session_is_found():
    doubled_evening(Playtime())
    (twin,) = repair.duplicates(session_log.load("tsuki"))
    assert twin.counted == 83 * 60  # the smaller of the two goes


def test_the_evening_comes_back_to_its_real_length():
    clock = Playtime()
    doubled_evening(clock)
    (fixed,) = repair.repair(clock)
    assert fixed.sessions == 1 and fixed.seconds == 83 * 60
    entry = clock.get("tsuki")
    assert entry.seconds == 84 * 60
    assert entry.days == {"2026-11-15": 84 * 60}
    assert entry.sessions == 1
    assert len(session_log.load("tsuki")) == 1


def test_a_total_already_corrected_by_hand_is_left_alone():
    clock = Playtime()
    doubled_evening(clock)
    # The reader fixed the total in Time played... under 0.18.0, which left the
    # day-by-day history as it was: a total smaller than its own history.
    clock._save({"tsuki": Entry(seconds=126 * 60, sessions=2, last_played="x",
                                days={"2026-11-15": 167 * 60})})
    repair.repair(clock)
    entry = clock.get("tsuki")
    assert entry.seconds == 126 * 60  # not lowered a second time
    assert sum(entry.days.values()) <= entry.seconds


def test_sessions_one_after_the_other_are_not_duplicates():
    session_log.record("g", at(15, 20), at(15, 21), 3000)
    session_log.record("g", at(15, 21, 1), at(15, 22), 3000)
    assert repair.duplicates(session_log.load("g")) == []


def test_it_runs_once():
    clock = Playtime()
    doubled_evening(clock)
    assert repair.repair_once()
    doubled_evening(clock)  # even if the same thing were there again
    assert repair.repair_once() == []


def test_lowering_the_total_by_hand_shrinks_the_history_to_fit():
    clock = Playtime()
    clock._save({"g": Entry(seconds=10_000, days={"2026-11-14": 3000, "2026-11-15": 6000})})
    entry = clock.set("g", 4500)
    assert sum(entry.days.values()) == 4500
    assert entry.days["2026-11-15"] == 2 * entry.days["2026-11-14"]  # same shape


def test_raising_the_total_leaves_the_history_alone():
    clock = Playtime()
    clock._save({"g": Entry(seconds=1000, days={"2026-11-15": 900})})
    assert clock.set("g", 50 * 3600).days == {"2026-11-15": 900}


def test_take_back_spills_into_the_next_day_after_midnight():
    clock = Playtime()
    clock._save({"g": Entry(seconds=9000, days={"2026-11-15": 600, "2026-11-16": 3000})})
    entry = clock.take_back("g", 1800, day="2026-11-15", sessions=1)
    assert entry.days == {"2026-11-16": 1800}
    assert entry.seconds == 7200
    assert dt.date(2026, 11, 16).isoformat() in entry.days
