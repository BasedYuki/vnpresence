"""Checking GitHub for a newer VNPresence, and installing it.

Nobody should have to remember to visit a releases page. VNPresence asks
GitHub once a day whether there is something newer, and if there is, offers to
fetch it.

The awkward part is Windows: a running .exe cannot be overwritten, so the new
one is downloaded *beside* the old one and a one-line PowerShell command is
launched to wait for this process to exit, swap the two files and start the new
one. The old .exe is kept as ``.old`` rather than deleted, so a bad update is
one rename away from being undone.

Nothing here happens on its own. The check is read-only, the download and the
swap both need the reader to say yes, and the whole feature can be turned off
with ``check_updates: false``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__
from .config import config_dir

log = logging.getLogger(__name__)

#: The only place an update may come from. Not configurable on purpose: this
#: value decides what gets downloaded and run on someone's machine.
REPO = "BasedYuki/vnpresence"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"

#: Names of the assets we know how to install, best first.
WINDOWED_ASSET = "VNPresence.exe"
CONSOLE_ASSET = "VNPresence-cli.exe"

#: A downloaded .exe smaller than this is not one of ours - an error page, a
#: truncated transfer - and must never be started.
MIN_ASSET_BYTES = 1_000_000

CHECK_EVERY = 24 * 3600  # seconds between automatic checks


class UpdateError(RuntimeError):
    pass


@dataclass
class Release:
    """What GitHub says the newest release is."""

    version: str
    notes: str = ""
    url: str = RELEASES_PAGE
    published: str = ""
    assets: dict[str, tuple[str, int]] | None = None  # name -> (url, size)

    def asset_for(self, frozen_name: str | None = None) -> tuple[str, str, int] | None:
        """(name, url, size) of the .exe that matches how this copy was built."""
        assets = self.assets or {}
        wanted = frozen_name or WINDOWED_ASSET
        for name in (wanted, WINDOWED_ASSET, CONSOLE_ASSET):
            if name in assets:
                url, size = assets[name]
                return name, url, size
        return None


# -- versions -------------------------------------------------------------
def parse_version(text: str) -> tuple[int, ...]:
    """``"v0.11.0"`` -> ``(0, 11, 0)``. Unparseable parts count as zero."""
    numbers = re.findall(r"\d+", (text or "").strip().lstrip("vV"))
    return tuple(int(n) for n in numbers[:4]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    """True when `candidate` is a later version than `current`.

    Compared piece by piece as numbers, so 0.11.0 beats 0.9.2 - which a string
    comparison gets backwards, and which is exactly the range this project is
    in.
    """
    return parse_version(candidate) > parse_version(current)


# -- asking GitHub --------------------------------------------------------
def latest_release(*, session=None, timeout: float = 10.0) -> Release | None:
    """Ask GitHub for the newest release. Never raises; None means "no idea"."""
    http = session or requests
    try:
        response = http.get(
            RELEASES_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"VNPresence/{__version__} (+https://github.com/{REPO})",
            },
            timeout=timeout,
        )
        if response.status_code != 200:
            log.debug("update check: GitHub returned HTTP %s", response.status_code)
            return None
        data = response.json()
    except Exception:  # offline, DNS, rate limit, malformed json...
        log.debug("update check failed", exc_info=True)
        return None
    return parse_release(data)


def parse_release(data) -> Release | None:
    if not isinstance(data, dict) or not data.get("tag_name"):
        return None
    assets = {}
    for asset in data.get("assets") or []:
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if name and url:
            assets[name] = (url, int(asset.get("size") or 0))
    return Release(
        version=str(data["tag_name"]).lstrip("vV"),
        notes=str(data.get("body") or "").strip(),
        url=str(data.get("html_url") or RELEASES_PAGE),
        published=str(data.get("published_at") or "")[:10],
        assets=assets,
    )


# -- remembering what the reader already answered -------------------------
def state_file() -> Path:
    return config_dir() / "updates.json"


def _state() -> dict:
    try:
        return json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(data: dict) -> None:
    try:
        state_file().parent.mkdir(parents=True, exist_ok=True)
        state_file().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:  # pragma: no cover - the check is not worth a crash
        log.debug("could not write %s", state_file(), exc_info=True)


def skip_version(version: str) -> None:
    """"Don't show again for this version"."""
    _write_state({**_state(), "skipped": version})


def is_skipped(version: str) -> bool:
    return _state().get("skipped") == version


def due_for_check(*, every: float = CHECK_EVERY, now: float | None = None) -> bool:
    """True when the last automatic check was long enough ago."""
    last = _state().get("checked_at") or 0
    return (now or time.time()) - float(last) >= every


def mark_checked(*, now: float | None = None) -> None:
    _write_state({**_state(), "checked_at": now or time.time()})


# -- installing -----------------------------------------------------------
def running_exe() -> Path | None:
    """The .exe this process is, or None when running from source."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve()


def download(url: str, destination: Path, *, session=None, timeout: float = 60.0) -> Path:
    """Fetch a release asset next to the current .exe, verifying it looks real."""
    http = session or requests
    response = http.get(url, stream=True, timeout=timeout)
    if getattr(response, "status_code", 0) != 200:
        raise UpdateError(f"download failed: HTTP {getattr(response, 'status_code', '?')}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(destination, "wb") as handle:
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if chunk:
                handle.write(chunk)
                written += len(chunk)

    if written < MIN_ASSET_BYTES:
        destination.unlink(missing_ok=True)
        raise UpdateError(
            f"the download is only {written} bytes, which is not a VNPresence build"
        )
    with open(destination, "rb") as handle:
        if handle.read(2) != b"MZ":  # every Windows executable starts with it
            destination.unlink(missing_ok=True)
            raise UpdateError("the download is not a Windows executable")
    return destination


def _ps_quote(text: str) -> str:
    """Quote a path for a PowerShell single-quoted string."""
    return "'" + str(text).replace("'", "''") + "'"


def swap_command(current: Path, new: Path, pid: int) -> list[str]:
    """The command that replaces the running .exe once it has exited.

    Windows holds a lock on a running executable, so the swap cannot happen
    inside this process - something has to outlive it. This waits for our pid,
    moves the old build aside (kept, not deleted), puts the new one in its
    place and starts it.
    """
    backup = current.with_suffix(current.suffix + ".old")
    script = (
        f"Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
        "Start-Sleep -Milliseconds 700; "
        f"Move-Item -Force -LiteralPath {_ps_quote(current)} {_ps_quote(backup)}; "
        f"Move-Item -Force -LiteralPath {_ps_quote(new)} {_ps_quote(current)}; "
        f"Start-Process -FilePath {_ps_quote(current)}"
    )
    return ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-Command", script]


def install(release: Release, *, session=None, spawn=None) -> str:
    """Download the new build and arrange the swap. Returns what to tell the user.

    Raises :class:`UpdateError` when this copy cannot update itself - from
    source, or on a platform where the swap trick does not apply - so the
    caller can fall back to pointing at the releases page.
    """
    current = running_exe()
    if current is None:
        raise UpdateError(
            "this copy runs from source, so there is nothing to replace - "
            "update it with git pull, or pip install -U vnpresence"
        )
    if sys.platform != "win32":
        raise UpdateError(f"self-update is only implemented for Windows, not {sys.platform}")

    picked = release.asset_for(current.name)
    if picked is None:
        raise UpdateError("that release has no VNPresence.exe attached")
    _, url, _size = picked

    new = current.with_name(current.stem + ".new" + current.suffix)
    download(url, new, session=session)

    launch = spawn or _spawn_detached
    launch(swap_command(current, new, os.getpid()))
    return (
        f"VNPresence {release.version} was downloaded. It will be installed when this "
        "window closes, and will then start again by itself."
    )


def _spawn_detached(command: list[str]) -> None:  # pragma: no cover - Windows only
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    )
    subprocess.Popen(command, creationflags=flags, close_fds=True)  # noqa: S603


# -- the whole question, in one call --------------------------------------
def check(*, force: bool = False, session=None) -> Release | None:
    """The newest release when it is worth telling the reader about it.

    Returns None when there is nothing newer, when the reader asked not to be
    told about this one, when it is not time to look yet, or when GitHub could
    not be reached - the caller treats every one of those the same way: say
    nothing.
    """
    if not force and not due_for_check():
        return None
    release = latest_release(session=session)
    mark_checked()
    if release is None or not is_newer(release.version):
        return None
    if not force and is_skipped(release.version):
        return None
    return release
