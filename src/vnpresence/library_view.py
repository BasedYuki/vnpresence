"""What the library shows about each game, worked out away from Tk.

The window decides where things go; this decides what they say. Kept apart so
that "Yesterday" versus "2026-10-14", or which game sorts first by last played,
can be tested without a display - and so the list, the grid and the details
page cannot drift into three different answers to the same question.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from .config import AppConfig
from .formatter import effective_privacy
from .models import GameMetadata, GameProfile, PrivacyMode
from .playtime import Entry, format_reading_time

NEVER = "Never"


def _parse(stamp: str | None) -> _dt.datetime | None:
    if not stamp:
        return None
    try:
        return _dt.datetime.fromisoformat(stamp.strip())
    except ValueError:
        return None


def format_last_played(stamp: str | None, now: _dt.datetime | None = None) -> str:
    """``Today``, ``Yesterday``, ``3 days ago``, then the date - or ``Never``.

    PCSX2 shows a bare date, and a bare date makes you do arithmetic to find
    out that you last opened a novel the day before yesterday. Relative for
    the last week, where it is what you want to know; a date after that,
    where "41 days ago" would be the arithmetic instead.
    """
    when = _parse(stamp)
    if when is None:
        return NEVER
    now = now or _dt.datetime.now()
    days = (now.date() - when.date()).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    return when.date().isoformat()


def last_played_key(stamp: str | None) -> float:
    """Seconds since the epoch, for sorting; never-played sorts as oldest."""
    when = _parse(stamp)
    return when.timestamp() if when else 0.0


def format_time_played(seconds: float | None) -> str:
    """``12h 40m`` for the column, ``-`` for a game never opened."""
    text = format_reading_time(seconds)
    return text.replace(" read", "") if text else "-"


def row_values(profile: GameProfile, entry: Entry | None = None,
               now: _dt.datetime | None = None) -> tuple[str, str, str, str, str, str]:
    """One line of the list: game, time, last played, sessions, privacy, VNDB."""
    entry = entry or Entry()
    return (
        profile.title,
        format_time_played(entry.seconds),
        format_last_played(entry.last_played, now),
        str(entry.sessions) if entry.sessions else "-",
        profile.privacy.value,
        profile.vndb_id or "-",
    )


@dataclass
class Card:
    """Everything one tile of the grid, or the details page, needs."""

    id: str
    title: str
    time_played: str
    last_played: str
    sessions: int
    cover_url: str | None
    #: The cover is not drawn: a private or switched-off game gets a plain
    #: card with its name, so the library is safe to have on screen while
    #: streaming or sharing a screen.
    hide_cover: bool
    metadata: GameMetadata | None = None


def card_for(profile: GameProfile, entry: Entry | None, metadata: GameMetadata | None,
             config: AppConfig, now: _dt.datetime | None = None) -> Card:
    entry = entry or Entry()
    mode = effective_privacy(profile, metadata, config)
    cover = profile.image_url or (metadata.image_url if metadata else None)
    return Card(
        id=profile.id,
        title=profile.title,
        time_played=format_time_played(entry.seconds),
        last_played=format_last_played(entry.last_played, now),
        sessions=entry.sessions,
        cover_url=cover,
        hide_cover=mode in (PrivacyMode.PRIVATE, PrivacyMode.OFF),
        metadata=metadata,
    )


def details_lines(card: Card) -> list[tuple[str, str]]:
    """The facts on the details page, label and value, in reading order."""
    meta = card.metadata
    lines: list[tuple[str, str]] = [
        ("Time played", card.time_played if card.time_played != "-" else "Not yet"),
        ("Sessions", str(card.sessions) if card.sessions else "None yet"),
        ("Last played", card.last_played),
    ]
    if meta is not None:
        if meta.alt_title and meta.alt_title != card.title:
            lines.insert(0, ("Original title", meta.alt_title))
        if meta.length:
            lines.append(("Length", meta.length))
        if meta.released:
            lines.append(("Released", meta.released))
        if meta.rating:
            lines.append(("VNDB rating", f"{meta.rating} / 10"))
    return lines
