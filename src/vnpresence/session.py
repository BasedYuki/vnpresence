"""Orchestration: launch a game, follow it, and keep Discord in sync."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from .config import AppConfig
from .formatter import effective_privacy
from .launcher import LaunchError, TrackedGame, find_running, launch, resolve_tracked_process
from .models import GameMetadata, GameProfile, PresenceState, PrivacyMode
from .notes import read_note
from .playtime import Playtime
from .plugins import PluginRegistry, build_registry
from .presence import DiscordPresence

log = logging.getLogger(__name__)

#: How often the play time is written to disk while a game is running.
RECORD_EVERY = 60.0


@dataclass
class SessionResult:
    title: str
    seconds: float
    privacy: PrivacyMode
    metadata_source: str
    #: Everything ever read of this game, this session included.
    total_seconds: float = 0.0


class GameSession:
    """One play session, from launch to exit."""

    def __init__(
        self,
        profile: GameProfile,
        config: AppConfig | None = None,
        registry: PluginRegistry | None = None,
        presence: DiscordPresence | None = None,
        playtime: Playtime | None = None,
    ) -> None:
        self.profile = profile
        self.config = config or AppConfig.load()
        self.registry = registry or build_registry(self.config.enabled_plugins or None)
        self.presence = presence or DiscordPresence(
            profile.client_id or self.config.client_id
        )
        self.playtime = playtime or Playtime()
        self.metadata: GameMetadata | None = None
        self.start_time = 0.0
        #: Seconds read before this session started: the total shown is about
        #: the novel, not about today.
        self.previous_seconds = 0.0
        self._recorded = 0.0  # of this session, already written to disk
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
            self.live_state(state),
            {"config": self.config, "start": int(self.start_time)},
        )

    # -- what the reader adds to the picture -------------------------------
    def live_state(self, state: PresenceState) -> PresenceState:
        """The plugin's state plus the note and the total reading time.

        Returns a copy: the state object belongs to the plugin that produced it
        and may well be reused on the next poll.
        """
        note = read_note(self.profile.id)
        total = state.playtime_seconds
        if total is None and self._playtime_enabled():
            total = self.previous_seconds + self.elapsed()
        return replace(
            state,
            # The reader typed the note on purpose, so it outranks a plugin's
            # guess at the same line.
            status_text=note or state.status_text,
            playtime_seconds=total,
        )

    def _playtime_enabled(self) -> bool:
        if self.profile.show_playtime is not None:
            return self.profile.show_playtime
        return self.config.show_playtime

    def elapsed(self) -> float:
        return max(time.time() - self.start_time, 0.0) if self.start_time else 0.0

    def _record_playtime(self, *, final: bool = False) -> None:
        """Write this session's time so far into the history. Never raises."""
        unrecorded = self.elapsed() - self._recorded
        if unrecorded <= 0 and not final:
            return
        try:
            self.playtime.add(self.profile.id, max(unrecorded, 0.0), new_session=final)
            self._recorded += max(unrecorded, 0.0)
        except Exception:  # pragma: no cover - the history is not load-bearing
            log.debug("could not record play time for %s", self.profile.id, exc_info=True)

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
        self.previous_seconds = self.playtime.total(self.profile.id)
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
        last_record = time.time()
        try:
            while not self._stop and tracked.is_running():
                time.sleep(self.config.poll_interval)
                if time.time() - last_record >= RECORD_EVERY:
                    # Save the time as we go. A crash, a power cut or a killed
                    # process then costs a minute of history, not the evening.
                    last_record = time.time()
                    self._record_playtime()
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
            self._record_playtime(final=True)
            self.presence.close()

        seconds = max(time.time() - self.start_time, 0.0)
        total = self.previous_seconds + seconds
        notify("end", f"session ended after {format_duration(seconds)}")
        return SessionResult(
            title=self.profile.title,
            seconds=seconds,
            privacy=privacy,
            metadata_source=(self.metadata or _empty()).source,
            total_seconds=total,
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
