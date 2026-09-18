"""Turning game data into a Discord activity payload.

Discord's layout, and what we put where::

    Playing Visual Novel      <- the Discord application's name (not settable)
    [cover]  Steins;Gate      <- details      (the game title)
             Reading          <- state        (status text / plugin state)
             01:23 elapsed    <- timestamps.start
             [View on VNDB]   <- buttons

Field limits enforced here: details/state must be 2-128 characters, and Discord
silently drops an activity whose strings are out of range.
"""

from __future__ import annotations

from typing import Any

from .config import AppConfig
from .models import GameMetadata, GameProfile, PresenceState, PrivacyMode
from .providers.base import PresenceFormatter

MAX_FIELD = 128
MIN_FIELD = 2


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

        if mode is PrivacyMode.PRIVATE:
            return {
                "details": clamp(config.private_title),
                "state": clamp(state.status_text or config.default_status_text),
                "start": start,
            }

        title = profile.title or (metadata.title if metadata else "Visual Novel")
        status = state.status_text or profile.status_text or config.default_status_text

        if config.use_activity_name:
            # Current Discord clients honour `name`, so the header itself can be
            # the game: "Playing Steins;Gate". The title then does not need to be
            # repeated in `details`, which frees that line for the status.
            payload: dict[str, Any] = {
                "name": clamp(title),
                "details": clamp(status),
                "state": clamp(_subtitle(metadata) if metadata else None),
                "start": start,
            }
        else:
            # Older clients ignore `name` and print the application's name, so
            # the title has to live in `details` or it would be lost entirely.
            payload = {
                "details": clamp(title),
                "state": clamp(status),
                "start": start,
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
            # With the name layout the subtitle is already on the state line,
            # so the little icon shows the title instead of repeating it.
            fallback = title if config.use_activity_name else _subtitle(metadata)
            payload["small_text"] = clamp(state.small_text or fallback)

        show_buttons = (
            profile.show_buttons if profile.show_buttons is not None else config.show_buttons
        )
        if show_buttons and metadata and metadata.url:
            payload["buttons"] = [{"label": "View on VNDB", "url": metadata.url}]

        return {k: v for k, v in payload.items() if v is not None}


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
