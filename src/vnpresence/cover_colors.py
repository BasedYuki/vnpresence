"""A game's page takes its colour from its cover.

The theme stays what the reader picked; only the accent - the Play button,
the lit tab, the heatmap's shades - is borrowed from the cover art, so every
novel's page looks like that novel. The colour picked is the cover's most
present *vivid* one (a grey or a near-black says nothing about a game), then
nudged lighter or darker until it stands out from the page and whatever is
written on it stays readable. A cover that is all greys keeps the theme's own
accent.
"""

from __future__ import annotations

import colorsys
import dataclasses
from pathlib import Path

from . import theme


def _luminance(value: str) -> float:
    channels = []
    for part in theme._hex(value):
        c = part / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio, 1 (identical) to 21 (black on white)."""
    a, b = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(c))) for c in rgb))


def dominant_vivid(path: Path | None) -> str | None:
    """The cover's most present colour that is actually a colour."""
    if path is None:
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            small = image.convert("RGB").resize((64, 64))
        palette = small.quantize(colors=10).convert("RGB").getcolors(64 * 64) or []
    except Exception:
        return None
    best, best_score = None, 0.0
    for count, rgb in palette:
        h, lightness, saturation = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        if saturation < 0.25 or not 0.18 <= lightness <= 0.85:
            continue
        score = count * (saturation ** 1.5)
        if score > best_score:
            best, best_score = rgb, score
    return _hex(best) if best else None


def _with_lightness(value: str, lightness: float) -> str:
    h, _l, s = colorsys.rgb_to_hls(*(c / 255 for c in theme._hex(value)))
    return _hex(c * 255 for c in colorsys.hls_to_rgb(h, lightness, min(s, 0.85)))


def fit_accent(color: str, base: theme.Palette) -> tuple[str, str]:
    """(accent, text on it): the colour moved just far enough to work here.

    It has to stand out from the card it sits on (3:1, the bar for anything
    you click) and carry readable text (4.5:1, white or the theme's darkest).
    """
    dark_page = _luminance(base.surface) < 0.2
    h, start, s = colorsys.rgb_to_hls(*(c / 255 for c in theme._hex(color)))
    # Walk away from the page's own lightness: lighter on dark themes,
    # darker on light ones, in small steps, until both rules hold.
    steps = [start + i * 0.03 * (1 if dark_page else -1) for i in range(0, 30)]
    for lightness in steps:
        if not 0.05 <= lightness <= 0.95:
            break
        accent = _with_lightness(color, lightness)
        for ink in ("#ffffff", "#101014", base.accent_text):
            if contrast(accent, base.surface) >= 3.0 and contrast(ink, accent) >= 4.5:
                return accent, ink
    return base.accent, base.accent_text


def page_palette(base: theme.Palette, cover: Path | None) -> theme.Palette:
    """The theme with the cover's accent - or the theme as it is."""
    color = dominant_vivid(cover)
    if color is None:
        return base
    accent, ink = fit_accent(color, base)
    return dataclasses.replace(base, accent=accent, accent_text=ink)
