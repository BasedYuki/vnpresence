"""Colours for the window, and the machinery that applies them.

Tkinter's own widgets look like Windows 95 and ignore most styling. The ``clam``
ttk theme is the one that does not: every colour it uses can be set, so that is
what everything here builds on.

A palette is eight colours and nothing else. No images, no fonts to ship, no
per-widget special cases - which is what makes adding one a ten-line change
rather than a rewrite, and why the themes stay consistent with each other.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """Every colour the window uses."""

    name: str
    label: str
    background: str  # the window itself
    surface: str  # lists, entries, anything holding content
    text: str
    muted: str  # secondary text: the status line, hints
    accent: str  # the primary button, focus rings, the selected row
    accent_text: str  # text that sits on `accent`
    border: str

    @property
    def stripe(self) -> str:
        """Alternate row colour - the surface, nudged toward the background."""
        return _mix(self.surface, self.background, 0.45)

    @property
    def hover(self) -> str:
        return _mix(self.surface, self.accent, 0.18)

    @property
    def pressed(self) -> str:
        return _mix(self.accent, "#000000", 0.2)


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(first: str, second: str, amount: float) -> str:
    """Blend two colours; `amount` is how much of `second` to use."""
    amount = min(max(amount, 0.0), 1.0)
    a, b = _hex(first), _hex(second)
    blended = tuple(round(x + (y - x) * amount) for x, y in zip(a, b))
    return "#{:02x}{:02x}{:02x}".format(*blended)


#: Every palette VNPresence ships. The first is the default.
PALETTES: dict[str, Palette] = {
    "midnight": Palette(
        name="midnight",
        label="Midnight (default)",
        background="#16181d",
        surface="#1e2129",
        text="#e6e8ee",
        muted="#9aa0ad",
        # The purple from the app's own icon, taken down far enough that white
        # text on it clears 4.5:1 - the lighter shade looked right and read
        # badly, which tests/test_theme.py now refuses to let happen again.
        accent="#6f5ae6",
        accent_text="#ffffff",
        border="#2b2f3a",
    ),
    "daylight": Palette(
        name="daylight",
        label="Daylight",
        background="#f4f5f8",
        surface="#ffffff",
        text="#1b1e26",
        muted="#5f6674",
        accent="#6d5ae0",
        accent_text="#ffffff",
        border="#d9dce4",
    ),
    # An original palette, not artwork: deep ocean blue and gold, the colours
    # those games are remembered for. No logos, emblems or characters - just
    # eight hex values.
    "kingdom-hearts": Palette(
        name="kingdom-hearts",
        label="Kingdom Hearts",
        background="#050c22",
        surface="#0e1c46",
        text="#eaf1ff",
        muted="#93a8d8",
        accent="#f5c542",  # the gold those title screens are lit by
        accent_text="#081434",
        border="#1d346f",
    ),
}

DEFAULT = "midnight"


def get(name: str | None) -> Palette:
    """The named palette, falling back to the default rather than failing.

    A config file can name a theme that a later version removed, and that is
    not worth refusing to open the window over.
    """
    return PALETTES.get((name or "").strip().lower(), PALETTES[DEFAULT])


def names() -> list[str]:
    return list(PALETTES)


def labels() -> list[str]:
    return [palette.label for palette in PALETTES.values()]


def by_label(label: str) -> Palette:
    for palette in PALETTES.values():
        if palette.label == label:
            return palette
    return PALETTES[DEFAULT]


def apply(root, name: str | None = None):  # pragma: no cover - needs a real Tk
    """Paint the window. Returns the palette that was applied.

    Everything is styled through ``clam``: it is the only built-in ttk theme
    that honours colour settings on every widget, which is what lets one
    palette cover the whole window instead of half of it.
    """
    from tkinter import ttk

    palette = get(name)
    style = ttk.Style(root)
    # clam is what makes the colours stick; without it they are ignored, but
    # the window still opens, which is the part that matters.
    with contextlib.suppress(Exception):
        style.theme_use("clam")

    root.configure(background=palette.background)

    style.configure(".", background=palette.background, foreground=palette.text,
                    fieldbackground=palette.surface, bordercolor=palette.border,
                    lightcolor=palette.border, darkcolor=palette.border,
                    focuscolor=palette.accent, troughcolor=palette.background)
    style.configure("TFrame", background=palette.background)
    style.configure("TLabel", background=palette.background, foreground=palette.text)
    style.configure("Muted.TLabel", foreground=palette.muted)
    style.configure("Heading.TLabel", foreground=palette.text, font=("Segoe UI", 11, "bold"))

    style.configure("TButton", background=palette.surface, foreground=palette.text,
                    bordercolor=palette.border, focusthickness=1, padding=(10, 5),
                    relief="flat")
    style.map("TButton",
              background=[("pressed", palette.pressed), ("active", palette.hover)],
              foreground=[("disabled", palette.muted)])

    # One button carries the main action; the rest stay quiet around it.
    style.configure("Accent.TButton", background=palette.accent,
                    foreground=palette.accent_text, relief="flat", padding=(14, 6))
    style.map("Accent.TButton",
              background=[("pressed", palette.pressed),
                          ("active", _mix(palette.accent, "#ffffff", 0.15))],
              foreground=[("disabled", palette.muted)])

    style.configure("TEntry", fieldbackground=palette.surface, foreground=palette.text,
                    insertcolor=palette.text, bordercolor=palette.border, padding=6)
    style.map("TEntry", bordercolor=[("focus", palette.accent)])

    style.configure("TCombobox", fieldbackground=palette.surface, background=palette.surface,
                    foreground=palette.text, arrowcolor=palette.muted,
                    bordercolor=palette.border, padding=4)
    style.map("TCombobox",
              fieldbackground=[("readonly", palette.surface)],
              bordercolor=[("focus", palette.accent)])

    style.configure("TCheckbutton", background=palette.background, foreground=palette.text,
                    indicatorcolor=palette.surface, focuscolor=palette.accent)
    style.map("TCheckbutton",
              indicatorcolor=[("selected", palette.accent)],
              foreground=[("disabled", palette.muted)])

    style.configure("Treeview", background=palette.surface, fieldbackground=palette.surface,
                    foreground=palette.text, bordercolor=palette.border, rowheight=26,
                    relief="flat")
    style.map("Treeview",
              background=[("selected", palette.accent)],
              foreground=[("selected", palette.accent_text)])
    style.configure("Treeview.Heading", background=palette.background,
                    foreground=palette.muted, relief="flat", padding=(8, 6))
    style.map("Treeview.Heading", background=[("active", palette.hover)])

    style.configure("TSeparator", background=palette.border)
    style.configure("Vertical.TScrollbar", background=palette.surface,
                    troughcolor=palette.background, arrowcolor=palette.muted,
                    bordercolor=palette.background)
    return palette
