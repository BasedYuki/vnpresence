"""The route or chapter the reader types in by hand.

No visual novel engine agrees on how to say where you are in the story, and
most say nothing at all. Rather than guess, VNPresence lets the reader write it
down: "Ayamine route", "Chapter 3", "common route, second loop".

The note lives in its own small file per game rather than in the game's profile,
for two reasons. The session re-reads it on every update, so typing a new route
while the game is running changes the activity within seconds - no restart. And
it is personal, throwaway text; profiles are the part of the library people copy
and share, and someone's route notes have no business travelling with them.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import config_dir

log = logging.getLogger(__name__)

#: Discord would cut anything longer off anyway; this keeps the file sane.
MAX_NOTE = 128


def notes_dir() -> Path:
    return config_dir() / "notes"


def note_path(game_id: str) -> Path:
    return notes_dir() / f"{game_id}.txt"


def read_note(game_id: str) -> str | None:
    """The current note for a game, or ``None`` if there is none.

    Never raises: this is called on the session loop, and a missing or
    unreadable note must not take the presence down with it.
    """
    try:
        text = note_path(game_id).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    text = " ".join(text.split())
    return text[:MAX_NOTE] or None


def write_note(game_id: str, text: str) -> Path:
    """Set the note. An empty string clears it, same as :func:`clear_note`."""
    text = " ".join(text.split())[:MAX_NOTE]
    if not text:
        clear_note(game_id)
        return note_path(game_id)
    path = note_path(game_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def clear_note(game_id: str) -> bool:
    """Remove the note. True if there was one."""
    try:
        note_path(game_id).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:  # pragma: no cover - permissions, locked file
        log.debug("could not clear the note for %s", game_id, exc_info=True)
        return False
