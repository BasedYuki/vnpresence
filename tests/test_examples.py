"""Every example profile must load - this is what CI checks on contributions."""

from pathlib import Path

import pytest

from vnpresence.library import Library

EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "examples" / "games").glob("*.yaml"))


def test_examples_exist():
    assert EXAMPLES, "examples/games/ should contain at least one profile"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_profile_is_valid(path):
    profile = Library(path.parent).load_file(path)
    assert profile.title
    assert profile.privacy.value in {"auto", "full", "private", "off"}
    if profile.vndb_id:
        assert profile.vndb_id.startswith("v")
