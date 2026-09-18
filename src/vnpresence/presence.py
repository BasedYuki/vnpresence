"""Thin wrapper around the Discord IPC connection.

Goals: never crash the session because Discord is closed, and never spam the
IPC socket (Discord rate-limits presence updates to one per 15 seconds).
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

MIN_UPDATE_INTERVAL = 15.0


class PresenceError(RuntimeError):
    pass


class DiscordPresence:
    """Connects lazily, reconnects quietly, and skips duplicate updates."""

    def __init__(self, client_id: str, *, backend: Any | None = None) -> None:
        self.client_id = str(client_id)
        self._backend = backend
        self._rpc: Any | None = None
        self._last_payload: dict[str, Any] | None = None
        self._last_sent: float = 0.0
        self.connected = False

    # -- connection -------------------------------------------------------
    def connect(self) -> bool:
        if self.connected:
            return True
        try:
            self._rpc = self._make_client()
            self._rpc.connect()
            self.connected = True
            log.info("connected to Discord (client id %s)", self.client_id)
        except Exception as exc:
            self.connected = False
            self._rpc = None
            log.warning("could not connect to Discord: %s", exc)
        return self.connected

    def _make_client(self) -> Any:
        if self._backend is not None:
            return self._backend(self.client_id)
        try:
            from pypresence import Presence
        except ImportError as exc:  # pragma: no cover
            raise PresenceError(
                "pypresence is not installed - run: pip install pypresence"
            ) from exc
        return Presence(self.client_id)

    def close(self) -> None:
        if self._rpc is not None:
            with contextlib.suppress(Exception):
                self._rpc.clear()
            with contextlib.suppress(Exception):
                self._rpc.close()
        self._rpc = None
        self.connected = False
        self._last_payload = None

    # -- updates ----------------------------------------------------------
    def update(self, payload: dict[str, Any] | None, *, force: bool = False) -> bool:
        """Push an activity. ``None`` clears it. Returns True if a call was made."""
        if payload is None:
            return self.clear()
        if not self.connected and not self.connect():
            return False
        now = time.time()
        unchanged = payload == self._last_payload
        too_soon = now - self._last_sent < MIN_UPDATE_INTERVAL
        if unchanged and not force:
            return False
        if too_soon and not force:
            return False
        try:
            self._rpc.update(**payload)  # type: ignore[union-attr]
            self._last_payload = dict(payload)
            self._last_sent = now
            return True
        except Exception as exc:
            log.warning("presence update failed (%s); will reconnect", exc)
            self.close()
            return False

    def clear(self) -> bool:
        if not self.connected or self._rpc is None:
            return False
        try:
            self._rpc.clear()
            self._last_payload = None
            return True
        except Exception:
            self.close()
            return False

    def __enter__(self) -> DiscordPresence:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
