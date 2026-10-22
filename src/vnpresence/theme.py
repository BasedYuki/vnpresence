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
    # Six originals. Each one is a mood first and a set of hex values second:
    # a background family, one accent, and text tuned on both until the
    # contrast tests pass. The pale accents on dark grounds carry dark text.
    "ink-paper": Palette(
        name="ink-paper",
        label="Ink & Paper",
        background="#efe6d2",  # an old paperback's page
        surface="#f8f2e4",
        text="#2b2118",  # brown-black ink
        muted="#6e5d4a",
        accent="#a8322d",  # the red of a name seal
        accent_text="#fff8ee",
        border="#ddd0b4",
    ),
    "matcha": Palette(
        name="matcha",
        label="Matcha",
        background="#e8eddc",
        surface="#f6f8ef",
        text="#1f2a1b",
        muted="#56634c",
        accent="#3f6b35",  # whisked tea, deep
        accent_text="#f4f8ec",
        border="#d0d9bf",
    ),
    "rainy-night": Palette(
        name="rainy-night",
        label="Rainy Night",
        background="#141b22",
        surface="#1c2630",
        text="#dde7ee",
        muted="#8ea0ad",
        accent="#4fd1c5",  # a sign reflected in a puddle
        accent_text="#06201e",
        border="#2a3743",
    ),
    "summer-dusk": Palette(
        name="summer-dusk",
        label="Summer Dusk",
        background="#211a2c",
        surface="#2c2339",
        text="#f3e9f0",
        muted="#b3a2bb",
        accent="#ff9a52",  # the last of the sun
        accent_text="#2a1406",
        border="#3d3150",
    ),
    "neon": Palette(
        name="neon",
        label="Neon",
        background="#0b0b10",
        surface="#15151d",
        text="#f1f0ff",
        muted="#a09fbd",
        accent="#ff3fa4",
        accent_text="#1a0010",
        border="#2a2a3a",
    ),
    "crimson-moon": Palette(
        name="crimson-moon",
        label="Crimson Moon",
        background="#120a0c",
        surface="#1d1013",
        text="#f2e4e4",
        muted="#b09294",
        accent="#d63a46",
        accent_text="#ffffff",
        border="#35191e",
    ),
}

DEFAULT = "midnight"

#: Themes that existed once and were replaced, and the one each reader gets
#: instead: light stays light, dark stays dark, the mood stays close.
RETIRED = {
    "sakura": "ink-paper",
    "lavender": "matcha",
    "lilac-dusk": "summer-dusk",
    "steel": "rainy-night",
    "navy": "rainy-night",
    "forest": "crimson-moon",
}


def get(name: str | None) -> Palette:
    """The named palette, falling back to the default rather than failing.

    A config file can name a theme that a later version removed, and that is
    not worth refusing to open the window over.
    """
    key = (name or "").strip().lower()
    key = RETIRED.get(key, key)
    return PALETTES.get(key, PALETTES[DEFAULT])


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

    # The cover grid: a tile is the surface colour, the chosen one the accent,
    # the same way the list marks its selected row.
    style.configure("Tile.TFrame", background=palette.background)
    style.configure("TileSelected.TFrame", background=palette.accent)
    style.configure("Tile.TLabel", background=palette.background, foreground=palette.text)
    style.configure("TileSelected.TLabel", background=palette.accent,
                    foreground=palette.accent_text)
    style.configure("TileMuted.TLabel", background=palette.background,
                    foreground=palette.muted)
    style.configure("TileSelectedMuted.TLabel", background=palette.accent,
                    foreground=palette.accent_text)

    # List / grid switch: two buttons, the current view lit.
    # A radio button drawn as a toggle: ttk's own "Toolbutton" layout.
    style.configure("View.Toolbutton", background=palette.surface,
                    foreground=palette.text, padding=(10, 5), relief="flat")
    style.map("View.Toolbutton",
              background=[("selected", palette.accent), ("active", palette.hover)],
              foreground=[("selected", palette.accent_text)])

    # The grid's size slider: an accent knob on a quiet track.
    style.configure("Horizontal.TScale", background=palette.accent,
                    troughcolor=palette.border, bordercolor=palette.border,
                    lightcolor=palette.accent, darkcolor=palette.accent, sliderthickness=14,
                    gripcount=0)
    style.map("Horizontal.TScale", background=[("active", _mix(palette.accent, "#ffffff", 0.15))])

    # Details page.
    style.configure("Title.TLabel", foreground=palette.text, font=("Segoe UI", 16, "bold"))
    style.configure("Fact.TLabel", foreground=palette.muted)

    # The game page is made of cards: the surface colour, a hairline border,
    # and everything inside them drawn on the surface too.
    style.configure("Card.TFrame", background=palette.surface, bordercolor=palette.border,
                    lightcolor=palette.border, darkcolor=palette.border,
                    relief="solid", borderwidth=1)
    style.configure("Inner.TFrame", background=palette.surface)
    style.configure("Card.TLabel", background=palette.surface, foreground=palette.text)
    style.configure("CardMuted.TLabel", background=palette.surface, foreground=palette.muted)
    style.configure("CardHeading.TLabel", background=palette.surface, foreground=palette.text,
                    font=("Segoe UI", 11, "bold"))
    style.configure("CardTitle.TLabel", background=palette.surface, foreground=palette.text,
                    font=("Segoe UI", 18, "bold"))
    style.configure("StatName.TLabel", background=palette.surface, foreground=palette.muted,
                    font=("Segoe UI", 8, "bold"))
    style.configure("StatValue.TLabel", background=palette.surface, foreground=palette.text,
                    font=("Segoe UI", 15, "bold"))
    style.configure("Link.TLabel", background=palette.surface, foreground=palette.accent,
                    font=("Segoe UI", 9, "underline"))
    style.configure("Thumb.TLabel", background=palette.surface)
    style.configure("ThumbSelected.TLabel", background=palette.accent)
    # Buttons and toggles sitting on a card: one step away from the card's
    # colour, so they read as buttons and not as holes.
    chip = _mix(palette.surface, palette.background, 0.6)
    style.configure("Card.TButton", background=chip, foreground=palette.text,
                    bordercolor=palette.border, padding=(10, 4), relief="flat")
    style.map("Card.TButton",
              background=[("pressed", palette.pressed), ("active", palette.hover)],
              foreground=[("disabled", palette.muted)])
    style.configure("Chip.Toolbutton", background=chip, foreground=palette.text,
                    padding=(10, 4), relief="flat")
    style.map("Chip.Toolbutton",
              background=[("selected", palette.accent), ("active", palette.hover)],
              foreground=[("selected", palette.accent_text), ("disabled", palette.muted)])
    style.configure("Card.TCombobox", fieldbackground=chip, background=chip,
                    foreground=palette.text, arrowcolor=palette.muted,
                    bordercolor=palette.border, padding=3)
    style.map("Card.TCombobox", fieldbackground=[("readonly", chip)])
    return palette


def apply_page(root, palette: Palette) -> None:  # pragma: no cover - needs a real Tk
    """Styles for a game's page alone, under the ``Page.`` prefix.

    ttk styles belong to the whole program, so the page's own accent - taken
    from its cover - gets its own names instead of repainting the main window.
    """
    from tkinter import ttk

    style = ttk.Style(root)
    chip = _mix(palette.surface, palette.background, 0.6)
    style.configure("Page.Accent.TButton", background=palette.accent,
                    foreground=palette.accent_text, relief="flat", padding=(16, 7),
                    font=("Segoe UI", 10, "bold"))
    style.map("Page.Accent.TButton",
              background=[("pressed", palette.pressed),
                          ("active", _mix(palette.accent, "#ffffff", 0.15))])
    style.configure("Page.Chip.Toolbutton", background=chip, foreground=palette.text,
                    padding=(10, 4), relief="flat")
    style.map("Page.Chip.Toolbutton",
              background=[("selected", palette.accent), ("active", palette.hover)],
              foreground=[("selected", palette.accent_text), ("disabled", palette.muted)])
    style.configure("Page.TNotebook", background=palette.background, borderwidth=0,
                    tabmargins=(0, 0, 0, 0), lightcolor=palette.background,
                    darkcolor=palette.background, bordercolor=palette.background)
    style.configure("Page.TNotebook.Tab", background=palette.background,
                    foreground=palette.muted, padding=(16, 8), borderwidth=0,
                    lightcolor=palette.background, bordercolor=palette.background,
                    font=("Segoe UI", 10, "bold"))
    style.map("Page.TNotebook.Tab",
              background=[("selected", palette.surface), ("active", palette.hover)],
              foreground=[("selected", palette.accent)],
              lightcolor=[("selected", palette.accent)])
    style.configure("Page.Link.TLabel", background=palette.surface,
                    foreground=palette.accent, font=("Segoe UI", 9, "underline"))
    style.configure("Page.Tag.TLabel", background=chip, foreground=palette.text,
                    padding=(8, 3))
    style.configure("Page.TCheckbutton", background=palette.surface,
                    foreground=palette.text, indicatorcolor=palette.background,
                    focuscolor=palette.accent)
    style.map("Page.TCheckbutton", indicatorcolor=[("selected", palette.accent)])
    style.configure("Page.Treeview", background=palette.surface,
                    fieldbackground=palette.surface, foreground=palette.text, rowheight=28,
                    bordercolor=palette.border, relief="flat")
    style.map("Page.Treeview", background=[("selected", palette.accent)],
              foreground=[("selected", palette.accent_text)])
    style.configure("Page.Treeview.Heading", background=palette.surface,
                    foreground=palette.muted, relief="flat", padding=(8, 6))
