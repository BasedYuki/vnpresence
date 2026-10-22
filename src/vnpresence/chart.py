"""The bar chart on a game's page: time played per day, or per week.

The geometry is worked out by :func:`layout`, which knows nothing about Tk -
so the part that can be wrong (where a bar goes, how tall, which days get a
label) is tested on its own, and :func:`draw` only paints what it is given.

One series, one colour: the theme's accent. Bars have rounded-off tops in
spirit only (Tk rectangles), thin gaps between them, light grid lines behind,
and the best day labelled with its value - the one number worth reading off
a chart like this without hovering.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from .stats import axis_ticks, format_axis, format_clock

#: Room for the axis labels on the left and the dates underneath.
LEFT, BOTTOM, TOP, RIGHT = 58, 22, 18, 6


@dataclass(frozen=True)
class Bar:
    x0: float
    y0: float
    x1: float
    y1: float
    when: _dt.date
    seconds: float


@dataclass(frozen=True)
class Layout:
    bars: list[Bar]
    gridlines: list[tuple[float, str]]  # y, label
    labels: list[tuple[float, str]]  # x centre, date text
    peak: Bar | None  # the tallest bar, labelled with its value


def _date_label(day: _dt.date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def layout(points: list[tuple[_dt.date, float]], width: int, height: int, *,
           weekly: bool = False) -> Layout:
    """Where everything goes on a ``width`` x ``height`` canvas."""
    plot_w = max(width - LEFT - RIGHT, 10)
    plot_h = max(height - TOP - BOTTOM, 10)
    top_value = max((s for _d, s in points), default=0.0)
    ticks = axis_ticks(top_value or 3600)
    scale_top = ticks[-1]

    def y_for(seconds: float) -> float:
        return TOP + plot_h - (seconds / scale_top) * plot_h

    gridlines = [(y_for(t), format_axis(t)) for t in ticks]
    count = max(len(points), 1)
    slot = plot_w / count
    gap = max(min(slot * 0.28, 8.0), 1.0)
    bars = []
    for index, (day, seconds) in enumerate(points):
        x0 = LEFT + index * slot + gap / 2
        x1 = LEFT + (index + 1) * slot - gap / 2
        if seconds <= 0:
            continue
        # A minute of reading is still visibly a bar, not a hairline.
        y0 = min(y_for(seconds), TOP + plot_h - 2)
        bars.append(Bar(x0, y0, x1, TOP + plot_h, day, seconds))

    # Dates under the bars: about six of them, whatever the range.
    every = max(count // 6, 1)
    labels = []
    for index, (day, _seconds) in enumerate(points):
        if (count - 1 - index) % every == 0:
            labels.append((LEFT + (index + 0.5) * slot, _date_label(day)))
    peak = max(bars, key=lambda b: b.seconds) if bars else None
    return Layout(bars, gridlines, labels, peak)


def draw(canvas, points, palette, *, weekly: bool = False) -> list[Bar]:  # pragma: no cover
    """Paint the chart. Returns the bars, for hover."""
    canvas.delete("all")
    width = int(canvas.winfo_width() or canvas.cget("width"))
    height = int(canvas.winfo_height() or canvas.cget("height"))
    plan = layout(points, width, height, weekly=weekly)
    small = ("Segoe UI", 8)
    for y, text in plan.gridlines:
        canvas.create_line(LEFT, y, width - RIGHT, y, fill=palette.border)
        canvas.create_text(LEFT - 8, y, text=text, anchor="e", fill=palette.muted, font=small)
    for bar in plan.bars:
        canvas.create_rectangle(bar.x0, bar.y0, bar.x1, bar.y1, fill=palette.accent,
                                outline="", tags=("bar",))
    for x, text in plan.labels:
        # Kept inside the canvas: the newest day is at the right-hand edge.
        x = min(max(x, LEFT + 18), width - RIGHT - 20)
        canvas.create_text(x, height - BOTTOM + 12, text=text, fill=palette.muted, font=small)
    if plan.peak is not None:
        peak = plan.peak
        canvas.create_text((peak.x0 + peak.x1) / 2, peak.y0 - 8,
                           text=format_clock(peak.seconds), fill=palette.text,
                           font=("Segoe UI", 8, "bold"))
    if not plan.bars:
        note = canvas.create_text(LEFT + (width - LEFT) / 2, TOP + (height - TOP - BOTTOM) / 2,
                                  text="Nothing played in this stretch yet",
                                  fill=palette.muted, font=("Segoe UI", 9))
        x0, y0, x1, y1 = canvas.bbox(note)
        backing = canvas.create_rectangle(x0 - 8, y0 - 3, x1 + 8, y1 + 3,
                                          fill=palette.surface, outline="")
        canvas.tag_lower(backing, note)
    return plan.bars


# -- the heatmap ----------------------------------------------------------
HEAT_LEFT, HEAT_TOP, HEAT_GAP = 34, 20, 3


@dataclass(frozen=True)
class Cell:
    x0: float
    y0: float
    x1: float
    y1: float
    when: _dt.date
    seconds: float


def heat_layout(columns, width: int) -> tuple[list[Cell], list[tuple[float, str]], float]:
    """Where each day's square goes; month labels along the top; the height
    the whole thing needs at this width."""
    weeks = max(len(columns), 1)
    size = max(min((width - HEAT_LEFT) / weeks - HEAT_GAP, 18.0), 6.0)
    cells, months, last_month = [], [], None
    for w, column in enumerate(columns):
        x0 = HEAT_LEFT + w * (size + HEAT_GAP)
        for d, (day, seconds) in enumerate(column):
            if seconds is None:
                continue
            y0 = HEAT_TOP + d * (size + HEAT_GAP)
            cells.append(Cell(x0, y0, x0 + size, y0 + size, day, seconds))
        first = column[0][0]
        if first.month != last_month:
            if last_month is not None or first.day <= 7:
                months.append((x0, first.strftime("%b")))
            last_month = first.month
    return cells, months, HEAT_TOP + 7 * (size + HEAT_GAP)


def shade(palette, level: int) -> str:
    """Nothing is a quiet square; each level is a stronger share of the accent."""
    from .theme import _mix

    if level <= 0:
        return _mix(palette.surface, palette.border, 0.85)
    return _mix(palette.surface, palette.accent, (0.32, 0.55, 0.78, 1.0)[min(level, 4) - 1])


def draw_heatmap(canvas, columns, palette) -> list[Cell]:  # pragma: no cover - needs Tk
    from .stats import level

    canvas.delete("all")
    width = int(canvas.winfo_width() or canvas.cget("width"))
    cells, months, height = heat_layout(columns, width)
    canvas.configure(height=height + 4)
    small = ("Segoe UI", 8)
    for x, text in months:
        canvas.create_text(x, HEAT_TOP - 10, text=text, anchor="w", fill=palette.muted, font=small)
    if cells:
        size = cells[0].x1 - cells[0].x0
        for row, text in ((0, "Mon"), (2, "Wed"), (4, "Fri")):
            canvas.create_text(HEAT_LEFT - 6, HEAT_TOP + row * (size + HEAT_GAP) + size / 2,
                               text=text, anchor="e", fill=palette.muted, font=small)
    for index, cell in enumerate(cells):
        canvas.create_rectangle(cell.x0, cell.y0, cell.x1, cell.y1, outline="",
                                fill=shade(palette, level(cell.seconds)),
                                tags=("cell", f"c{index}"))
    return cells
