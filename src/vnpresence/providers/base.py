"""The three extension points of VNPresence.

Adding a game normally needs no code at all (a YAML profile is enough).
These interfaces exist for the cases where behaviour, not data, is missing.

* :class:`MetadataProvider` - where a game's title/cover/description comes from.
* :class:`StateProvider`    - live per-session information (chapter, route...).
* :class:`PresenceFormatter`- the final Discord activity payload.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..models import GameMetadata, GameProfile, PresenceState


class MetadataProvider:
    """Resolves descriptive information for a game."""

    #: Unique name, used in config and in ``metadata_provider:``.
    name: str = "unnamed"
    #: Higher priority wins when several providers can handle a profile.
    priority: int = 0

    def can_handle(self, profile: GameProfile) -> bool:
        raise NotImplementedError

    def fetch(self, profile: GameProfile) -> GameMetadata | None:
        raise NotImplementedError


class StateProvider:
    """Produces the live state of a running session.

    Implementations must be non-blocking: :meth:`poll` is called on the session
    loop and should return quickly (or return ``None`` to keep the last state).
    """

    name: str = "unnamed"

    def start(self, profile: GameProfile, pid: int | None) -> None:  # noqa: B027
        """Called once when the game is up. Open files/hooks here."""

    def poll(self) -> PresenceState | None:
        """Called every update interval. Return ``None`` to keep the last state."""
        return None

    def stop(self) -> None:  # noqa: B027
        """Called once when the session ends. Release resources here."""


class PresenceFormatter:
    """Builds the payload that is sent to Discord."""

    name: str = "unnamed"
    priority: int = 0

    def format(
        self,
        profile: GameProfile,
        metadata: GameMetadata | None,
        state: PresenceState,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return kwargs for ``pypresence.Presence.update``, or ``None`` to hide."""
        raise NotImplementedError


@runtime_checkable
class Registrable(Protocol):
    """A plugin module exposes ``register(registry)``."""

    def register(self, registry: Any) -> None: ...
