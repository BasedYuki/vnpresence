"""Small, smooth movement: a pill that slides to the chosen tab.

Two controls, both drawn on a Tk canvas because ttk's own tabs and toggles can
only jump from one state to the next:

* :class:`PillSwitch` - a segmented control (List / Grid). The highlighted
  pill glides to the option you click instead of flicking over.
* :class:`SmoothTabs` - a row of tabs with a pill that slides and stretches to
  the tab you pick, and the new tab's page easing up into place.

The motion itself is one function, :func:`ease_out_cubic`, stepped by
:class:`Tween` at about 60 frames a second: fast at the start, settling gently
at the end, the way a physical thing comes to rest. Each tween lasts a quarter
of a second at most - long enough to read as motion, short enough never to
make anyone wait for it. A new movement takes over from the one in flight
from wherever it has got to, so clicking quickly never jumps or stutters.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .easing import FRAME_MS, RISE_PX, SLIDE_MS, frames, lerp
from .theme import Palette, _mix


class Tween:
    """Runs ``step(progress)`` once a frame on ``widget``'s clock.

    Starting a new tween on the same object cancels the old one: the caller
    starts the new movement from wherever the old one had reached.
    """

    def __init__(self, widget) -> None:
        self.widget = widget
        self._job = None

    def run(self, step, duration_ms: int = SLIDE_MS, done=None) -> None:
        self.cancel()
        plan = frames(duration_ms)

        def tick(index: int = 0) -> None:
            self._job = None
            try:
                step(plan[index])
            except tk.TclError:
                return  # the widget went away mid-movement
            if index + 1 < len(plan):
                self._job = self.widget.after(FRAME_MS, tick, index + 1)
            elif done is not None:
                done()

        tick()

    def cancel(self) -> None:
        if self._job is not None:
            with contextlib.suppress(Exception):
                self.widget.after_cancel(self._job)
            self._job = None


def round_rect(canvas, x0, y0, x1, y1, radius, **options):
    """A rounded rectangle, as one smooth polygon - Tk has none built in."""
    r = max(min(radius, (x1 - x0) / 2, (y1 - y0) / 2), 0)
    points = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
              x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **options)


def move_round_rect(canvas, item, x0, y0, x1, y1, radius) -> None:
    r = max(min(radius, (x1 - x0) / 2, (y1 - y0) / 2), 0)
    canvas.coords(item, x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
                  x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0)


class _PillRow(tk.Canvas):
    """What both controls share: labels in a row, and a pill that slides."""

    PAD_X, GAP, HEIGHT, RADIUS = 14, 4, 32, 9

    def __init__(self, master, labels: list[str], palette: Palette, *, track: bool,
                 font=("Segoe UI", 10, "bold")) -> None:
        super().__init__(master, height=self.HEIGHT, highlightthickness=0, borderwidth=0)
        self.labels = labels
        self.track = track
        self.font = tkfont.Font(root=master, font=font)
        self.selected = 0
        self.hovered: int | None = None
        self._tween = Tween(self)
        self._slots: list[tuple[float, float]] = []
        x = 3 if track else 0
        for text in labels:
            width = self.font.measure(text) + 2 * self.PAD_X
            self._slots.append((x, x + width))
            x += width + self.GAP
        self.configure(width=int(x - self.GAP + (3 if track else 0)))
        self._pill_at = list(self._slots[0])
        self.recolor(palette)
        self.bind("<Button-1>", self._clicked)
        self.bind("<Motion>", self._hover)
        self.bind("<Leave>", lambda _e: self._hover(None))
        self.configure(cursor="hand2")

    # -- drawing ------------------------------------------------------------
    def recolor(self, palette: Palette) -> None:
        self.palette = palette
        self.configure(background=self._behind())
        self._draw()

    def _behind(self) -> str:
        return self.palette.background

    def _pill_colour(self) -> str:
        return self.palette.accent

    def _under_pill(self, index: int) -> bool:
        """Whether the pill is sitting on this label right now - mid-glide
        included, so a label is never drawn in pill colours on bare track."""
        x0, x1 = self._slots[index]
        centre = (x0 + x1) / 2
        return self._pill_at[0] <= centre <= self._pill_at[1]

    def _text_colour(self, index: int) -> str:
        if self._under_pill(index):
            return self.palette.accent_text
        if index == self.hovered:
            return self.palette.text
        return self.palette.muted

    def _draw(self) -> None:
        self.delete("all")
        top, bottom = 3, self.HEIGHT - 3
        if self.track:
            round_rect(self, 0, 0, int(self.cget("width")), self.HEIGHT, self.RADIUS + 3,
                       fill=self.palette.surface, outline="")
        self._pill = round_rect(self, self._pill_at[0], top, self._pill_at[1], bottom,
                                self.RADIUS, fill=self._pill_colour(), outline="")
        self._texts = []
        for index, (x0, x1) in enumerate(self._slots):
            self._texts.append(self.create_text((x0 + x1) / 2, self.HEIGHT / 2,
                                                text=self.labels[index], font=self.font,
                                                fill=self._text_colour(index)))

    def _paint_texts(self) -> None:
        for index, item in enumerate(self._texts):
            self.itemconfigure(item, fill=self._text_colour(index))

    # -- movement -----------------------------------------------------------
    def glide_to(self, index: int, *, animate: bool = True) -> None:
        index = min(max(index, 0), len(self._slots) - 1)
        self.selected = index
        start, end = tuple(self._pill_at), self._slots[index]
        self._paint_texts()
        top, bottom = 3, self.HEIGHT - 3

        def step(t: float) -> None:
            self._pill_at = [lerp(start[0], end[0], t), lerp(start[1], end[1], t)]
            move_round_rect(self, self._pill, *[self._pill_at[0], top, self._pill_at[1],
                                                bottom], self.RADIUS)
            self._paint_texts()

        if animate:
            self._tween.run(step)
        else:
            self._tween.cancel()
            step(1.0)

    def _index_at(self, x: float) -> int | None:
        for index, (x0, x1) in enumerate(self._slots):
            if x0 <= x <= x1:
                return index
        return None

    def _hover(self, event) -> None:
        hovered = None if event is None else self._index_at(event.x)
        if hovered != self.hovered:
            self.hovered = hovered
            self._paint_texts()

    def _clicked(self, event) -> None:
        index = self._index_at(event.x)
        if index is not None and index != self.selected:
            self.glide_to(index)
            self.chosen(index)

    def chosen(self, index: int) -> None:  # pragma: no cover - overridden
        pass


class PillSwitch(_PillRow):
    """A segmented control bound to a StringVar: List | Grid."""

    def __init__(self, master, options: list[tuple[str, str]], variable: tk.StringVar,
                 palette: Palette, command=None) -> None:
        self.values = [value for value, _ in options]
        self.variable = variable
        self.command = command
        super().__init__(master, [text for _, text in options], palette, track=True)
        current = variable.get()
        if current in self.values:
            self.glide_to(self.values.index(current), animate=False)
        # Changed from elsewhere (Ctrl+G): the pill follows.
        variable.trace_add("write", lambda *_: self._follow())

    def _follow(self) -> None:
        value = self.variable.get()
        if value in self.values and self.values.index(value) != self.selected:
            self.glide_to(self.values.index(value))

    def chosen(self, index: int) -> None:
        self.variable.set(self.values[index])
        if self.command is not None:
            self.command()


class SmoothTabs(ttk.Frame):
    """Tabs with a sliding pill, and each page rising softly into view.

    Built like ttk.Notebook: ``add(frame, text)`` for each page (the frame's
    parent must be :attr:`body`), then :meth:`show` picks one.
    """

    def __init__(self, master, palette: Palette, *, on_change=None) -> None:
        super().__init__(master)
        self.palette = palette
        self.on_change = on_change
        self.pages: list[ttk.Frame] = []
        self.titles: list[str] = []
        self.current = 0
        self._strip_holder = ttk.Frame(self)
        self._strip_holder.pack(fill="x")
        self.strip: _TabStrip | None = None
        self.body = tk.Frame(self, background=palette.surface, highlightthickness=0)
        self.body.pack(fill="both", expand=True, pady=(8, 0))
        self._rise = Tween(self.body)

    def add(self, page, text: str) -> None:
        self.pages.append(page)
        self.titles.append(text)
        if self.strip is not None:
            self.strip.destroy()
        self.strip = _TabStrip(self._strip_holder, self.titles, self.palette, self)
        self.strip.pack(side="left")
        if len(self.pages) == 1:
            self.show(0, animate=False)

    def show(self, index: int, *, animate: bool = True) -> None:
        index = min(max(index, 0), len(self.pages) - 1)
        for page in self.pages:
            page.place_forget()
        page = self.pages[index]
        self.current = index
        if self.strip is not None and self.strip.selected != index:
            self.strip.glide_to(index, animate=animate)
        if not animate:
            page.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            def rise(t: float) -> None:
                page.place(x=0, y=round(RISE_PX * (1 - t)), relwidth=1, relheight=1)

            self._rise.run(rise)
        if self.on_change is not None:
            self.on_change(index)


class _TabStrip(_PillRow):
    def __init__(self, master, labels, palette, owner: SmoothTabs) -> None:
        self.owner = owner
        super().__init__(master, labels, palette, track=False)
        self.glide_to(owner.current, animate=False)

    def _pill_colour(self) -> str:
        # Quieter than the List/Grid switch: a tint of the accent, with the
        # tab's name in the accent itself.
        return _mix(self.palette.background, self.palette.accent, 0.22)

    def _text_colour(self, index: int) -> str:
        if self._under_pill(index):
            return self.palette.accent
        if index == self.hovered:
            return self.palette.text
        return self.palette.muted

    def chosen(self, index: int) -> None:
        self.owner.show(index)
