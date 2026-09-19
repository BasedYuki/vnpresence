"""Shared test setup.

Everything that reads or writes user data goes through ``config_dir()``, which
honours ``VNPRESENCE_HOME``. Pointing it at a temporary folder for every test
means the suite can never touch a contributor's real library, play-time history
or notes - and each test starts from an empty one.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "vnpresence-home"
    home.mkdir()
    monkeypatch.setenv("VNPRESENCE_HOME", str(home))
    return home
