"""Reading history and the progress estimate built on it.

Two things matter here. The history must accumulate rather than overwrite -
two sessions of an hour are two hours, and a second VNPresence running in the
background must not wipe the first one's total. And the estimate must stay
honest: no percentage at all when the novel's length is unknown, and never
more than 100% for someone who reads slowly.
"""

from __future__ import annotations

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


# -- the estimate ---------------------------------------------------------
def test_progress_is_time_read_over_time_expected():
    assert playtime.fraction(seconds_read=3600, length_minutes=120) == 0.5


def test_no_length_means_no_guess():
    assert playtime.fraction(3600, None) is None
    assert playtime.fraction(3600, 0) is None


def test_nothing_read_yet_shows_nothing():
    assert playtime.fraction(0, 600) is None


def test_a_slow_reader_never_goes_past_one_hundred_percent():
    assert playtime.fraction(seconds_read=10**7, length_minutes=120) == 1.0
    assert playtime.percent(playtime.fraction(10**7, 120)) == "100%"


def test_the_first_minutes_show_one_percent_rather_than_zero():
    assert playtime.percent(playtime.fraction(60, 3600)) == "1%"


def test_percent_of_nothing_is_nothing():
    assert playtime.percent(None) is None


def test_votes_are_preferred_and_the_bucket_is_the_fallback():
    assert playtime.expected_minutes(2400, bucket=1) == 2400  # real votes win
    assert playtime.expected_minutes(None, bucket=4) == playtime.BUCKET_MINUTES[4]
    assert playtime.expected_minutes(None, bucket=None) is None
