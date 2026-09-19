"""The reading history, and how the total reads on the card.

The history must accumulate rather than overwrite - two sessions of an hour are
two hours, and a second VNPresence running in the background must not wipe the
first one's total. The formatting is deliberately coarse: the line is rewritten
every fifteen seconds and a ticking number would make it flicker.
"""

from __future__ import annotations

import pytest

from vnpresence import playtime
from vnpresence.playtime import Playtime


def test_time_accumulates_across_sessions():
    store = Playtime()
    store.add("clannad", 3600)
    store.add("clannad", 1800)
    assert store.total("clannad") == 3600 + 1800


def test_sessions_are_only_counted_when_one_ends():
    store = Playtime()
    store.add("x", 60)  # a mid-session save
    store.add("x", 60)
    assert store.get("x").sessions == 0
    store.add("x", 60, new_session=True)
    assert store.get("x").sessions == 1


def test_a_second_writer_adds_to_the_total_instead_of_replacing_it(tmp_path):
    # The GUI and a background watcher can both be running.
    shared = tmp_path / "playtime.yaml"
    first, second = Playtime(shared), Playtime(shared)
    first.add("x", 100)
    second.add("x", 50)
    assert Playtime(shared).total("x") == 150


def test_an_unknown_game_is_simply_zero():
    assert Playtime().total("nothing-here") == 0.0


def test_a_corrupt_history_does_not_take_the_session_down(tmp_path):
    broken = tmp_path / "playtime.yaml"
    broken.write_text("this: is: not: yaml:", encoding="utf-8")
    assert Playtime(broken).load() == {}
    Playtime(broken).add("x", 10)  # and it recovers on the next write
    assert Playtime(broken).total("x") == 10


def test_garbage_entries_are_ignored_rather_than_crashing(tmp_path):
    path = tmp_path / "playtime.yaml"
    path.write_text("x: {seconds: 'lots', sessions: null}\ny: 7\n", encoding="utf-8")
    history = Playtime(path).load()
    assert history["x"].seconds == 0.0
    assert history["y"].seconds == 0.0


# -- how it reads on the card --------------------------------------------
def test_hours_and_minutes():
    assert playtime.format_reading_time(12 * 3600 + 30 * 60) == "12h 30m read"


def test_a_whole_number_of_hours_drops_the_minutes():
    assert playtime.format_reading_time(3 * 3600) == "3h read"


def test_under_an_hour_is_just_minutes():
    assert playtime.format_reading_time(45 * 60) == "45m read"


def test_the_seconds_never_show_so_the_line_does_not_flicker():
    a = playtime.format_reading_time(3600 + 5)
    b = playtime.format_reading_time(3600 + 50)
    assert a == b == "1h read"


def test_the_first_minute_shows_nothing_rather_than_zero():
    assert playtime.format_reading_time(30) is None
    assert playtime.format_reading_time(0) is None
    assert playtime.format_reading_time(None) is None


# -- seeding a game that was read long before VNPresence -------------------
def test_set_replaces_the_total_instead_of_adding_to_it():
    store = Playtime()
    store.add("rewrite", 3600)
    store.set("rewrite", 50 * 3600)
    assert store.total("rewrite") == 50 * 3600


def test_time_carries_on_accumulating_after_a_set():
    store = Playtime()
    store.set("rewrite", 50 * 3600)
    store.add("rewrite", 1800, new_session=True)
    assert store.total("rewrite") == 50 * 3600 + 1800


def test_setting_a_game_that_was_never_played_just_works():
    Playtime().set("new-one", 7200)
    assert Playtime().total("new-one") == 7200


@pytest.mark.parametrize(
    ("typed", "hours"),
    [
        ("50h", 50),
        ("50", 50),          # a bare number is hours: nobody seeds 50 seconds
        ("50h 30m", 50.5),
        ("50h30m", 50.5),
        ("50:30", 50.5),
        ("90m", 1.5),
        ("2.5h", 2.5),
        ("  12H  ", 12),
    ],
)
def test_the_parser_takes_what_a_save_screen_shows(typed, hours):
    assert playtime.parse_duration(typed) == pytest.approx(hours * 3600)


def test_spelled_out_units_work_too():
    """People type what they mean; "50 hours" should not be an error."""
    assert playtime.parse_duration("50 hours") == 50 * 3600
    assert playtime.parse_duration("90 minutes") == 90 * 60


@pytest.mark.parametrize("typed", ["", "   ", "soon", "a while", "h", "??"])
def test_nonsense_is_refused_with_an_example(typed):
    with pytest.raises(ValueError):
        playtime.parse_duration(typed)
