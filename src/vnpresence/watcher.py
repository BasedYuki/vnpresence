"""Auto-detect mode: notice a game that was started outside VNPresence.

The launcher path (``vnpresence play``) starts the game itself. This one does
the opposite: it watches the running processes and, the moment one of them
matches a game in your library, attaches to it and publishes the presence.
That covers games you start from Steam, a desktop shortcut, or a launcher of
their own.

One scan of the process table serves the whole library, so the cost does not
grow with the number of games you have added.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import psutil

from .config import AppConfig
from .launcher import _split_path
from .library import Library
from .models import GameProfile, PrivacyMode
from .plugins import PluginRegistry, build_registry
from .session import GameSession

log = logging.getLogger(__name__)

EventHandler = Callable[[str, str], None]


@dataclass
class Match:
    profile: GameProfile
    pid: int
    process_name: str


class LibraryWatcher:
    """Polls the process table and attaches to whichever game shows up."""

    def __init__(
        self,
        config: AppConfig | None = None,
        library: Library | None = None,
        registry: PluginRegistry | None = None,
        interval: float | None = None,
    ) -> None:
        self.config = config or AppConfig.load()
        self.library = library or Library()
        self.registry = registry or build_registry(self.config.enabled_plugins or None)
        self.interval = interval or self.config.watch_interval
        self._stop = False
        self._session: GameSession | None = None

    # -- matching ---------------------------------------------------------
    def watchable(self) -> list[GameProfile]:
        """Games worth watching: everything except the ones set to `off`."""
        return [p for p in self.library.load_all() if p.privacy is not PrivacyMode.OFF]

    def find_match(self, profiles: list[GameProfile] | None = None) -> Match | None:
        """Return the first library game that is currently running."""
        profiles = self.watchable() if profiles is None else profiles
        if not profiles:
            return None

        wanted: dict[str, GameProfile] = {}
        for profile in profiles:
            for name in profile.process_names:
                wanted.setdefault(name.lower(), profile)
            _, exe_name = _split_path(profile.path or "")
            if exe_name:
                wanted.setdefault(exe_name, profile)

        for process in psutil.process_iter(["pid", "name"]):
            try:
                name = (process.info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            profile = wanted.get(name)
            if profile is not None:
                return Match(profile, process.info["pid"], name)
        return None

    # -- loop -------------------------------------------------------------
    def run(self, on_event: EventHandler | None = None, *, once: bool = False) -> None:
        notify = on_event or (lambda kind, message: log.info("%s: %s", kind, message))
        notify("watch", f"watching {len(self.watchable())} game(s); Ctrl+C to stop")

        try:
            while not self._stop:
                match = self.find_match()
                if match is None:
                    if once:
                        return
                    time.sleep(self.interval)
                    continue

                notify("detected", f"{match.profile.title} ({match.process_name})")
                self._session = GameSession(match.profile, self.config, self.registry)
                try:
                    self._session.run(attach=True, on_event=notify)
                except Exception as exc:
                    # A single bad game must not take the watcher down with it.
                    log.exception("session for %s failed", match.profile.id)
                    notify("error", f"{match.profile.title}: {exc}")
                finally:
                    self._session = None
                if once:
                    return
                # Say so, otherwise the silence after a session looks like a hang.
                notify("watch", "watching again; Ctrl+C to stop")
                time.sleep(self.interval)
        except KeyboardInterrupt:
            notify("watch", "stopped")

    def stop(self) -> None:
        self._stop = True
        if self._session is not None:
            self._session.stop()
