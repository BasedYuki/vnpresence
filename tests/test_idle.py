"""Noticing that the novel is open and nobody is there.

The focused window answers "is the reader in the game?" but not "is the reader
in the room?" - and a visual novel left open overnight keeps the focus the
whole time. These are the rules for the second question.
"""

from __future__ import annotations

import time

import pytest

from vnpresence import idle
from vnpresence.config import AppConfig
from vnpresence.formatter import IDLE, PAUSED
from vnpresence.models import GameMetadata, GameProfile, PresenceState
from vnpresence.playtime import Playtime
from vnpresence.session import GameSession


@pytest.fixture
def session(tmp_path):
    game = GameProfile(id="sg", title="Steins;Gate", path="/x.exe")
    made = GameSession(
        game,
        AppConfig(client_id="1", idle_after=600),
        playtime=Playtime(tmp_path / "playtime.yaml"),
        presence=object(),
    )
    made.metadata = GameMetadata(title="Steins;Gate")
    made.start_time = time.time()
    made._timer_start = made.start_time
    made._tracked_pid = 4242
    return made


def quiet_for(monkeypatch, seconds):
    monkeypatch.setattr("vnpresence.session.idle_seconds", lambda: seconds)


def in_the_game(monkeypatch):
    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 4242)


# -- reading the clock ------------------------------------------------------
def test_off_windows_it_says_nothing_rather_than_guessing():
    if idle.supported():  # pragma: no cover - depends where the tests run
        pytest.skip("this is the non-Windows behaviour")
    assert idle.idle_seconds() is None


def test_the_ordinary_case():
    assert idle.since(1_000_000, 1_012_000) == pytest.approx(12.0)
    assert idle.since(5_000, 5_000) == 0.0


def test_the_tick_counter_wrapping_does_not_invent_a_49_day_idle():
    """GetTickCount wraps every 49.7 days; the subtraction has to wrap with it."""
    last, now = idle.TICK_WIDTH - 1000, 4000  # input just before the wrap
    assert idle.since(last, now) == pytest.approx(5.0, abs=0.01)


def test_a_last_input_that_is_ahead_of_now_reads_as_just_now():
    """Microsoft: the last-input tick "is not guaranteed to be incremental".

    A few milliseconds of that, run through wrapping arithmetic, comes out as
    49.7 days - and a reader who just clicked would be reported as having left
    the building. It has to come out as zero instead.
    """
    assert idle.since(1_000_050, 1_000_000) == 0.0  # 50ms ahead
    assert idle.since(2_000, 1_000) == 0.0
    assert idle.since(0, idle.TICK_WIDTH) == 0.0  # the worst case, 1ms ahead


def test_a_genuinely_long_idle_still_reads_long():
    """The guard must not swallow a real afternoon away from the desk."""
    assert idle.since(0, 6 * 3600 * 1000) == pytest.approx(6 * 3600)
    assert idle.since(0, 20 * 24 * 3600 * 1000) > 0  # twenty days, still real


# -- what the session does with it -----------------------------------------
def test_a_novel_left_open_stops_counting(session, monkeypatch):
    in_the_game(monkeypatch)
    quiet_for(monkeypatch, 30)
    assert session.observe() is None  # reading: a click half a minute ago

    quiet_for(monkeypatch, 15 * 60)
    assert session.observe() == IDLE


def test_idle_is_only_asked_when_the_game_is_the_window_in_use(session, monkeypatch):
    """Another window is "Paused" - saying "Idle" would name the wrong reason."""
    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: 999)
    quiet_for(monkeypatch, 15 * 60)
    assert session.observe() == PAUSED


def test_idle_can_be_switched_off(session, monkeypatch):
    in_the_game(monkeypatch)
    quiet_for(monkeypatch, 99 * 60)
    session.config.idle_after = 0
    assert session.observe() is None


def test_the_minutes_before_it_noticed_are_given_back(session, monkeypatch):
    """Idle is always noticed in arrears - those minutes were already counted."""
    in_the_game(monkeypatch)
    quiet_for(monkeypatch, 10)
    for _ in range(60):  # an hour of reading, a minute at a time
        session._tick(60.0)
    assert session.read_seconds == 3600

    quiet_for(monkeypatch, 600)  # and now: ten minutes of nothing
    session._tick(60.0)
    assert session._stopped == IDLE
    assert session.read_seconds == 3000  # the ten minutes handed back


def test_the_handback_happens_once_not_every_tick(session, monkeypatch):
    in_the_game(monkeypatch)
    quiet_for(monkeypatch, 10)
    session._tick(60.0)

    quiet_for(monkeypatch, 600)
    session._tick(60.0)
    after_first = session.read_seconds
    session._tick(60.0)
    session._tick(60.0)
    assert session.read_seconds == after_first


def test_the_total_never_goes_below_zero(session, monkeypatch):
    in_the_game(monkeypatch)
    quiet_for(monkeypatch, 4 * 3600)  # idle far longer than the session is old
    session._tick(60.0)
    assert session.read_seconds == 0.0


def test_the_history_gets_the_time_back_too(session, monkeypatch):
    """A rollback has to reach the file, or the evening is banked anyway."""
    in_the_game(monkeypatch)
    quiet_for(monkeypatch, 10)
    for _ in range(60):
        session._tick(60.0)
    session._record_playtime()
    assert session.playtime.total("sg") == 3600

    quiet_for(monkeypatch, 600)
    session._tick(60.0)
    session._record_playtime()
    assert session.playtime.total("sg") == 3000


def test_coming_back_starts_the_clock_again(session, monkeypatch):
    in_the_game(monkeypatch)
    quiet_for(monkeypatch, 15 * 60)
    session._tick(60.0)
    assert session._stopped == IDLE

    quiet_for(monkeypatch, 1)  # a click
    session._tick(60.0)
    assert session._stopped is None
    assert session.read_seconds == 60.0


def test_the_card_says_idle_and_loses_the_timer(session, monkeypatch):
    in_the_game(monkeypatch)
    quiet_for(monkeypatch, 15 * 60)
    session._tick(60.0)
    payload = session.build_payload(PresenceState())
    assert payload["details"] == "Idle"
    assert "start" not in payload


def test_a_sleeping_laptop_does_not_wipe_the_evening(session, monkeypatch):
    """Windows keeps the idle clock running while the machine is suspended."""
    in_the_game(monkeypatch)
    quiet_for(monkeypatch, 10)
    for _ in range(120):  # two hours genuinely read
        session._tick(60.0)
    assert session.read_seconds == 7200

    quiet_for(monkeypatch, 6 * 3600)  # lid shut for six hours, loop frozen
    session._tick(60.0)
    # Only the threshold (plus the poll that noticed) can have been counted.
    handed_back = session.config.idle_after + session.config.poll_interval
    assert session.read_seconds == 7200 - handed_back
