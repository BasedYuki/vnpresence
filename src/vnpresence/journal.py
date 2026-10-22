"""A reader's own record of a game: the routes, and private notes.

Two things, one small JSON file per game in ``journal/``:

* **Routes** - named by the reader, ticked off when finished. No database
  agrees on what a "route" is for a given novel (VNDB lists characters and
  releases, not routes), so the reader writes their own list, the way they
  would on paper. The count of finished ones can show in Discord as
  "Routes 2/5".
* **Notes** - free text, saved as it is typed, never sent anywhere.

Kept apart from the profile for the same reason the route/chapter line is:
profiles are what people copy and share, and this is personal.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import config_dir

log = logging.getLogger(__name__)

#: Generous, but a bound: a route name is a name, not an essay.
MAX_ROUTE_NAME = 80
MAX_ROUTES = 60
MAX_NOTES = 20_000


@dataclass
class Route:
    name: str
    done: bool = False


@dataclass
class Journal:
    routes: list[Route] = field(default_factory=list)
    notes: str = ""

    def progress(self) -> tuple[int, int]:
        """(finished, total)."""
        return sum(1 for r in self.routes if r.done), len(self.routes)


def journal_dir() -> Path:
    return config_dir() / "journal"


def journal_path(game_id: str) -> Path:
    return journal_dir() / f"{game_id}.json"


def load(game_id: str) -> Journal:
    """The game's journal. Never raises: a broken file reads as empty."""
    try:
        data = json.loads(journal_path(game_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return Journal()
    if not isinstance(data, dict):
        return Journal()
    routes = []
    for item in data.get("routes") or []:
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            routes.append(Route(_clean_name(item["name"]), bool(item.get("done"))))
    notes = data.get("notes")
    return Journal(routes[:MAX_ROUTES], notes[:MAX_NOTES] if isinstance(notes, str) else "")


def save(game_id: str, journal: Journal) -> None:
    path = journal_path(game_id)
    data = {
        "routes": [{"name": r.name, "done": r.done} for r in journal.routes[:MAX_ROUTES]],
        "notes": journal.notes[:MAX_NOTES],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:  # pragma: no cover - disk trouble
        log.warning("could not save the journal for %s", game_id, exc_info=True)


def _clean_name(text) -> str:
    return " ".join(str(text).split())[:MAX_ROUTE_NAME]


# -- the edits the page makes ---------------------------------------------
def add_route(game_id: str, name: str) -> Journal:
    journal = load(game_id)
    name = _clean_name(name)
    if name and len(journal.routes) < MAX_ROUTES and \
            name.lower() not in {r.name.lower() for r in journal.routes}:
        journal.routes.append(Route(name))
        save(game_id, journal)
    return journal


def set_done(game_id: str, index: int, done: bool) -> Journal:
    journal = load(game_id)
    if 0 <= index < len(journal.routes):
        journal.routes[index].done = bool(done)
        save(game_id, journal)
    return journal


def remove_route(game_id: str, index: int) -> Journal:
    journal = load(game_id)
    if 0 <= index < len(journal.routes):
        del journal.routes[index]
        save(game_id, journal)
    return journal


def move_route(game_id: str, index: int, step: int) -> Journal:
    journal = load(game_id)
    target = index + step
    if 0 <= index < len(journal.routes) and 0 <= target < len(journal.routes):
        routes = journal.routes
        routes[index], routes[target] = routes[target], routes[index]
        save(game_id, journal)
    return journal


def set_notes(game_id: str, text: str) -> None:
    journal = load(game_id)
    journal.notes = (text or "")[:MAX_NOTES]
    save(game_id, journal)


def routes_line(game_id: str) -> str | None:
    """"Routes 2/5" for the presence - or None when there is no list."""
    done, total = load(game_id).progress()
    return f"Routes {done}/{total}" if total else None
