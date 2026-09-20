"""What the session adds on top of a plugin: the note and the reading total.

These are the rules that are easy to get wrong and impossible to notice from a
screenshot: the total has to count *every* session, not tonight's; the note has
to be re-read while the game runs, not once at launch; and a plugin that knows
better must not be overruled.
"""

from __future__ import annotations

import time

import pytest

from vnpresence import notes
from vnpresence.config import AppConfig
from vnpresence.models import GameMetadata, GameProfile, PresenceState
from vnpresence.playtime import Playtime
from vnpresence.session import GameSession


def make_session(tmp_path, **profile_kwargs):
    profile = GameProfile(id="sg", title="Steins;Gate", path="/x.exe", **profile_kwargs)
    session = GameSession(
        profile,
        AppConfig(client_id="1"),
        playtime=Playtime(tmp_path / "playtime.yaml"),
        presence=object(),  # never touched: these tests do not run the loop
    )
    session.metadata = GameMetadata(title="Steins;Gate")
    session.start_time = time.time() - 60  # a minute in
    return session


def test_the_total_counts_previous_sessions_not_just_tonight(tmp_path):
    session = make_session(tmp_path)
    session.previous_seconds = 5 * 3600  # five hours on earlier evenings
    session.read_seconds = 60  # and a minute tonight
    assert session.live_state(PresenceState()).playtime_seconds == 5 * 3600 + 60


def test_a_plugin_that_knows_better_is_not_overruled(tmp_path):
    session = make_session(tmp_path)
    session.previous_seconds = 5 * 3600
    state = session.live_state(PresenceState(playtime_seconds=42.0))
    assert state.playtime_seconds == 42.0


def test_the_total_can_be_switched_off_globally(tmp_path):
    session = make_session(tmp_path)
    session.previous_seconds = 3600
    session.config.show_playtime = False
    assert session.live_state(PresenceState()).playtime_seconds is None


def test_one_game_can_opt_out_on_its_own(tmp_path):
    session = make_session(tmp_path, show_playtime=False)
    session.previous_seconds = 3600
    assert session.live_state(PresenceState()).playtime_seconds is None


def test_the_note_is_read_again_on_every_update(tmp_path):
    session = make_session(tmp_path)
    assert session.live_state(PresenceState()).status_text is None

    notes.write_note("sg", "Ayamine route")
    assert session.live_state(PresenceState()).status_text == "Ayamine route"

    notes.write_note("sg", "Chapter 4")
    assert session.live_state(PresenceState()).status_text == "Chapter 4"

    notes.clear_note("sg")
    assert session.live_state(PresenceState()).status_text is None


def test_a_typed_note_outranks_a_plugin_guess(tmp_path):
    session = make_session(tmp_path)
    notes.write_note("sg", "Ayamine route")
    state = session.live_state(PresenceState(status_text="Chapter 1"))
    assert state.status_text == "Ayamine route"


def test_the_plugin_state_object_is_left_alone(tmp_path):
    """It belongs to the plugin and may well be reused on the next poll."""
    session = make_session(tmp_path)
    session.previous_seconds = 3600
    notes.write_note("sg", "Route A")
    original = PresenceState(status_text="Chapter 1")
    session.live_state(original)
    assert original.status_text == "Chapter 1"
    assert original.playtime_seconds is None


# -- only while the game is the window in front ---------------------------
def test_time_only_counts_while_the_game_is_in_front(tmp_path, monkeypatch):
    """Alt-tab to a browser and the reading total stops, like a time tracker."""
    session = make_session(tmp_path)
    session._tracked_pid = 4242

    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 4242)
    session._tick(2.0)
    session._tick(2.0)
    assert session.read_seconds == 4.0

    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 999)  # a browser
    session._tick(2.0)
    session._tick(2.0)
    assert session.read_seconds == 4.0  # unchanged: nobody was reading

    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 4242)
    session._tick(2.0)
    assert session.read_seconds == 6.0


def test_the_discord_timer_keeps_running_even_so(tmp_path, monkeypatch):
    """Every game on Discord counts wall clock; a timer that jumped back looks broken."""
    session = make_session(tmp_path)
    session._tracked_pid = 4242
    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 999)
    assert session.elapsed() >= 60  # start_time was a minute ago
    assert session.read_seconds == 0.0


def test_an_unknown_foreground_counts_as_reading(tmp_path, monkeypatch):
    """On Linux there is no way to ask - recording nothing would be worse."""
    session = make_session(tmp_path)
    session._tracked_pid = 4242
    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: None)
    session._tick(5.0)
    assert session.read_seconds == 5.0


def test_the_whole_thing_can_be_switched_off(tmp_path, monkeypatch):
    session = make_session(tmp_path)
    session._tracked_pid = 4242
    session.config.focused_time_only = False
    monkeypatch.setattr(
        "vnpresence.session.foreground_pid", lambda: pytest.fail("should not be asked")
    )
    session._tick(3.0)
    assert session.read_seconds == 3.0


def test_nothing_is_counted_before_a_game_is_tracked(tmp_path):
    session = make_session(tmp_path)
    assert session.is_focused() is True  # no pid yet: nothing to compare against


# -- the history ----------------------------------------------------------
def test_time_is_written_as_the_session_goes(tmp_path):
    session = make_session(tmp_path)
    session.read_seconds = 60.0
    session._record_playtime()
    assert session.playtime.total("sg") == 60.0


def test_a_mid_session_save_is_not_counted_twice(tmp_path):
    session = make_session(tmp_path)
    session.read_seconds = 60.0
    session._record_playtime()
    session._record_playtime()
    session.read_seconds = 90.0
    session._record_playtime(final=True)
    assert session.playtime.total("sg") == 90.0
    assert session.playtime.get("sg").sessions == 1


def test_a_broken_history_never_ends_the_session(tmp_path):
    session = make_session(tmp_path)

    def explode(*args, **kwargs):
        raise OSError("disk full")

    session.playtime.add = explode
    session._record_playtime(final=True)  # must not raise


# -- the chapter, read off the game's own title bar -------------------------
def test_a_chapter_in_the_title_becomes_the_status_line(tmp_path, monkeypatch):
    session = make_session(tmp_path, chapter_pattern=r"Chapter \d+")
    session._tracked_pid = 4242
    monkeypatch.setattr(
        "vnpresence.session.titles_for", lambda pid: ["Some VN - Chapter 3"]
    )
    assert session.live_state(PresenceState()).status_text == "Chapter 3"


def test_a_capture_group_is_what_gets_shown(tmp_path, monkeypatch):
    session = make_session(tmp_path, chapter_pattern=r"Route: (.+?)\]")
    session._tracked_pid = 4242
    monkeypatch.setattr(
        "vnpresence.session.titles_for", lambda pid: ["Some VN [Route: Ayamine]"]
    )
    assert session.live_state(PresenceState()).status_text == "Ayamine"


def test_a_title_that_says_nothing_leaves_the_line_alone(tmp_path, monkeypatch):
    session = make_session(tmp_path, chapter_pattern=r"Chapter \d+")
    session._tracked_pid = 4242
    monkeypatch.setattr("vnpresence.session.titles_for", lambda pid: ["Some VN"])
    assert session.live_state(PresenceState()).status_text is None


def test_a_typed_note_still_outranks_the_title_bar(tmp_path, monkeypatch):
    """You know where you are better than a window title does."""
    session = make_session(tmp_path, chapter_pattern=r"Chapter \d+")
    session._tracked_pid = 4242
    monkeypatch.setattr(
        "vnpresence.session.titles_for", lambda pid: ["Some VN - Chapter 3"]
    )
    notes.write_note("sg", "Ayamine route, second loop")
    assert session.live_state(PresenceState()).status_text == "Ayamine route, second loop"


def test_the_title_bar_outranks_a_plugin_guess(tmp_path, monkeypatch):
    session = make_session(tmp_path, chapter_pattern=r"Chapter \d+")
    session._tracked_pid = 4242
    monkeypatch.setattr(
        "vnpresence.session.titles_for", lambda pid: ["Some VN - Chapter 3"]
    )
    state = PresenceState(status_text="Chapter 1")
    assert session.live_state(state).status_text == "Chapter 3"


def test_a_broken_pattern_is_dropped_rather_than_crashing(tmp_path, monkeypatch):
    """A typo in a YAML file must not take the session down every update."""
    session = make_session(tmp_path, chapter_pattern=r"Chapter (\d+")  # unbalanced
    session._tracked_pid = 4242
    monkeypatch.setattr(
        "vnpresence.session.titles_for", lambda pid: ["Some VN - Chapter 3"]
    )
    assert session.chapter_from_title() is None
    assert session.profile.chapter_pattern is None  # and not tried again


def test_no_pattern_means_no_window_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "vnpresence.session.titles_for", lambda pid: pytest.fail("nothing to look for")
    )
    session = make_session(tmp_path)
    session._tracked_pid = 4242
    assert session.chapter_from_title() is None


# -- pausing when the reader looks away ------------------------------------
def test_focus_is_three_answers_not_two(tmp_path, monkeypatch):
    """"Cannot tell" has to be its own answer, or Linux would pause forever."""
    session = make_session(tmp_path)
    session._tracked_pid = 4242

    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: None)
    assert session.look_at_focus() is None  # not Windows, or the call failed
    assert session.is_focused() is True  # ...so the clock keeps running

    session.config.focused_time_only = False
    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 999)
    assert session.look_at_focus() is None  # the feature is switched off


def test_a_window_owned_by_a_child_process_still_counts(tmp_path, monkeypatch):
    """Plenty of games put their window in a process they started themselves."""
    session = make_session(tmp_path)
    session._tracked_pid = 4242

    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 5555)
    monkeypatch.setattr(
        "vnpresence.session.belongs_to",
        lambda pid, owner, **kw: (pid, owner) == (5555, 4242),
    )
    assert session.look_at_focus() is True
    session._tick(2.0)
    assert session.read_seconds == 2.0


def test_the_presence_says_paused_and_drops_the_timer(tmp_path, monkeypatch):
    session = make_session(tmp_path)
    session._tracked_pid = 4242
    session._timer_start = session.start_time
    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 999)

    session._tick(2.0)
    payload = session.build_payload(PresenceState())
    assert payload["details"] == "Paused"
    assert "start" not in payload  # no clock ticking next to the word "Paused"

    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 4242)
    session._tick(2.0)
    payload = session.build_payload(PresenceState())
    assert payload["details"] == "Reading"
    assert "start" in payload


def test_a_note_survives_the_pause_and_is_marked(tmp_path, monkeypatch):
    session = make_session(tmp_path)
    session._tracked_pid = 4242
    notes.write_note("sg", "Chapter 3 - Ayamine route")
    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 999)

    session._tick(2.0)
    payload = session.build_payload(PresenceState())
    assert payload["details"] == "Chapter 3 - Ayamine route (paused)"


def test_the_timer_is_re_anchored_to_the_reading_time(tmp_path):
    """After a pause the timer shows time read, not time the game was open."""
    session = make_session(tmp_path)
    session.start_time = time.time() - 3600  # open for an hour
    session._timer_start = session.start_time
    session.read_seconds = 600  # of which ten minutes were actually read

    session._resume_timer()
    shown = time.time() - session._timer_start
    assert 599 <= shown <= 601
