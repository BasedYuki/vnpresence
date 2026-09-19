"""What the session adds on top of a plugin: the note and the reading total.

These are the rules that are easy to get wrong and impossible to notice from a
screenshot: the total has to count *every* session, not tonight's; the note has
to be re-read while the game runs, not once at launch; and a plugin that knows
better must not be overruled.
"""

from __future__ import annotations

import time

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
    total = session.live_state(PresenceState()).playtime_seconds
    assert 5 * 3600 + 55 <= total <= 5 * 3600 + 70  # plus tonight's minute


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


# -- the history ----------------------------------------------------------
def test_time_is_written_as_the_session_goes(tmp_path):
    session = make_session(tmp_path)
    session._record_playtime()
    recorded = session.playtime.total("sg")
    assert 55 <= recorded <= 70  # the minute since start_time


def test_a_mid_session_save_is_not_counted_twice(tmp_path):
    session = make_session(tmp_path)
    session._record_playtime()
    session._record_playtime()
    session._record_playtime(final=True)
    assert 55 <= session.playtime.total("sg") <= 70
    assert session.playtime.get("sg").sessions == 1


def test_a_broken_history_never_ends_the_session(tmp_path):
    session = make_session(tmp_path)

    def explode(*args, **kwargs):
        raise OSError("disk full")

    session.playtime.add = explode
    session._record_playtime(final=True)  # must not raise
