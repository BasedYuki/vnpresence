"""The game page's second shape: heatmap, journal, session history, About,
the cover's colours and the banner - plus the themes that replaced 0.17's."""

from __future__ import annotations

import datetime as dt
import time

from PIL import Image, ImageDraw

from vnpresence import banner, chart, cover_colors, journal, session_log, stats, theme
from vnpresence.config import AppConfig
from vnpresence.formatter import DefaultFormatter
from vnpresence.models import GameProfile, PresenceState, PrivacyMode
from vnpresence.playtime import Entry
from vnpresence.vndb import about_text, clean_description, parse_vn, visible_tags

TODAY = dt.date(2026, 10, 22)  # a Thursday


def entry(*days_back, seconds=1800):
    return Entry(seconds=1, days={(TODAY - dt.timedelta(days=b)).isoformat(): seconds
                                  for b in days_back})


# -- heatmap and streaks ----------------------------------------------------
def test_the_heatmap_is_weeks_of_monday_to_sunday_with_no_future():
    columns = stats.heatmap(entry(0, 1), weeks=4, today=TODAY)
    assert len(columns) == 4 and all(len(c) == 7 for c in columns)
    assert all(day.weekday() == i for column in columns for i, (day, _) in enumerate(column))
    last = columns[-1]
    assert last[3] == (TODAY, 1800.0)  # Thursday, today
    assert last[4][1] is None and last[6][1] is None  # Friday on: not yet


def test_shades_go_from_a_taste_to_a_long_evening():
    assert [stats.level(s) for s in (0, None, 60, 1800, 3600, 9000)] == [0, 0, 1, 2, 3, 4]


def test_a_streak_survives_until_today_is_over():
    current, longest = stats.streaks(entry(1, 2, 3, 10, 11), TODAY)
    assert current == 3  # yesterday back: today is not played *yet*
    assert longest == 3
    assert stats.streaks(entry(0, 1, 2, 3), TODAY) == (4, 4)
    assert stats.streaks(entry(5), TODAY) == (0, 1)
    assert stats.streaks(None, TODAY) == (0, 0)


def test_the_best_day_is_the_longest_one():
    e = Entry(days={"2026-10-01": 600, "2026-10-02": 9000})
    assert stats.best_day(e) == (dt.date(2026, 10, 2), 9000.0)
    assert stats.best_day(Entry()) is None


def test_heatmap_squares_stay_inside_the_canvas():
    columns = stats.heatmap(entry(0), weeks=26, today=TODAY)
    cells, months, height = chart.heat_layout(columns, 560)
    assert all(c.x1 <= 560 for c in cells)
    assert months and height > 0
    assert len(cells) == 26 * 7 - 3  # Friday to Sunday of this week are not drawn


# -- the journal --------------------------------------------------------------
def test_routes_are_added_ticked_moved_and_removed():
    journal.add_route("g", "  Fiona  ")
    journal.add_route("g", "Eris")
    journal.add_route("g", "fiona")  # the same route twice is once
    assert [r.name for r in journal.load("g").routes] == ["Fiona", "Eris"]
    journal.set_done("g", 1, True)
    assert journal.load("g").progress() == (1, 2)
    journal.move_route("g", 1, -1)
    assert [r.name for r in journal.load("g").routes] == ["Eris", "Fiona"]
    journal.remove_route("g", 0)
    assert [r.name for r in journal.load("g").routes] == ["Fiona"]


def test_notes_are_kept_and_a_broken_file_is_not_fatal():
    journal.set_notes("g", "save before the bridge")
    assert journal.load("g").notes == "save before the bridge"
    journal.journal_path("g").write_text("{not json")
    assert journal.load("g").notes == ""


def test_routes_show_on_discord_but_never_for_a_private_game():
    journal.add_route("sg", "Kurisu")
    journal.add_route("sg", "Mayuri")
    journal.set_done("sg", 0, True)
    config = AppConfig(client_id="1")
    state = PresenceState(playtime_seconds=7200)
    open_ = DefaultFormatter().format(GameProfile(id="sg", title="S;G"), None, state,
                                      {"config": config, "start": 1})
    assert "Routes 1/2" in open_["state"]
    private = DefaultFormatter().format(
        GameProfile(id="sg", title="S;G", privacy=PrivacyMode.PRIVATE), None, state,
        {"config": config, "start": 1})
    assert "Routes" not in str(private)


def test_no_route_list_means_nothing_extra_on_discord():
    assert journal.routes_line("nothing-here") is None


# -- session history -----------------------------------------------------------
def test_a_session_is_kept_with_its_counted_time():
    start = time.mktime((2026, 10, 21, 21, 0, 0, 0, 0, -1))
    assert session_log.record("g", start, start + 3 * 3600, 2 * 3600)
    (only,) = session_log.load("g")
    assert only.counted == 7200 and only.wall == 3 * 3600
    day, span, counted = session_log.describe(only, dt.datetime(2026, 10, 22, 9))
    assert (day, span, counted) == ("Yesterday", "21:00 – 00:00 (+1)", "2h 00m")


def test_a_game_opened_by_mistake_is_not_a_session():
    assert not session_log.record("g", 100, 110, 10)
    assert session_log.load("g") == []


def test_newest_sessions_come_first():
    for hour in (10, 12, 14):
        start = time.mktime((2026, 10, 20, hour, 0, 0, 0, 0, -1))
        session_log.record("g", start, start + 3600, 3000)
    assert [s.start.hour for s in session_log.newest_first("g", 2)] == [14, 12]


# -- About: VNDB, spoilers held back ----------------------------------------------
TAGS = [{"name": "Fantasy", "category": "cont", "rating": 2.8, "spoiler": 0},
        {"name": "Big Twist", "category": "cont", "rating": 2.0, "spoiler": 2},
        {"name": "Sex", "category": "ero", "rating": 2.5, "spoiler": 0},
        {"name": "Barely", "category": "cont", "rating": 0.4, "spoiler": 0}]


def test_spoiler_tags_wait_until_asked_for():
    assert visible_tags(TAGS) == (["Fantasy", "Sex"], 1)
    assert visible_tags(TAGS, spoilers=True)[0] == ["Fantasy", "Big Twist", "Sex"]


def test_a_private_game_never_lists_18_plus_tags():
    assert "Sex" not in visible_tags(TAGS, adult=False)[0]


def test_spoiler_passages_are_held_back_in_the_description():
    raw = "Kind [b]girl[/b].\n\n[spoiler]She dies.[/spoiler] See [url=/c1]her[/url]."
    assert about_text(raw) == "Kind girl.\n\n[spoiler hidden] See her."
    assert "She dies." in about_text(raw, spoilers=True)


def test_the_discord_description_never_carries_a_spoiler():
    """Before 0.18 the markers were stripped and the spoiler itself kept."""
    assert "dies" not in clean_description("Kind girl. [spoiler]She dies.[/spoiler]")


def test_developers_and_tags_are_read_from_vndb():
    meta = parse_vn({"id": "v1", "title": "x", "developers": [{"name": "August"}],
                     "tags": [{"name": "A", "category": "cont", "rating": 1.5, "spoiler": 0}],
                     "description": "Hello"})
    assert meta.developers == ["August"] and meta.tags[0]["name"] == "A"
    assert meta.about == "Hello"


# -- the cover's colours ---------------------------------------------------------
def cover(tmp_path, colour="#d4a017"):
    path = tmp_path / "cover.png"
    image = Image.new("RGB", (120, 170), "#202020")
    ImageDraw.Draw(image).rectangle((10, 10, 110, 160), fill=colour)
    image.save(path)
    return path


def test_the_page_takes_its_accent_from_the_cover(tmp_path):
    base = theme.get("midnight")
    page = cover_colors.page_palette(base, cover(tmp_path))
    assert page.accent != base.accent
    red, green, blue = theme._hex(page.accent)
    assert red > blue  # still the cover's gold, not the theme's purple


def test_any_cover_colour_ends_up_readable_on_every_theme(tmp_path):
    for colour in ("#d4a017", "#2040ff", "#ff2080", "#30a030", "#f4f0a0", "#5a1010"):
        for base in theme.PALETTES.values():
            accent, ink = cover_colors.fit_accent(colour, base)
            assert cover_colors.contrast(ink, accent) >= 4.5, (colour, base.name)


def test_a_grey_cover_keeps_the_theme(tmp_path):
    path = tmp_path / "grey.png"
    Image.new("RGB", (60, 80), "#808080").save(path)
    base = theme.get("rainy-night")
    assert cover_colors.page_palette(base, path) == base
    assert cover_colors.page_palette(base, None) == base


def test_the_banner_is_exactly_the_size_asked_for(tmp_path):
    palette = theme.get("ink-paper")
    assert banner.render(cover(tmp_path), (900, 230), palette).size == (900, 230)
    assert banner.render(None, (900, 230), palette).size == (900, 230)
    # Private: the cover is not used at all - the gradient is the same as none.
    hidden = banner.render(cover(tmp_path), (300, 100), palette, hide=True)
    assert hidden.tobytes() == banner.render(None, (300, 100), palette).tobytes()


# -- themes ---------------------------------------------------------------------
def test_the_new_themes_are_all_there():
    for name in ("ink-paper", "matcha", "rainy-night", "summer-dusk", "neon", "crimson-moon"):
        assert theme.get(name).name == name
    assert len(theme.PALETTES) == 9
