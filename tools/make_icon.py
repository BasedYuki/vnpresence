"""Draw the fallback VNPresence artwork.

Run with:  python tools/make_icon.py
Writes assets/icon.png (1024x1024) and assets/icon-256.png.

It deliberately does **not** touch assets/icon.ico. That file is the Windows
executable's icon and is maintained by hand; regenerating it here would quietly
overwrite whatever the project is actually shipping. Pass --ico if you really
want a generated .ico, and it is written next to the others as
icon-generated.ico so nothing is clobbered.

The motif is a visual novel's dialogue box: a rounded frame, two lines of
"text", and the little advance marker in the corner. It has to stay readable at
32 pixels, so everything is big, high contrast, and there is no fine detail.
"""

from __future__ import annotations

import sys
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


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    OUT.mkdir(exist_ok=True)
    icon = build()
    icon.save(OUT / "icon.png")
    icon.resize((256, 256), Image.LANCZOS).save(OUT / "icon-256.png")
    written = ["icon.png", "icon-256.png"]

    if "--ico" in argv:
        # Never "icon.ico": that one belongs to whoever set the app's icon.
        icon.save(
            OUT / "icon-generated.ico",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        written.append("icon-generated.ico")

    print(f"wrote {', '.join(written)} in {OUT}")
    if "--ico" not in argv:
        print("assets/icon.ico was left alone (it is the app icon; use --ico for a generated one)")


if __name__ == "__main__":
    main()
