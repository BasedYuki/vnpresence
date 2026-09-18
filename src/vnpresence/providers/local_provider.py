"""Fallback metadata built from the profile itself (works fully offline)."""

from __future__ import annotations

from ..models import GameMetadata, GameProfile
from .base import MetadataProvider


class LocalMetadataProvider(MetadataProvider):
    name = "local"
    priority = -10  # last resort

    def can_handle(self, profile: GameProfile) -> bool:
        return True

    def fetch(self, profile: GameProfile) -> GameMetadata | None:
        return GameMetadata(
            title=profile.title,
            image_url=profile.image_url,
            description=profile.description,
            source="local",
        )
