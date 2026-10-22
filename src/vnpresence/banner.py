"""The wide picture across the top of a game's page.

The cover, blown up to fill the width, blurred until it is colour and mood
rather than a picture, and washed toward the page's background so the title
written over it reads in the theme's own text colour on any cover. A private
or 18+ game gets no cover at all here - a blur still shows shapes and colours
- just a soft gradient from the theme into its accent.
"""

from __future__ import annotations

from pathlib import Path

from . import theme


def _gradient(size, start: str, end: str):
    from PIL import Image

    width, height = size
    a, b = theme._hex(start), theme._hex(end)
    image = Image.new("RGB", size)
    pixels = image.load()
    for x in range(width):
        for y in range(0, height):
            t = min(max((x / max(width, 1)) * 0.75 + (y / max(height, 1)) * 0.25, 0), 1)
            pixels[x, y] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return image


def _wash_mask(size):
    """How much of the page colour lies over the blur at each point: more at
    the bottom and on the left, where the title is written."""
    from PIL import Image

    columns, rows = 48, 12
    mask = Image.new("L", (columns, rows))
    pixels = mask.load()
    for x in range(columns):
        for y in range(rows):
            down, left = y / (rows - 1), 1 - x / (columns - 1)
            pixels[x, y] = round(120 + 95 * down + 30 * left * down)
    return mask.resize(size, Image.BILINEAR)


def render(cover: Path | None, size: tuple[int, int], palette: theme.Palette, *,
           hide: bool = False):
    """A PIL image exactly ``size``, ready to put behind the title."""
    from PIL import Image, ImageFilter, ImageOps

    width, height = max(size[0], 1), max(size[1], 1)
    background = palette.background
    if cover is not None and not hide:
        try:
            with Image.open(cover) as raw:
                small = ImageOps.fit(raw.convert("RGB"), (max(width // 4, 1), max(height // 4, 1)))
            picture = small.filter(ImageFilter.GaussianBlur(4)).resize((width, height))
            picture = picture.filter(ImageFilter.GaussianBlur(10))
            wash = Image.new("RGB", (width, height), background)
            return Image.composite(wash, picture, _wash_mask((width, height)))
        except Exception:
            pass
    small = _gradient((max(width // 8, 2), max(height // 8, 2)), background,
                      theme._mix(background, palette.accent, 0.35))
    return small.resize((width, height), Image.BILINEAR)
