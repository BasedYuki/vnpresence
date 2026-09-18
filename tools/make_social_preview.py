"""Draw the repository's social preview card (1280x640).

Run with:  python tools/make_social_preview.py
Writes assets/social-preview.png - upload it under
Settings -> General -> Social preview.

The right half is a mock of the real Discord activity, because the fastest way
to explain what the project does is to show what it produces.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 640
BACKGROUND = (18, 19, 26)
PANEL = (32, 34, 45)
PANEL_EDGE = (48, 50, 66)
WHITE = (243, 243, 250)
MUTED = (150, 152, 172)
ACCENT = (138, 118, 255)
GREEN = (78, 201, 140)
COVER_A = (58, 46, 104)
COVER_B = (120, 100, 210)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"

FONTS = Path("/usr/share/fonts/truetype")
CANDIDATES = {
    "bold": [
        FONTS / "google-fonts/Poppins-Bold.ttf",
        FONTS / "dejavu/DejaVuSans-Bold.ttf",
    ],
    "semibold": [
        FONTS / "google-fonts/Poppins-SemiBold.ttf",
        FONTS / "dejavu/DejaVuSans-Bold.ttf",
    ],
    "regular": [
        FONTS / "google-fonts/Poppins-Regular.ttf",
        FONTS / "dejavu/DejaVuSans.ttf",
    ],
}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in CANDIDATES[kind]:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def cover(size: int) -> Image.Image:
    """A stand-in for a VNDB cover: a soft vertical gradient with the icon motif."""
    art = Image.new("RGB", (size, size), COVER_A)
    draw = ImageDraw.Draw(art)
    for y in range(size):
        blend = y / size
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(int(a + (b - a) * blend) for a, b in zip(COVER_A, COVER_B)),
        )
    pad = size // 6
    draw.rounded_rectangle(
        (pad, pad + size // 8, size - pad, size - pad), radius=size // 14, fill=(246, 244, 255)
    )
    bar = size // 18
    for index, width in enumerate((0.52, 0.34)):
        top = pad + size // 8 + size // 5 + index * bar * 2
        draw.rounded_rectangle(
            (pad + bar, top, pad + bar + int(size * width), top + bar),
            radius=bar // 2,
            fill=(110, 104, 150),
        )
    return art


def build() -> Image.Image:
    image = Image.new("RGB", (W, H), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # A soft accent glow behind the card, so the flat background has some depth
    glow = Image.new("RGB", (W, H), BACKGROUND)
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((660, -200, 1560, 720), fill=(36, 31, 68))
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    image = Image.blend(image, glow, 0.6)
    draw = ImageDraw.Draw(image)

    # -- left: what it is ------------------------------------------------
    draw.text((80, 152), "VNPresence", font=font("bold", 68), fill=WHITE)
    draw.text(
        (84, 244),
        "Discord Rich Presence for visual novels",
        font=font("semibold", 25),
        fill=ACCENT,
    )
    for index, line in enumerate(
        (
            "Cover art, title and reading time.",
            "Detects the games you start yourself.",
            "One .exe, no setup. MIT licensed.",
        )
    ):
        draw.text((84, 306 + index * 40), line, font=font("regular", 22), fill=MUTED)

    draw.text(
        (84, 500),
        "github.com/BasedYuki/vnpresence",
        font=font("regular", 21),
        fill=(102, 104, 128),
    )

    # -- right: the activity card ----------------------------------------
    card = (700, 150, 1192, 490)
    draw.rounded_rectangle(card, radius=26, fill=PANEL, outline=PANEL_EDGE, width=2)

    draw.text((736, 186), "PLAYING A GAME", font=font("semibold", 19), fill=MUTED)

    art = cover(148)
    image.paste(art, (736, 228))
    draw.rounded_rectangle((736, 228, 884, 376), radius=14, outline=PANEL_EDGE, width=2)

    draw.text((908, 232), "a Visual Novel", font=font("semibold", 25), fill=WHITE)
    draw.text((908, 272), "Steins;Gate", font=font("regular", 24), fill=(214, 214, 230))
    draw.text((908, 308), "Reading", font=font("regular", 24), fill=MUTED)
    draw.ellipse((908, 350, 926, 368), fill=GREEN)
    draw.text((938, 346), "01:24:07 elapsed", font=font("regular", 22), fill=MUTED)

    button = (736, 406, 1156, 458)
    draw.rounded_rectangle(button, radius=12, fill=(60, 63, 82))
    draw.text((870, 420), "View on VNDB", font=font("semibold", 22), fill=(226, 226, 240))

    return image


def main() -> None:
    OUT.mkdir(exist_ok=True)
    path = OUT / "social-preview.png"
    build().save(path)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
