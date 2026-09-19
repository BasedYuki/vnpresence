"""Draw the fallback VNPresence artwork.

Run with:  python tools/make_icon.py
Writes assets/icon-source.png, and nothing else.

Three files in assets/ are the project's real identity and this script must
never overwrite any of them:

* ``icon.ico``     - the Windows executable's icon
* ``icon-256.png`` - the small icon Discord shows in the corner of the cover
* ``icon.png``     - the large artwork

They are maintained by hand. Regenerating them here would quietly replace what
the project actually ships, which has already happened once. So the generated
art goes to its own names, and the script refuses to write over a file it did
not create. Pass ``--force`` only if you truly mean to reset the artwork.

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


#: The project's identity. This script never writes to these names.
PROTECTED = ("icon.ico", "icon-256.png", "icon.png")


def _guard(name: str, force: bool) -> bool:
    """False when writing this name would clobber the project's identity."""
    return force or name not in PROTECTED


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    force = "--force" in argv
    OUT.mkdir(exist_ok=True)
    icon = build()

    written, skipped = [], []
    targets = [("icon-source.png", icon)]
    if force:
        # An explicit reset: the generated art becomes the project's art again.
        targets = [
            ("icon.png", icon),
            ("icon-256.png", icon.resize((256, 256), Image.LANCZOS)),
        ]

    for name, image in targets:
        if not _guard(name, force):
            skipped.append(name)
            continue
        image.save(OUT / name)
        written.append(name)

    ico_name = "icon.ico" if force else "icon-generated.ico"
    if "--ico" in argv or force:
        if _guard(ico_name, force):
            icon.save(
                OUT / ico_name,
                sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
            )
            written.append(ico_name)
        else:
            skipped.append(ico_name)

    print(f"wrote {', '.join(written)} in {OUT}")
    if not force:
        print(f"left alone: {', '.join(PROTECTED)} (the project's own icons)")
        print("use --force to overwrite them, or --ico for a generated icon-generated.ico")
    if skipped:
        print(f"skipped: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
