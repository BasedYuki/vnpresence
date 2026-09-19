"""The palettes, and the rules every one of them has to keep.

A theme is only worth having if it is readable. These check the parts that can
be checked without a screen: that every palette is complete and well formed,
that text has enough contrast against what it sits on, and that a config file
naming a theme that no longer exists still opens the window.
"""

from __future__ import annotations

import pytest

from vnpresence import theme


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio between two colours, 1.0 (same) to 21.0 (black/white)."""

    def luminance(value: str) -> float:
        channels = []
        for part in theme._hex(value):
            c = part / 255
            channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
        red, green, blue = channels
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    a, b = sorted((luminance(first), luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


@pytest.mark.parametrize("palette", theme.PALETTES.values(), ids=theme.names())
def test_every_colour_is_a_hex_value(palette):
    for field in ("background", "surface", "text", "muted", "accent", "accent_text", "border"):
        value = getattr(palette, field)
        assert value.startswith("#") and len(value) == 7, f"{palette.name}.{field} = {value}"
        int(value[1:], 16)  # raises if it is not hex


@pytest.mark.parametrize("palette", theme.PALETTES.values(), ids=theme.names())
def test_body_text_is_comfortably_readable(palette):
    """4.5:1 is the readable-at-any-size threshold; these clear it easily."""
    assert contrast(palette.text, palette.surface) >= 4.5
    assert contrast(palette.text, palette.background) >= 4.5


@pytest.mark.parametrize("palette", theme.PALETTES.values(), ids=theme.names())
def test_secondary_text_is_still_legible(palette):
    """3:1 - dimmer on purpose, but never guesswork."""
    assert contrast(palette.muted, palette.background) >= 3.0


@pytest.mark.parametrize("palette", theme.PALETTES.values(), ids=theme.names())
def test_the_accent_button_can_be_read(palette):
    """Whatever sits on the accent colour has to survive it."""
    assert contrast(palette.accent_text, palette.accent) >= 4.5


@pytest.mark.parametrize("palette", theme.PALETTES.values(), ids=theme.names())
def test_a_selected_row_does_not_vanish(palette):
    assert contrast(palette.accent_text, palette.accent) >= 4.5
    assert contrast(palette.accent, palette.surface) >= 1.5  # visibly different


@pytest.mark.parametrize("palette", theme.PALETTES.values(), ids=theme.names())
def test_stripes_are_a_nudge_not_a_second_colour(palette):
    """Alternating rows should be felt, not seen as two different lists."""
    assert palette.stripe != palette.surface
    assert contrast(palette.stripe, palette.surface) < 1.5


def test_an_unknown_theme_falls_back_instead_of_failing():
    """A config naming a theme a later version dropped must still open."""
    assert theme.get("no-such-theme").name == theme.DEFAULT
    assert theme.get(None).name == theme.DEFAULT
    assert theme.get("").name == theme.DEFAULT


def test_names_are_matched_loosely():
    assert theme.get("  Kingdom-Hearts  ").name == "kingdom-hearts"


def test_every_palette_has_a_distinct_label():
    assert len(set(theme.labels())) == len(theme.PALETTES)


def test_a_label_round_trips_to_its_palette():
    for palette in theme.PALETTES.values():
        assert theme.by_label(palette.label).name == palette.name
    assert theme.by_label("something else").name == theme.DEFAULT


def test_the_kingdom_hearts_palette_is_blue_and_gold():
    """The one thing that makes it recognisable, and the only thing borrowed."""
    palette = theme.get("kingdom-hearts")
    red, green, blue = theme._hex(palette.background)
    assert blue > red and blue > green  # a deep blue night
    red, green, blue = theme._hex(palette.accent)
    assert red > 200 and green > 150 and blue < 120  # gold


def test_mixing_is_bounded():
    assert theme._mix("#000000", "#ffffff", 0.0) == "#000000"
    assert theme._mix("#000000", "#ffffff", 1.0) == "#ffffff"
    assert theme._mix("#000000", "#ffffff", 5.0) == "#ffffff"  # clamped
    assert theme._mix("#000000", "#ffffff", 0.5) == "#808080"
