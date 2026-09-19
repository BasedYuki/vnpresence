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


def test_stats_shows_no_percentage_anywhere(library):
    """It reports what was measured; it does not guess how far in that is."""
    Playtime().add("rewrite", 5 * 3600, new_session=True)
    output = run("stats", "rewrite").output
    assert "5h" in output
    assert "%" not in output


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


# -- rename ----------------------------------------------------------------
def test_rename_changes_only_the_title(library):
    result = run("rename", "rewrite", "STEINS;GATE", "Re:Boot")
    assert result.exit_code == 0
    saved = Library().get("rewrite")
    assert saved.title == "STEINS;GATE Re:Boot"
    assert saved.vndb_id == "v2400"  # the cover source is untouched
    assert saved.path == "/r.exe"


def test_rename_on_an_unknown_game_says_so(library):
    assert run("rename", "nothing", "X").exit_code != 0


def test_doctor_points_at_games_with_no_cover(library, monkeypatch):
    """Clannad was added without a VNDB match; nothing else ever said so."""
    monkeypatch.setattr("vnpresence.cli._vndb_check", lambda config: None)
    output = run("doctor").output
    assert "no vndb" in output
    assert "vnpresence link clannad" in output


def test_doctor_stays_quiet_when_every_game_is_matched(library, monkeypatch):
    monkeypatch.setattr("vnpresence.cli._vndb_check", lambda config: None)
    store = Library()
    clannad = store.get("clannad")
    clannad.vndb_id = "v4"
    store.save(clannad)
    assert "no vndb" not in run("doctor").output


# -- rematch ---------------------------------------------------------------
def _match(title, vid):
    return GameMetadata(title=title, url=f"https://vndb.org/{vid}", source="vndb"), vid


def test_rematch_all_fills_in_the_missing_links(library, monkeypatch):
    monkeypatch.setattr(
        "vnpresence.cli._search_interactive", lambda term, cfg: _match("Clannad", "v4")
    )
    result = run("rematch", "--all")
    assert result.exit_code == 0
    assert Library().get("clannad").vndb_id == "v4"


def test_rematch_leaves_the_title_alone(library, monkeypatch):
    """A name the reader chose - "STEINS;GATE Re:Boot" - is not VNDB's to take."""
    store = Library()
    profile = store.get("clannad")
    profile.title = "Clannad (my own patch)"
    store.save(profile)
    monkeypatch.setattr(
        "vnpresence.cli._search_interactive", lambda term, cfg: _match("Clannad", "v4")
    )
    run("rematch", "--all")
    saved = Library().get("clannad")
    assert saved.vndb_id == "v4"
    assert saved.title == "Clannad (my own patch)"


def test_rematch_skips_games_that_already_match(library, monkeypatch):
    seen = []
    monkeypatch.setattr(
        "vnpresence.cli._search_interactive",
        lambda term, cfg: seen.append(term) or _match("Clannad", "v4"),
    )
    run("rematch", "--all")
    assert seen == ["Clannad"]  # Rewrite already has v2400


def test_rematch_needs_to_be_told_what_to_do(library):
    assert run("rematch").exit_code != 0


def test_rematch_that_finds_nothing_changes_nothing(library, monkeypatch):
    monkeypatch.setattr("vnpresence.cli._search_interactive", lambda term, cfg: (None, None))
    run("rematch", "--all")
    assert Library().get("clannad").vndb_id is None
