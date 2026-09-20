"""Orchestration: launch a game, follow it, and keep Discord in sync."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from .config import AppConfig
from .formatter import IDLE, PAUSED, effective_privacy
from .idle import idle_seconds
from .launcher import (
    LaunchError,
    TrackedGame,
    belongs_to,
    find_running,
    launch,
    resolve_tracked_process,
)
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
        #: What the last look said: None while the clock is running, or the
        #: word for why it stopped. Kept rather than asked for on demand so
        #: one answer serves the tick, the presence and the status line,
        #: instead of three trips into Windows for the same question.
        self._stopped: str | None = None
        #: Where Discord's timer counts from. It starts as the launch time -
        #: an ordinary session timer - and is re-anchored after a pause so it
        #: shows time spent reading rather than time spent with the game open.
        self._timer_start = 0.0
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
            {"config": self.config, "start": int(self._timer_start or self.start_time)},
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
            paused=self._stopped,
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

        How long the game has been *open*, which is not the same as how long it
        has been read and is not what Discord's timer shows any more - that one
        follows the reading (see :meth:`_resume_timer`). This is the number the
        session reports at the end, and what the grace period and the process
        checks are measured against.
        """
        return max(time.time() - self.start_time, 0.0) if self.start_time else 0.0

    def look_at_focus(self) -> bool | None:
        """Is the game the window being used? ``None`` means there is no way to tell.

        The *focused* window, not a visible one. Two monitors make the
        difference obvious: a novel sitting open on the left while its reader
        types in Discord on the right is in plain sight and is not being read.
        Windows has exactly one focused window across every monitor, which is
        the question worth asking.

        Three answers, not two, and that matters too. On Linux, on macOS, or
        when the call fails there is nothing to go on - and treating that as
        "paused" would silently stop recording everyone's reading time on a
        platform where the question cannot be asked. Treating it as "reading"
        is the safe direction; saying so honestly is what lets the presence
        avoid claiming a pause it did not actually observe.
        """
        if not self.config.focused_time_only or self._tracked_pid is None:
            return None
        # foreground_pid() already answers None off Windows, so there is no
        # separate platform check to keep in step with it.
        active = foreground_pid()
        if active is None:
            return None
        # The window being used may belong to a process the game started
        # rather than to the game itself, so this is a question about the
        # family, not about one pid.
        return belongs_to(active, self._tracked_pid)

    def look_at_idle(self) -> bool | None:
        """Has nobody touched anything for a long time? ``None`` if unknowable.

        The focused window cannot answer this one. A novel left open while its
        reader goes to bed keeps the focus all night, so without this the
        morning would show eight hours of reading that nobody did.
        """
        limit = self.config.idle_after
        if not limit or limit <= 0:
            return None
        quiet = idle_seconds()
        if quiet is None:
            return None
        return quiet >= limit

    def observe(self) -> str | None:
        """What is happening right now: ``None`` reading, or why it stopped.

        Returns the word the presence will show - "Paused" or "Idle" - so
        there is one place that decides, and the card, the window, the CLI and
        the clock cannot drift apart about it.
        """
        if self.look_at_focus() is False:
            return PAUSED
        if self.look_at_idle() is True:
            return IDLE
        return None

    def is_focused(self) -> bool:
        """Should this moment count as reading? Unknown counts as yes."""
        return self.observe() is None

    def _tick(self, seconds: float) -> str | None:
        """Add a slice of the loop's waiting to the reading total, if it counts.

        Returns what was observed, so the caller can notice the moment it
        changes and tell the reader.
        """
        stopped = self.observe()
        going_idle = stopped == IDLE and self._stopped != IDLE
        self._stopped = stopped
        if seconds > 0 and stopped is None:
            self.read_seconds += seconds
        if going_idle:
            # Idle is only ever noticed in arrears: the reader walked away ten
            # minutes ago and those ten minutes have already been counted as
            # reading. Take them back, or every interruption would quietly pay
            # out the length of the threshold.
            self._give_back_idle_time()
        return stopped

    def _give_back_idle_time(self) -> None:
        """Un-count the stretch that turned out to be nobody there.

        Capped at the threshold plus the poll that noticed it, because no
        longer stretch than that can have been counted - anything more would
        have been caught a tick earlier. The cap is what makes a sleeping
        laptop harmless: Windows keeps the idle clock running while the
        machine is suspended, and without it a lid closed for six hours would
        wipe out an evening that really was read.
        """
        quiet = idle_seconds()
        if quiet is None:
            return
        ceiling = self.config.idle_after + self.config.poll_interval
        self.read_seconds = max(self.read_seconds - min(quiet, ceiling), 0.0)

    def _resume_timer(self) -> None:
        """Re-anchor Discord's timer so it reads as time spent reading.

        Discord draws the timer itself from a start time, counting up second by
        second, and it has no idea the reader walked away. Moving the anchor
        forward by the length of the pause makes the number it shows the time
        actually read - which is the number the rest of the presence reports.
        """
        self._timer_start = time.time() - self.read_seconds

    def _record_playtime(self, *, final: bool = False) -> None:
        """Write this session's reading time into the history. Never raises."""
        unrecorded = self.read_seconds - self._recorded
        if unrecorded == 0 and not final:
            return
        try:
            # Can be negative: going idle takes back minutes that were already
            # written down as reading, and the history has to follow.
            self.playtime.add(self.profile.id, unrecorded, new_session=final)
            self._recorded += unrecorded
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
        self._timer_start = tracked.started_at
        self._tracked_pid = tracked.pid
        self._stopped = self.observe()
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
                was = self._stopped
                stopped = self._tick(self.config.poll_interval)
                if stopped != was:
                    if was is not None:
                        # Back from a pause: the timer picks up where the
                        # reading left off rather than where the game started.
                        self._resume_timer()
                    notify("focus", (stopped or "reading").lower())
                    # Try to say so straight away rather than leaving "Reading"
                    # on the card until the next scheduled update. Discord's
                    # own rate limit may swallow this one; the scheduled update
                    # below then carries it, which is why last_update is left
                    # alone here.
                    self.presence.update(self.build_payload(state))
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
