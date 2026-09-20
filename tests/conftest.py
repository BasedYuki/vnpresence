"""Shared test setup.

Everything that reads or writes user data goes through ``config_dir()``, which
honours ``VNPRESENCE_HOME``. Pointing it at a temporary folder for every test
means the suite can never touch a contributor's real library, play-time history
or notes - and each test starts from an empty one.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The suite runs offline. A test that reaches VNDB is a bug in the test."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a test tried to reach VNDB over the network - pass a fake session to "
            "VNDBClient, or stub the function that calls it"
        )

    # Patched at the HTTP call, not at the client: tests that hand VNDBClient a
    # fake session are exercising the real parsing code and must keep working.
    monkeypatch.setattr("vnpresence.vndb.requests.post", refuse)


@pytest.fixture(autouse=True)
def quiet_machine(request, monkeypatch):
    """No test may depend on where the mouse is or when it last moved.

    The session asks Windows two questions - which window has the focus, and
    how long since anybody touched anything - and on Linux both answer "no
    idea", so a test that leaves them alone passes there by accident. On
    Windows they answer for real: a build machine nobody has touched since it
    booted is, correctly, idle, and seven tests that had nothing to do with
    idling started failing on CI while passing everywhere else.

    So both are answered here, for every test, with the honest "cannot tell"
    the unit tests were written against. A test that cares patches them with
    what it wants to see.

    ``@pytest.mark.real_machine`` opts out - that is for the handful of tests
    whose entire purpose is to call the real thing.
    """
    if request.node.get_closest_marker("real_machine"):
        return
    monkeypatch.setattr("vnpresence.session.foreground_pid", lambda: None)
    monkeypatch.setattr("vnpresence.session.idle_seconds", lambda: None)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "vnpresence-home"
    home.mkdir()
    monkeypatch.setenv("VNPRESENCE_HOME", str(home))
    return home
