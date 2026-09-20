"""VNPresence - Discord Rich Presence for visual novels."""

__version__ = "0.14.1"

from .models import GameMetadata, GameProfile, PresenceState, PrivacyMode
from .providers.base import MetadataProvider, PresenceFormatter, StateProvider

__all__ = [
    "GameMetadata",
    "GameProfile",
    "MetadataProvider",
    "PresenceFormatter",
    "PresenceState",
    "PrivacyMode",
    "StateProvider",
    "__version__",
]
