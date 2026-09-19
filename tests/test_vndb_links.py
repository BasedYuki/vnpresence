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


# -- picking the right entry out of a search -------------------------------
def _vn(title, votes, **kwargs):
    from vnpresence.models import GameMetadata

    return GameMetadata(title=title, votes=votes, source="vndb", **kwargs)


def test_the_well_known_entry_beats_the_near_empty_namesake():
    """The real bug: VNDB ranks a 2-vote 'rewrite' above the 8000-vote one."""
    from vnpresence.vndb import rank

    results = [_vn("rewrite", 2), _vn("Rewrite", 8433), _vn("Rewrite Harvest festa!", 709)]
    assert [v.title for v in rank("rewrite", results)][0] == "Rewrite"


def test_case_and_spacing_do_not_stop_an_exact_match():
    from vnpresence.vndb import rank

    results = [_vn("muv-luv alternative", 10), _vn("Muv-Luv", 5000)]
    assert rank("  MUV-LUV  ", results)[0].title == "Muv-Luv"


def test_an_alternative_title_counts_as_an_exact_match():
    from vnpresence.vndb import rank

    results = [_vn("Something Else", 90000), _vn("Kaikan Phrase", 12, alt_title="快感♥フレーズ")]
    assert rank("快感♥フレーズ", results)[0].title == "Kaikan Phrase"


def test_without_an_exact_match_vndbs_own_order_is_kept():
    """Its relevance ranking is the best signal when nothing matches exactly."""
    from vnpresence.vndb import rank

    results = [_vn("Muv-Luv Alternative", 3), _vn("Muv-Luv Unlimited", 9000)]
    assert [v.title for v in rank("muv luv", results)] == [
        "Muv-Luv Alternative",
        "Muv-Luv Unlimited",
    ]
