"""What the list, the grid and the details page say about a game."""

from __future__ import annotations

import datetime as dt

from vnpresence.config import AppConfig
from vnpresence.library_view import (
    card_for,
    details_lines,
    format_last_played,
    format_time_played,
    last_played_key,
    row_values,
)
from vnpresence.models import GameMetadata, GameProfile, PrivacyMode
from vnpresence.playtime import Entry

NOW = dt.datetime(2026, 10, 15, 21, 0, 0)


def stamp(days_ago: int, hour: int = 20) -> str:
    when = (NOW - dt.timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0)
    return when.strftime("%Y-%m-%dT%H:%M:%S")


# -- last played ----------------------------------------------------------
def test_last_played_reads_like_a_person_would_say_it():
    assert format_last_played(stamp(0), NOW) == "Today"
    assert format_last_played(stamp(1), NOW) == "Yesterday"
    assert format_last_played(stamp(3), NOW) == "3 days ago"
    assert format_last_played(stamp(6), NOW) == "6 days ago"


def test_past_a_week_it_is_a_date_not_arithmetic():
    assert format_last_played(stamp(7), NOW) == "2026-10-08"
    assert format_last_played(stamp(40), NOW) == "2026-09-05"


def test_yesterday_is_the_calendar_day_not_24_hours():
    """Played at 23:00 and looked at the next morning: that is yesterday."""
    late = dt.datetime(2026, 10, 14, 23, 30).strftime("%Y-%m-%dT%H:%M:%S")
    morning = dt.datetime(2026, 10, 15, 8, 0)
    assert format_last_played(late, morning) == "Yesterday"


def test_never_played_and_garbage_both_read_never():
    assert format_last_played("", NOW) == "Never"
    assert format_last_played(None, NOW) == "Never"
    assert format_last_played("not a date", NOW) == "Never"


def test_sorting_by_last_played_is_chronological_not_alphabetical():
    """"Yesterday" < "Today" alphabetically; the key must not care."""
    keys = [last_played_key(stamp(d)) for d in (0, 1, 3, 40)]
    assert keys == sorted(keys, reverse=True)
    assert last_played_key("") == 0.0  # never played sorts as the oldest


# -- time played ----------------------------------------------------------
def test_time_played_drops_the_word_the_column_already_says():
    assert format_time_played(12 * 3600 + 40 * 60) == "12h 40m"
    assert format_time_played(0) == "-"
    assert format_time_played(None) == "-"


def test_a_row_carries_all_six_columns():
    profile = GameProfile(id="sg", title="STEINS;GATE", vndb_id="v2002")
    entry = Entry(seconds=3600, sessions=4, last_played=stamp(1))
    assert row_values(profile, entry, NOW) == (
        "STEINS;GATE", "1h", "Yesterday", "4", "auto", "v2002")


# -- cards: the grid and the details page ---------------------------------
def meta(**kw):
    base = {"title": "Mahoutsukai no Yoru", "image_url": "https://t.vndb.org/cv/x.jpg",
            "length": "Long (30-50h)", "released": "2012-04-12", "rating": 8.6}
    base.update(kw)
    return GameMetadata(**base)


def test_a_card_uses_the_vndb_cover():
    profile = GameProfile(id="woh", title="Mahoutsukai no Yoru", privacy=PrivacyMode.FULL)
    card = card_for(profile, Entry(seconds=7200, sessions=2), meta(), AppConfig(), NOW)
    assert card.cover_url == "https://t.vndb.org/cv/x.jpg"
    assert card.hide_cover is False
    assert card.time_played == "2h"


def test_a_cover_the_reader_set_themselves_wins():
    profile = GameProfile(id="woh", title="W", image_url="https://example.org/mine.png")
    assert card_for(profile, None, meta(), AppConfig()).cover_url == "https://example.org/mine.png"


def test_a_private_game_shows_no_cover_in_the_grid():
    """The library ends up on screen while streaming; private means private there too."""
    for mode in (PrivacyMode.PRIVATE, PrivacyMode.OFF):
        profile = GameProfile(id="p", title="P", privacy=mode)
        assert card_for(profile, None, meta(), AppConfig()).hide_cover is True


def test_auto_privacy_hides_an_18_plus_cover():
    profile = GameProfile(id="p", title="P", privacy=PrivacyMode.AUTO)
    assert card_for(profile, None, meta(nsfw=True), AppConfig()).hide_cover is True
    assert card_for(profile, None, meta(nsfw=False), AppConfig()).hide_cover is False


def test_the_details_page_lists_what_is_known_and_skips_what_is_not():
    profile = GameProfile(id="woh", title="Mahoutsukai no Yoru")
    card = card_for(profile, Entry(seconds=41 * 3600, sessions=18, last_played=stamp(0)),
                    meta(alt_title="魔法使いの夜"), AppConfig(), NOW)
    lines = dict(details_lines(card))
    assert lines["Time played"] == "41h"
    assert lines["Sessions"] == "18"
    assert lines["Last played"] == "Today"
    assert lines["Original title"] == "魔法使いの夜"
    assert lines["VNDB rating"] == "8.6 / 10"

    bare = card_for(GameProfile(id="x", title="X"), None, None, AppConfig(), NOW)
    lines = dict(details_lines(bare))
    assert lines["Time played"] == "Not yet"
    assert lines["Last played"] == "Never"
    assert "Length" not in lines  # nothing invented when VNDB had nothing
