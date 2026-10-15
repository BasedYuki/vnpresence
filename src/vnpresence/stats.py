"""The numbers on a game's page: how long, how often, how far, and when.

Worked out from :class:`~vnpresence.playtime.Entry` and nothing else, away from
Tk, so the page, the tests and anything later that wants the same figures all
get the same answer.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from .playtime import Entry


def _today(today: _dt.date | None) -> _dt.date:
    return today or _dt.date.today()


def _day(text: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def daily(entry: Entry | None, days: int = 30, today: _dt.date | None = None,
          ) -> list[tuple[_dt.date, float]]:
    """The last ``days`` calendar days, oldest first, with the seconds read on
    each. Days with no reading are there as zero - a gap in the chart is the
    point of the chart."""
    today = _today(today)
    record = (entry.days if entry else {}) or {}
    out = []
    for back in range(days - 1, -1, -1):
        day = today - _dt.timedelta(days=back)
        out.append((day, float(record.get(day.isoformat(), 0.0))))
    return out


def weekly(entry: Entry | None, weeks: int = 12, today: _dt.date | None = None,
           ) -> list[tuple[_dt.date, float]]:
    """The last ``weeks`` weeks, oldest first, each keyed by its Monday."""
    today = _today(today)
    this_monday = today - _dt.timedelta(days=today.weekday())
    first = this_monday - _dt.timedelta(weeks=weeks - 1)
    totals = {first + _dt.timedelta(weeks=n): 0.0 for n in range(weeks)}
    for text, seconds in ((entry.days if entry else {}) or {}).items():
        day = _day(text)
        if day is None or day < first or day > today:
            continue
        monday = day - _dt.timedelta(days=day.weekday())
        totals[monday] = totals.get(monday, 0.0) + float(seconds)
    return sorted(totals.items())


def last_days(entry: Entry | None, days: int = 7, today: _dt.date | None = None) -> float:
    """Seconds read in the last ``days`` days, today included."""
    return sum(seconds for _day_, seconds in daily(entry, days, today))


def history_since(entry: Entry | None) -> _dt.date | None:
    """The first day with a per-day record - where the chart's memory starts."""
    found = [d for d in (_day(t) for t in ((entry.days if entry else {}) or {})) if d]
    return min(found) if found else None


# -- how it reads ---------------------------------------------------------
def format_clock(seconds: float | None) -> str:
    """``115740`` -> ``"32h 09m"``. Minutes are zero-padded so a column of
    these lines up; under an hour it is just ``"9m"``."""
    seconds = max(float(seconds or 0), 0.0)
    hours, minutes = divmod(int(seconds) // 60, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def format_axis(seconds: float) -> str:
    """Chart axis labels: ``0m``, ``30m``, ``1h``, ``1h 30m``."""
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


#: Steps the chart's axis may use, in seconds: 15m, 30m, 1h, 2h, 3h, 5h, 10h...
_STEPS = (900, 1800, 3600, 7200, 10800, 18000, 36000, 72000, 180000)


def axis_ticks(top: float, most: int = 4) -> list[float]:
    """Round values for the chart's axis, from 0 to just above ``top``.

    At most ``most`` steps, each a time a person would say out loud - never
    "1h 13m" as a grid line.
    """
    top = max(float(top or 0), 1.0)
    step = next((s for s in _STEPS if top / s <= most), _STEPS[-1])
    count = int(-(-top // step))  # ceiling
    return [step * n for n in range(count + 1)]


@dataclass(frozen=True)
class Progress:
    """How far through a game the reading time suggests, against VNDB."""

    fraction: float  # 0.8 for 80%; can pass 1.0
    average_seconds: float

    @property
    def percent(self) -> int:
        return int(round(self.fraction * 100))

    @property
    def bar(self) -> float:
        """For drawing: the bar fills up and stops there."""
        return min(max(self.fraction, 0.0), 1.0)

    def describe(self) -> str:
        hours = self.average_seconds / 3600
        average = f"~{hours:.0f}h" if hours >= 1.5 else f"~{self.average_seconds / 60:.0f}m"
        return f"{self.percent}% · average {average}"


def progress(seconds: float | None, length_minutes: int | None) -> Progress | None:
    """Reading time against VNDB's average, or None without an average.

    An estimate and labelled as one: reading speed, skipped text and how many
    routes count as "finished" all move it, so it is never shown as anything
    but a comparison with other readers.
    """
    if not length_minutes or length_minutes <= 0:
        return None
    average = float(length_minutes) * 60
    return Progress(max(float(seconds or 0), 0.0) / average, average)
