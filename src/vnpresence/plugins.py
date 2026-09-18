"""Plugin discovery and the registry that holds every extension point."""

from __future__ import annotations

import logging
from importlib import metadata as importlib_metadata
from typing import Any

from .models import GameProfile
from .providers.base import MetadataProvider, PresenceFormatter, StateProvider

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "vnpresence.plugins"


class PluginRegistry:
    """Holds providers and formatters, built-in and third-party alike."""

    def __init__(self) -> None:
        self.metadata_providers: list[MetadataProvider] = []
        self.state_providers: dict[str, type[StateProvider]] = {}
        self.formatters: list[PresenceFormatter] = []
        self.loaded: list[str] = []

    # -- registration -----------------------------------------------------
    def add_metadata_provider(self, provider: MetadataProvider) -> None:
        self.metadata_providers.append(provider)
        self.metadata_providers.sort(key=lambda p: -p.priority)

    def add_state_provider(self, provider_cls: type[StateProvider]) -> None:
        self.state_providers[provider_cls.name] = provider_cls

    def add_formatter(self, formatter: PresenceFormatter) -> None:
        self.formatters.append(formatter)
        self.formatters.sort(key=lambda f: -f.priority)

    # -- lookup -----------------------------------------------------------
    def metadata_provider_for(self, profile: GameProfile) -> MetadataProvider | None:
        if profile.metadata_provider:
            for provider in self.metadata_providers:
                if provider.name == profile.metadata_provider:
                    return provider
            log.warning("metadata provider %r not found", profile.metadata_provider)
        for provider in self.metadata_providers:
            try:
                if provider.can_handle(profile):
                    return provider
            except Exception:  # pragma: no cover - defensive
                log.exception("provider %s failed can_handle", provider.name)
        return None

    def state_provider_for(self, profile: GameProfile) -> StateProvider | None:
        if not profile.plugin:
            return None
        cls = self.state_providers.get(profile.plugin)
        if cls is None:
            log.warning("state plugin %r is not installed", profile.plugin)
            return None
        try:
            return cls(**profile.plugin_options) if profile.plugin_options else cls()
        except Exception:
            log.exception("could not create state plugin %r", profile.plugin)
            return None

    def formatter(self) -> PresenceFormatter:
        return self.formatters[0]

    def describe(self) -> dict[str, Any]:
        return {
            "loaded": list(self.loaded),
            "metadata_providers": [p.name for p in self.metadata_providers],
            "state_providers": sorted(self.state_providers),
            "formatters": [f.name for f in self.formatters],
        }


def build_registry(enabled: list[str] | None = None) -> PluginRegistry:
    """Create a registry with the built-ins plus any installed plugin."""
    from .formatter import DefaultFormatter
    from .providers.local_provider import LocalMetadataProvider
    from .providers.vndb_provider import VNDBMetadataProvider

    registry = PluginRegistry()
    registry.add_metadata_provider(VNDBMetadataProvider())
    registry.add_metadata_provider(LocalMetadataProvider())
    registry.add_formatter(DefaultFormatter())
    registry.loaded.append("builtin")

    for entry_point in _iter_entry_points():
        if enabled and entry_point.name not in enabled:
            continue
        try:
            module = entry_point.load()
            register = getattr(module, "register", None)
            if register is None:
                log.warning("plugin %r has no register() function", entry_point.name)
                continue
            register(registry)
            registry.loaded.append(entry_point.name)
        except Exception:
            log.exception("failed to load plugin %r", entry_point.name)
    return registry


def _iter_entry_points() -> list[Any]:
    try:
        return list(importlib_metadata.entry_points(group=ENTRY_POINT_GROUP))
    except Exception:  # pragma: no cover - very old importlib
        return []
