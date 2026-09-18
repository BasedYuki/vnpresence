"""Draw the VNPresence icon.

Run with:  python tools/make_icon.py
Writes assets/icon.png (1024x1024) and assets/icon-256.png.

The motif is a visual novel's dialogue box: a rounded frame, two lines of
"text", and the little advance marker in the corner. It has to stay readable at
32 pixels, so everything is big, high contrast, and there is no fine detail.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
BACKGROUND = (28, 29, 41)  # deep indigo, sits well on Discord's dark UI
BOX = (245, 243, 255)
BOX_SHADE = (196, 190, 230)
ACCENT = (138, 118, 255)  # the marker
TEXT = (96, 92, 130)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"


def rounded(draw: ImageDraw.ImageDraw, box, radius, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def build() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Background tile
    rounded(draw, (0, 0, SIZE, SIZE), radius=224, fill=BACKGROUND)

    # A second, offset page behind the dialogue box - hints at "novel"
    rounded(draw, (196, 232, 872, 700), radius=48, fill=BOX_SHADE)

    # The dialogue box itself
    rounded(draw, (152, 296, 828, 764), radius=56, fill=BOX)

    # Two lines of text, second one shorter, like a real text box mid-sentence
    for top, right in ((404, 700), (512, 596)):
        rounded(draw, (228, top, right, top + 56), radius=28, fill=TEXT)

    # The advance marker in the bottom right corner
    draw.polygon([(700, 640), (772, 640), (736, 700)], fill=ACCENT)

    return image


def main() -> None:
    OUT.mkdir(exist_ok=True)
    icon = build()
    icon.save(OUT / "icon.png")
    icon.resize((256, 256), Image.LANCZOS).save(OUT / "icon-256.png")
    # .ico for the Windows executable itself (PyInstaller --icon)
    icon.save(
        OUT / "icon.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote icon.png, icon-256.png and icon.ico in {OUT}")


if __name__ == "__main__":
    main()
