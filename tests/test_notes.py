"""The hand-typed route or chapter.

The note is the only part of the presence the reader writes themselves, and the
session re-reads it on every update, so the two things worth pinning down are
that a write is visible to the next read and that a missing or broken note
never raises - the presence loop has no business dying over a text file.
"""

from __future__ import annotations

from vnpresence import notes


def test_a_written_note_comes_back():
    notes.write_note("muv-luv", "Chapter 3 - Ayamine route")
    assert notes.read_note("muv-luv") == "Chapter 3 - Ayamine route"


def test_no_note_is_none_not_an_error():
    assert notes.read_note("never-played") is None


def test_whitespace_is_tidied_so_the_presence_line_stays_clean():
    notes.write_note("x", "  common   route \n second loop  ")
    assert notes.read_note("x") == "common route second loop"


def test_a_very_long_note_is_cut_to_something_discord_accepts():
    notes.write_note("x", "route " * 100)
    assert len(notes.read_note("x")) <= notes.MAX_NOTE


def test_writing_an_empty_note_clears_it():
    notes.write_note("x", "Route A")
    notes.write_note("x", "   ")
    assert notes.read_note("x") is None


def test_clearing_says_whether_there_was_anything_to_clear():
    notes.write_note("x", "Route A")
    assert notes.clear_note("x") is True
    assert notes.clear_note("x") is False


def test_an_unreadable_note_reads_as_none(monkeypatch):
    notes.write_note("x", "Route A")

    def explode(*args, **kwargs):
        raise OSError("file is locked")

    monkeypatch.setattr("pathlib.Path.read_text", explode)
    assert notes.read_note("x") is None


def test_notes_are_kept_out_of_the_shared_profile_folder():
    # Profiles are the part of a library people copy around; notes are not.
    notes.write_note("x", "Route A")
    assert notes.note_path("x").parent.name == "notes"
