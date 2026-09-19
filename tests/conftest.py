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
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "vnpresence-home"
    home.mkdir()
    monkeypatch.setenv("VNPRESENCE_HOME", str(home))
    return home
