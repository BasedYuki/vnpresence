"""Start VNPresence with Windows.

Uses the per-user *Run* key, which is the normal place for "start this with
Windows": no administrator rights, no scheduled task, no shortcut file to go
stale, and removing the value is a complete uninstall of the behaviour.

Everything goes through a small backend object so the logic can be tested
without a registry (and so a Linux or macOS build fails politely instead of
crashing on an import).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Protocol

from .daemon import _self_command

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "VNPresence"


class StartupUnsupported(RuntimeError):
    """Raised when the platform has no supported autostart mechanism."""


class Backend(Protocol):
    def read(self, name: str) -> str | None: ...
    def write(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class WindowsRunKey:
    """The real thing: HKEY_CURRENT_USER\\...\\Run."""

    def _key(self, write: bool = False):
        import winreg

        access = winreg.KEY_SET_VALUE if write else winreg.KEY_READ
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)

    def read(self, name: str) -> str | None:
        import winreg

        try:
            with self._key() as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None
        except OSError:
            log.debug("could not read the Run key", exc_info=True)
            return None

    def write(self, name: str, value: str) -> None:
        import winreg

        with self._key(write=True) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg

        try:
            with self._key(write=True) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


class Unsupported:
    """Stand-in on platforms without a Run key."""

    def read(self, name: str) -> str | None:
        return None

    def write(self, name: str, value: str) -> None:
        raise StartupUnsupported(
            "starting with the system is only supported on Windows for now"
        )

    def delete(self, name: str) -> None:
        return None


def default_backend() -> Backend:
    return WindowsRunKey() if sys.platform == "win32" else Unsupported()


def startup_command() -> str:
    """The command Windows should run at login, quoted for the registry."""
    return subprocess.list2cmdline(_self_command(["watch"]))


def is_enabled(backend: Backend | None = None) -> bool:
    return (backend or default_backend()).read(VALUE_NAME) is not None


def enable(backend: Backend | None = None) -> str:
    command = startup_command()
    (backend or default_backend()).write(VALUE_NAME, command)
    return command


def disable(backend: Backend | None = None) -> None:
    (backend or default_backend()).delete(VALUE_NAME)


def set_enabled(enabled: bool, backend: Backend | None = None) -> None:
    if enabled:
        enable(backend)
    else:
        disable(backend)
