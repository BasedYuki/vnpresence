"""Turning game data into a Discord activity payload.

Discord's layout, and what we put where::

    Playing Steins;Gate       <- name         (the game; see use_activity_name)
    [cover]  Steins;Gate      <- the card's own title line
             Reading          <- details      (status text / note / plugin state)
             Long • 2009 • 12h read   <- state (VNDB, plus total time read)
             01:23 elapsed    <- timestamps.start
             [View on VNDB]   <- buttons

When the reader is working in another window the details line reads "Paused",
and when nobody has touched anything for a long time it reads "Idle". Either
way the timestamp is left out entirely, so Discord has no clock to tick.

The cover's tooltip is the game; the corner icon's tooltip names the app, so
the two do not say the same thing twice.

Field limits enforced here: details/state must be 2-128 characters, and Discord
silently drops an activity whose strings are out of range.
"""

from __future__ import annotations

from typing import Any

from .config import AppConfig
from .models import GameMetadata, GameProfile, PresenceState, PrivacyMode
from .playtime import format_reading_time
from .providers.base import PresenceFormatter

MAX_FIELD = 128
MIN_FIELD = 2

#: What the status line says when the clock is not running. "Paused" is the
#: reader working in another window - on this monitor or any other; "Idle" is
#: the novel left in focus with nobody touching anything. The reading total
#: stops in both, so the card never claims progress nobody is making.
PAUSED = "Paused"
IDLE = "Idle"


def clamp(text: str | None, limit: int = MAX_FIELD) -> str | None:
    """Fit a string into a Discord text field, or drop it if it is too short."""
    if not text:
        return None
    text = " ".join(str(text).split())
    if len(text) < MIN_FIELD:
        text = text + " "  # Discord rejects single characters
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def effective_privacy(
    profile: GameProfile, metadata: GameMetadata | None, config: AppConfig
) -> PrivacyMode:
    """Resolve ``auto`` into a concrete mode using the game's metadata."""
    if profile.privacy is not PrivacyMode.AUTO:
        return profile.privacy
    if config.nsfw_auto_private and metadata is not None and metadata.nsfw:
        return PrivacyMode.PRIVATE
    return PrivacyMode.FULL


class DefaultFormatter(PresenceFormatter):
    """The presence layout shipped with VNPresence."""

    name = "default"
    priority = 0

    def format(
        self,
        profile: GameProfile,
        metadata: GameMetadata | None,
        state: PresenceState,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        config: AppConfig = context["config"]
        start: int = context["start"]
        mode = effective_privacy(profile, metadata, config)

        if mode is PrivacyMode.OFF:
            return None

        # A stopped clock gets no running timer. Discord counts the timer up
        # on its own from this start time and cannot know the reader walked
        # away, so a timer left in place would tick merrily on next to the
        # word "Paused" - which looks broken, and is the thing being
        # complained about. Dropping it and putting it back on resume is the
        # honest version, and the session moves the anchor forward by the
        # length of the pause so the number that returns is time read, not
        # time open.
        timer = None if state.paused else start

        if mode is PrivacyMode.PRIVATE:
            # Nothing that came from the game or the reader goes out here. A
            # route name ("Ayamine route") or a reading total would identify
            # the novel just as surely as its title, which is the one thing
            # private mode exists to withhold. "Paused" says nothing about
            # which novel it is, so it is allowed through.
            private = {
                "details": clamp(config.private_title),
                "state": clamp(
                    _with_pause(
                        config.default_status_text, state.paused, config.default_status_text
                    )
                ),
                "start": timer,
            }
            return {k: v for k, v in private.items() if v is not None}

        title = profile.title or (metadata.title if metadata else "Visual Novel")
        status = _with_pause(
            state.status_text or profile.status_text or config.default_status_text,
            state.paused,
            config.default_status_text,
        )

        read_for = format_reading_time(state.playtime_seconds)

        if config.use_activity_name:
            # Current Discord clients honour `name`, so the header itself can be
            # the game: "Playing Steins;Gate". The title then does not need to be
            # repeated in `details`, which frees that line for the status.
            payload: dict[str, Any] = {
                "name": clamp(title),
                "details": clamp(status),
                "state": clamp(_join(_subtitle(metadata) if metadata else None, read_for)),
                "start": timer,
            }
        else:
            # Older clients ignore `name` and print the application's name, so
            # the title has to live in `details` or it would be lost entirely.
            # There is no third line for the reading time, so it joins the
            # status rather than pushing the title off the card.
            payload = {
                "details": clamp(title),
                "state": clamp(_join(status, read_for)),
                "start": timer,
            }

        large_image = profile.image_url or (metadata.image_url if metadata else None)
        if large_image:
            payload["large_image"] = large_image
            payload["large_text"] = clamp(
                (metadata.alt_title if metadata else None) or title
            )

        small_image = state.small_image or config.small_image
        if small_image and large_image:
            payload["small_image"] = small_image
            # The game is already the header and the cover's tooltip, so the
            # corner icon names the app - unless a plugin or the config says
            # otherwise, or there is nothing to show but the VNDB details.
            fallback = config.small_text or (
                title if config.use_activity_name else _subtitle(metadata)
            )
            payload["small_text"] = clamp(state.small_text or fallback)

        show_buttons = (
            profile.show_buttons if profile.show_buttons is not None else config.show_buttons
        )
        if show_buttons and metadata and metadata.url:
            payload["buttons"] = [{"label": "View on VNDB", "url": metadata.url}]

        return {k: v for k, v in payload.items() if v is not None}


def _with_pause(status: str | None, stopped: str | None, default: str | None) -> str | None:
    """The status line, marked with why the clock stopped - or left alone.

    A plain "Reading" becomes "Paused" or "Idle" outright - they are answers to
    the same question. Anything more specific is kept and marked, because
    "Chapter 3 - Ayamine route" is where the reader is whether or not they are
    looking at it, and throwing it away for the length of a coffee break would
    be a strange thing to do to a status line.
    """
    if not stopped:
        return status
    if not status or status.strip().casefold() == (default or "").strip().casefold():
        return stopped
    suffix = f" ({stopped.casefold()})"
    trimmed = clamp(status, MAX_FIELD - len(suffix))
    return f"{trimmed}{suffix}" if trimmed else stopped


def _join(*parts: str | None) -> str | None:
    """Join the pieces of a presence line with the separator used throughout."""
    kept = [p for p in parts if p]
    return " • ".join(kept) or None


def _subtitle(metadata: GameMetadata | None) -> str | None:
    """A short line for the small-image tooltip: length, release year, rating."""
    if metadata is None:
        return "Visual Novel"
    bits: list[str] = []
    if metadata.length:
        bits.append(metadata.length)
    if metadata.released:
        bits.append(metadata.released[:4])
    if metadata.rating:
        bits.append(f"★ {metadata.rating}")
    return " • ".join(bits) or "Visual Novel"
