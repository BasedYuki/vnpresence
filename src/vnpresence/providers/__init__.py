"""Built-in providers and the extension-point base classes."""

from .base import MetadataProvider, PresenceFormatter, StateProvider
from .local_provider import LocalMetadataProvider
from .vndb_provider import VNDBMetadataProvider

__all__ = [
    "LocalMetadataProvider",
    "MetadataProvider",
    "PresenceFormatter",
    "StateProvider",
    "VNDBMetadataProvider",
]
