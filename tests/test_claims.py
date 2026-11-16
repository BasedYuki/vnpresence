"""One game, one session - the fix for an evening counted twice.

Press Play with auto-detect on, and two processes used to track the same game:
the window's session and the background watcher's. Each wrote the evening into
the history, and the total came out doubled.
"""

from __future__ import annotations

import json
import os

import psutil
import pytest

from vnpresence import claims
from vnpresence.config import AppConfig
from vnpresence.launcher import LaunchError
from vnpresence.models import GameProfile
from vnpresence.session import GameSession
from vnpresence.watcher import LibraryWatcher


def held_by(pid: int, started: float | None = None) -> None:
    """Pretend another VNPresence process holds the game."""
    if started is None:
        started = psutil.Process(pid).create_time()
    path = claims.claim_path("g")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "started": started}))


def test_a_free_game_is_claimed_and_released():
    assert claims.claim("g")
    assert claims.holder("g") is None  # our own claim is not "someone else"
    assert claims.claim("g")  # claiming again from the same process is fine
    claims.release("g")
    assert not claims.claim_path("g").exists()


def test_a_game_another_live_session_holds_is_refused():
    other = os.getppid()
    held_by(other)
    assert claims.holder("g") == other
    assert not claims.claim("g")
    claims.release("g")  # never lets go of someone else's claim
    assert claims.claim_path("g").exists()


def test_a_claim_left_by_a_crash_is_ignored():
    held_by(os.getppid(), started=1.0)  # the pid lives on, but it is not that process
    assert claims.holder("g") is None
    assert claims.claim("g")
    held_by(999_999_999, started=1.0)  # and a pid that is gone altogether
    assert claims.claim("g")


def test_a_broken_claim_file_does_not_block_anything():
    claims.claim_path("g").parent.mkdir(parents=True, exist_ok=True)
    claims.claim_path("g").write_text("{not json")
    assert claims.claim("g")


def test_play_refuses_a_game_auto_detect_is_already_tracking():
    held_by(os.getppid())
    session = GameSession(GameProfile(id="g", title="Game"), AppConfig(client_id="1"),
                          presence=object())
    with pytest.raises(LaunchError, match="already being tracked"):
        session.run()


def test_the_watcher_leaves_a_claimed_game_alone():
    me = GameProfile(id="me", title="This test", path=psutil.Process().exe())
    watcher = LibraryWatcher(config=AppConfig(), library=object(), registry=object())
    assert watcher.find_match([me]) is not None  # it is running: this very process
    assert watcher.find_match([me], skip={"me"}) is None


def test_the_session_lets_go_of_its_game_when_it_ends(monkeypatch):
    session = GameSession(GameProfile(id="g", title="Game"), AppConfig(client_id="1"),
                          presence=object())
    seen = []

    def fake_run(*, attach, notify):
        seen.append(claims.claim_path("g").exists())
        raise RuntimeError("the game crashed")

    monkeypatch.setattr(session, "_run", fake_run)
    with pytest.raises(RuntimeError):
        session.run()
    assert seen == [True]  # held while it ran
    assert not claims.claim_path("g").exists()  # and given back after


def test_skip_is_by_id_not_by_name():
    me = GameProfile(id="me", title="This test", path=psutil.Process().exe())
    watcher = LibraryWatcher(config=AppConfig(), library=object(), registry=object())
    assert watcher.find_match([me], skip={"someone-else"}) is not None
