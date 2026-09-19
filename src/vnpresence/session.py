"""Orchestration: launch a game, follow it, and keep Discord in sync."""

from __future__ import annotations

import logging
import re
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
from .titlebar import foreground_pid, titles_for

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
    #: Of this session, the part spent with the game actually in front.
    read_seconds: float = 0.0


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
        #: Seconds of *this* session actually spent reading - the game in the
        #: foreground, not the game sitting behind a browser. Time is added a
        #: tick at a time by the loop rather than measured from the clock,
        #: because the clock cannot know where the reader was looking.
        self.read_seconds = 0.0
        self._tracked_pid: int | None = None
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
        chapter = self.chapter_from_title()
        total = state.playtime_seconds
        if total is None and self._playtime_enabled():
            total = self.previous_seconds + self.read_seconds
        return replace(
            state,
            # In order of how much they know: what the reader typed, what the
            # game itself says in its title bar, then whatever a plugin found.
            status_text=note or chapter or state.status_text,
            playtime_seconds=total,
        )

    def chapter_from_title(self) -> str | None:
        """The chapter, if the game writes one into its own window title.

        A minority of visual novels do - and for those this is the whole
        feature, with no plugin, no memory reading and no save-file parsing.
        The profile supplies the pattern because only someone looking at that
        game's title bar knows what it says.
        """
        pattern = self.profile.chapter_pattern
        if not pattern or self._tracked_pid is None:
            return None
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            log.warning("%s: chapter_pattern is not a valid regex", self.profile.id)
            self.profile.chapter_pattern = None  # do not retry it every update
            return None
        for title in titles_for(self._tracked_pid):
            found = compiled.search(title)
            if found:
                text = found.group(1) if found.groups() else found.group(0)
                if text and text.strip():
                    return " ".join(text.split())
        return None

    def _playtime_enabled(self) -> bool:
        if self.profile.show_playtime is not None:
            return self.profile.show_playtime
        return self.config.show_playtime

    def elapsed(self) -> float:
        """Wall-clock seconds since the game started.

        This is what Discord's timer shows, and it keeps running while you are
        elsewhere - every game on Discord behaves that way, and a timer that
        jumped backwards would look broken. The *reading* total is the one that
        pauses; see :meth:`is_focused`.
        """
        return max(time.time() - self.start_time, 0.0) if self.start_time else 0.0

    def is_focused(self) -> bool:
        """Is the game the window being used right now?

        Unknown counts as yes. On Linux, on macOS, or if the call fails, there
        is no way to tell - and silently recording nobody's reading time would
        be far worse than counting a few minutes spent in a browser.
        """
        if not self.config.focused_time_only or self._tracked_pid is None:
            return True
        active = foreground_pid()
        return active is None or active == self._tracked_pid

    def _tick(self, seconds: float) -> None:
        """Add a slice of the loop's waiting to the reading total, if it counts."""
        if seconds > 0 and self.is_focused():
            self.read_seconds += seconds

    def _record_playtime(self, *, final: bool = False) -> None:
        """Write this session's reading time into the history. Never raises."""
        unrecorded = self.read_seconds - self._recorded
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
        self._tracked_pid = tracked.pid
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
                # Count the slice that just passed, but only if it was spent
                # in the game. Alt-tab away and the total stops moving.
                self._tick(self.config.poll_interval)
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
        total = self.previous_seconds + self.read_seconds
        notify("end", f"session ended after {format_duration(seconds)}")
        return SessionResult(
            title=self.profile.title,
            seconds=seconds,
            privacy=privacy,
            metadata_source=(self.metadata or _empty()).source,
            total_seconds=total,
            read_seconds=self.read_seconds,
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
