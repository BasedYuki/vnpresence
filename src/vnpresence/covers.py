"""Cover art on disk, for the library grid and the details page.

Discord fetches a cover from its URL by itself; the window cannot. Tk shows
PNG and GIF and nothing else, and VNDB serves JPEG - so covers are downloaded
once, kept in the cache folder, and decoded with Pillow.

Everything here is best effort. A missing cover is a placeholder tile with the
title on it, never an error dialog: the library is for picking a novel, and a
grid that refuses to draw because one image failed is worse than one grey box.
"""

from __future__ import annotations

import hashlib
import logging
import os
import textwrap
from pathlib import Path

import requests

from .config import cache_dir

log = logging.getLogger(__name__)

#: A cover is a few hundred kilobytes. Anything past this is not one.
MAX_COVER_BYTES = 10 * 1024 * 1024

#: The shape of a box. VNDB covers are mostly portrait packages around this.
COVER_RATIO = 1.42


def cover_dir() -> Path:
    return cache_dir() / "covers"


def cover_path(url: str) -> Path:
    """Where the cover at ``url`` lives once downloaded.

    Named after the URL rather than after the game, so a game that was
    re-matched to another VNDB entry gets the other entry's cover instead of
    keeping the first one forever.
    """
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        suffix = ".jpg"
    return cover_dir() / f"{digest}{suffix}"


def cached(url: str | None) -> Path | None:
    """The downloaded cover for ``url``, if there is one."""
    if not url:
        return None
    path = cover_path(url)
    return path if path.is_file() and path.stat().st_size > 0 else None


def download(url: str | None, *, session=None, timeout: float = 15.0) -> Path | None:
    """Fetch a cover into the cache. Returns its path, or None. Never raises."""
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    already = cached(url)
    if already is not None:
        return already
    http = session or requests
    try:
        response = http.get(url, timeout=timeout)
        if getattr(response, "status_code", 0) != 200:
            return None
        body = response.content
        if not body or len(body) > MAX_COVER_BYTES:
            return None
        if not _looks_like_an_image(body):
            return None  # an error page served with a 200, which happens
        path = cover_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside and swapped in: a window drawing the grid must never
        # see half a JPEG.
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(body)
        os.replace(temporary, path)
        return path
    except Exception:
        log.debug("could not download cover %s", url, exc_info=True)
        return None


def _looks_like_an_image(body: bytes) -> bool:
    return (
        body[:3] == b"\xff\xd8\xff"  # JPEG
        or body[:8] == b"\x89PNG\r\n\x1a\n"
        or body[:6] in (b"GIF87a", b"GIF89a")
        or (body[:4] == b"RIFF" and body[8:12] == b"WEBP")
    )


# -- drawing --------------------------------------------------------------
def tile(path: Path | None, size: tuple[int, int], *, title: str = "",
         background: str = "#1e2230", foreground: str = "#e8e8f0"):
    """A Pillow image of exactly ``size``: the cover fitted inside, or a card.

    The same box every time, whatever the source image's shape - which is what
    keeps a grid looking like a shelf rather than a ransom note. Returns None
    only when Pillow itself is missing.
    """
    try:
        from PIL import Image, ImageOps
    except Exception:  # pragma: no cover - Pillow ships in the .exe
        return None

    canvas = Image.new("RGB", size, background)
    if path is not None:
        try:
            with Image.open(path) as source:
                source = ImageOps.exif_transpose(source).convert("RGB")
                fitted = ImageOps.contain(source, size, Image.LANCZOS)
            canvas.paste(fitted, ((size[0] - fitted.width) // 2,
                                  (size[1] - fitted.height) // 2))
            return canvas
        except Exception:
            log.debug("could not draw cover %s", path, exc_info=True)
    return _card(canvas, title, foreground)


def _card(canvas, title: str, foreground: str):
    """No cover: the title, set in the middle, the way PCSX2 does it."""
    from PIL import ImageDraw, ImageFont

    width, height = canvas.size
    draw = ImageDraw.Draw(canvas)
    size = max(12, width // 9)
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - Pillow older than 10.1
        font = ImageFont.load_default()
    lines = textwrap.wrap(title or "?", width=max(8, width // (size // 2 + 1)))[:5]
    line_height = size + 4
    top = (height - line_height * len(lines)) // 2
    for i, line in enumerate(lines):
        box = draw.textbbox((0, 0), line, font=font)
        draw.text(((width - (box[2] - box[0])) // 2, top + i * line_height),
                  line, fill=foreground, font=font)
    return canvas
