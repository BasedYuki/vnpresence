"""Orchestration: launch a game, follow it, and keep Discord in sync."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .formatter import effective_privacy
from .launcher import LaunchError, TrackedGame, find_running, launch, resolve_tracked_process
from .models import GameMetadata, GameProfile, PresenceState, PrivacyMode
from .plugins import PluginRegistry, build_registry
from .presence import DiscordPresence

log = logging.getLogger(__name__)


@dataclass
class SessionResult:
    title: str
    seconds: float
    privacy: PrivacyMode
    metadata_source: str


class GameSession:
    """One play session, from launch to exit."""

    def __init__(
        self,
        profile: GameProfile,
        config: AppConfig | None = None,
        registry: PluginRegistry | None = None,
        presence: DiscordPresence | None = None,
    ) -> None:
        self.profile = profile
        self.config = config or AppConfig.load()
        self.registry = registry or build_registry(self.config.enabled_plugins or None)
        self.presence = presence or DiscordPresence(
            profile.client_id or self.config.client_id
        )
        self.metadata: GameMetadata | None = None
        self.start_time = 0.0
        self._stop = False

    # -- metadata ---------------------------------------------------------
    def resolve_metadata(self) -> GameMetadata | None:
        provider = self.registry.metadata_provider_for(self.profile)
        if provider is None:
            return None
        metadata = provider.fetch(self.profile)
        if metadata is not None and self.profile.image_url:
            metadata.image_url = self.profile.image_url
        if metadata is not None and self.profile.description:
            metadata.description = self.profile.description
        self.metadata = metadata
        return metadata

    def build_payload(self, state: PresenceState) -> dict[str, Any] | None:
        formatter = self.registry.formatter()
        return formatter.format(
            self.profile,
            self.metadata,
            state,
            {"config": self.config, "start": int(self.start_time)},
        )

    # -- run --------------------------------------------------------------
    def run(
        self,
        *,
        attach: bool = False,
        on_event: Callable[[str, str], None] | None = None,
    ) -> SessionResult:
        notify = on_event or (lambda kind, message: log.info("%s: %s", kind, message))

        self.resolve_metadata()
        privacy = effective_privacy(self.profile, self.metadata, self.config)
        notify("metadata", f"{self.profile.title} ({(self.metadata or _empty()).source})")
        if privacy is PrivacyMode.PRIVATE:
            notify("privacy", "18+ or private game: showing a neutral activity")

        tracked = self._start_game(attach=attach)
        self.start_time = tracked.started_at
        notify("launch", f"tracking {tracked.name} (pid {tracked.pid})")

        state_provider = self.registry.state_provider_for(self.profile)
        if state_provider is not None:
            try:
                state_provider.start(self.profile, tracked.pid)
            except Exception:
                log.exception("state plugin failed to start")
                state_provider = None

        state = PresenceState()
        if not (self.profile.client_id or self.config.client_id):
            notify(
                "warning",
                "no Discord application id set - see docs/discord-setup.md "
                "(the game still runs, nothing is published)",
            )
        else:
            self.presence.connect()
            if not self.presence.connected:
                notify("warning", "Discord is not running - the game keeps working")

        payload = self.build_payload(state)
        self.presence.update(payload, force=True)
        notify("presence", "activity published" if payload else "activity hidden")

        last_update = time.time()
        try:
            while not self._stop and tracked.is_running():
                time.sleep(self.config.poll_interval)
                if time.time() - last_update < self.config.update_interval:
                    continue
                last_update = time.time()
                if state_provider is not None:
                    try:
                        new_state = state_provider.poll()
                        if new_state is not None:
                            state = new_state
                    except Exception:
                        log.exception("state plugin poll failed; disabling it")
                        state_provider = None
                self.presence.update(self.build_payload(state))
        except KeyboardInterrupt:
            notify("stop", "interrupted")
        finally:
            if state_provider is not None:
                try:
                    state_provider.stop()
                except Exception:
                    log.exception("state plugin failed to stop")
            self.presence.close()

        seconds = max(time.time() - self.start_time, 0.0)
        notify("end", f"session ended after {format_duration(seconds)}")
        return SessionResult(
            title=self.profile.title,
            seconds=seconds,
            privacy=privacy,
            metadata_source=(self.metadata or _empty()).source,
        )

    def stop(self) -> None:
        self._stop = True

    # -- internals --------------------------------------------------------
    def _start_game(self, *, attach: bool) -> TrackedGame:
        if attach:
            tracked = find_running(self.profile)
            if tracked is None:
                raise LaunchError(f"{self.profile.title} does not seem to be running")
            return tracked
        process = launch(self.profile)
        tracked = resolve_tracked_process(self.profile, process)
        if tracked is None:
            raise LaunchError(
                f"{self.profile.title} exited immediately. If it uses a launcher "
                "(Locale Emulator, a config tool...), add the real executable name "
                "to 'process_names' in the game profile."
            )
        return tracked


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _empty() -> GameMetadata:
    return GameMetadata(title="", source="none")
