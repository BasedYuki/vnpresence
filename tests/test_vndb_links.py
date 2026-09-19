"""Telling a novel apart from its sequel.

A name search cannot separate "Rewrite" from "Rewrite+" - the sequel answers to
its parent's name, and VNDB's search rank decides, not the reader. So every
place that asks for a name also takes a link, and a link is never guessed at.
"""

from __future__ import annotations

import pytest

from vnpresence.models import looks_like_vndb_ref, normalise_vndb_id


@pytest.mark.parametrize(
    "text",
    [
        "https://vndb.org/v2400",
        "http://vndb.org/v17",
        "vndb.org/v2400",
        "https://vndb.org/v2400/chars",  # a deeper page still identifies the VN
        "v2400",
        "V2400",
        "  v17  ",
    ],
)
def test_links_and_bare_ids_are_recognised(text):
    assert looks_like_vndb_ref(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Rewrite",
        "Rewrite+",
        "Muv-Luv Alternative",
        "Clannad v2",  # the id-looking part is not the whole string
        "v",
        "",
        "   ",
        "Steins;Gate 0",
    ],
)
def test_game_names_are_not_mistaken_for_links(text):
    assert looks_like_vndb_ref(text) is False


def test_a_recognised_link_resolves_to_its_id():
    assert normalise_vndb_id("https://vndb.org/v2400") == "v2400"
    assert normalise_vndb_id("v2400") == "v2400"
