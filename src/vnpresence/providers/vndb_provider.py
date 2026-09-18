"""Metadata from VNDB."""

from __future__ import annotations

import logging

from ..models import GameMetadata, GameProfile
from ..vndb import VNDBClient, VNDBError
from .base import MetadataProvider

log = logging.getLogger(__name__)


class VNDBMetadataProvider(MetadataProvider):
    name = "vndb"
    priority = 10

    def __init__(self, client: VNDBClient | None = None) -> None:
        self.client = client or VNDBClient()

    def can_handle(self, profile: GameProfile) -> bool:
        return bool(profile.vndb_id)

    def fetch(self, profile: GameProfile) -> GameMetadata | None:
        if not profile.vndb_id:
            return None
        try:
            return self.client.get(profile.vndb_id)
        except VNDBError as exc:
            # Offline or rate-limited: the session still runs, just with less info.
            log.warning("VNDB lookup failed for %s: %s", profile.vndb_id, exc)
            return None
