"""The commands behind the two new features, exercised as a user runs them."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from vnpresence import notes
from vnpresence.cli import main
from vnpresence.library import Library
from vnpresence.models import GameMetadata, GameProfile
from vnpresence.playtime import Playtime


@pytest.fixture()
def library():
    store = Library()
    store.save(GameProfile(id="rewrite", title="Rewrite", path="/r.exe", vndb_id="v2400"))
    store.save(GameProfile(id="clannad", title="Clannad", path="/c.exe"))
    return store


def run(*args, **kwargs):
    return CliRunner().invoke(main, list(args), **kwargs)


# -- note ------------------------------------------------------------------
def test_note_sets_the_route(library):
    result = run("note", "rewrite", "Kotori route")
    assert result.exit_code == 0
    assert notes.read_note("rewrite") == "Kotori route"


def test_note_without_text_prints_the_current_one(library):
    notes.write_note("rewrite", "Kotori route")
    assert "Kotori route" in run("note", "rewrite").output


def test_note_clear_removes_it(library):
    notes.write_note("rewrite", "Kotori route")
    run("note", "rewrite", "--clear")
    assert notes.read_note("rewrite") is None


def test_note_on_an_unknown_game_says_so(library):
    result = run("note", "nothing", "x")
    assert result.exit_code != 0
    assert "no game matches" in result.output


# -- stats -----------------------------------------------------------------
def test_stats_reports_recorded_time(library):
    Playtime().add("clannad", 7200, new_session=True)
    output = run("stats", "clannad").output
    assert "2h" in output
    assert "1 session" in output


def test_stats_says_when_nothing_has_been_read(library):
    assert "Nothing read yet" in run("stats").output


def test_stats_shows_an_estimate_when_vndb_knows_the_length(library, monkeypatch):
    Playtime().add("rewrite", 5 * 3600)

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def get(self, vndb_id):
            return GameMetadata(title="Rewrite", length_minutes=600)  # 10 hours

    monkeypatch.setattr("vnpresence.cli.VNDBClient", FakeClient)
    assert "~50%" in run("stats", "rewrite").output


# -- link ------------------------------------------------------------------
def test_link_repoints_a_game_and_takes_the_new_title(library, monkeypatch):
    monkeypatch.setattr(
        "vnpresence.cli._lookup",
        lambda vndb_id, config: GameMetadata(
            title="Rewrite+", url="https://vndb.org/v7738", source="vndb"
        ),
    )
    result = run("link", "rewrite", "https://vndb.org/v7738")
    assert result.exit_code == 0
    saved = Library().get("rewrite")
    assert saved.vndb_id == "v7738"
    assert saved.title == "Rewrite+"


def test_link_can_keep_the_title_you_chose(library, monkeypatch):
    monkeypatch.setattr(
        "vnpresence.cli._lookup",
        lambda vndb_id, config: GameMetadata(title="Rewrite+", source="vndb"),
    )
    run("link", "rewrite", "v7738", "--keep-title")
    assert Library().get("rewrite").title == "Rewrite"


def test_link_refuses_something_that_is_not_a_link(library):
    result = run("link", "rewrite", "Rewrite+")
    assert result.exit_code != 0
    assert "not a VNDB link or id" in result.output


def test_link_leaves_the_game_alone_when_vndb_has_nothing(library, monkeypatch):
    monkeypatch.setattr("vnpresence.cli._lookup", lambda vndb_id, config: None)
    result = run("link", "rewrite", "v999999")
    assert result.exit_code != 0
    assert Library().get("rewrite").vndb_id == "v2400"
