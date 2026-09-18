"""Application paths and global configuration."""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

APP_NAME = "VNPresence"

#: The Discord application VNPresence connects to.
#:
#: Discord takes the bold "Playing <name>" line from the application's own name,
#: not from the payload, so this application is named "Visual Novel" and the game
#: title goes in the `details` line.
#:
#: This is the project's own application, named "a Visual Novel" - that name is
#: what Discord prints after the word "Playing", so users need no setup at all.
#: An application id is public information, not a secret.
#: Users can override it in config.yaml, or per game with `client_id`.
DEFAULT_CLIENT_ID = "1550587693673488434"

#: Small icon in the corner of the cover art. Any public https URL works, so
#: the project's own icon is served straight from the repository - no asset
#: upload, and no bumping into Discord's 300-asset limit. Set it to "" to turn
#: the corner icon off, or to an uploaded asset's key to use that instead.
DEFAULT_SMALL_IMAGE = (
    "https://raw.githubusercontent.com/BasedYuki/vnpresence/main/assets/icon-256.png"
)


def config_dir() -> Path:
    """Per-user configuration directory."""
    override = os.environ.get("VNPRESENCE_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "vnpresence"


def games_dir() -> Path:
    return config_dir() / "games"


def cache_dir() -> Path:
    if sys.platform in ("win32", "darwin") or os.environ.get("VNPRESENCE_HOME"):
        return config_dir() / "cache"
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "vnpresence"


def config_file() -> Path:
    return config_dir() / "config.yaml"


@dataclass
class AppConfig:
    """Global settings. Every field has a sane default."""

    client_id: str = DEFAULT_CLIENT_ID
    #: Default privacy for newly added games.
    default_privacy: str = "auto"
    #: Second presence line when a game provides nothing more specific.
    default_status_text: str = "Reading"
    #: Put the game's name in the activity itself, so the header reads
    #: "Playing Steins;Gate" instead of "Playing a Visual Novel". Current
    #: Discord clients honour this; set it to false on a very old client, where
    #: the name is ignored and the title belongs on the second line instead.
    #: Check yours with: python tools/probe_name_override.py
    use_activity_name: bool = True
    #: Text shown for the neutral activity in private mode.
    private_title: str = "Reading a visual novel"
    #: Show the "View on VNDB" button.
    show_buttons: bool = True
    #: Small image (icon) shown in the corner of the cover art.
    small_image: str = DEFAULT_SMALL_IMAGE
    #: Seconds between presence updates. Discord rate-limits to 1 per 15s.
    update_interval: float = 15.0
    #: Seconds between process checks while a game is running.
    poll_interval: float = 2.0
    #: Seconds between scans in auto-detect mode (`vnpresence watch`).
    watch_interval: float = 5.0
    #: Treat 18+ titles as private when a game's privacy is "auto".
    nsfw_auto_private: bool = True
    #: How long VNDB responses stay cached, in days.
    cache_days: int = 30
    #: Enabled plugin names; empty means "all installed plugins".
    enabled_plugins: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        path = path or config_file()
        if not path.exists():
            return cls()
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        allowed = {f for f in cls.__dataclass_fields__}  # noqa: PLC0206
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def save(self, path: Path | None = None) -> Path:
        path = path or config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(asdict(self), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path
