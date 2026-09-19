"""Core data models for VNPresence.

Plain dataclasses on purpose: no pydantic, so the frozen .exe stays small and
contributors do not need to learn an extra library.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PrivacyMode(str, Enum):
    """How much of a game is exposed in the Discord activity."""

    #: Show everything: title, cover art, description, VNDB button.
    FULL = "full"
    #: Show a neutral "Reading a visual novel" activity with no title/art.
    PRIVATE = "private"
    #: Do not publish any activity for this game.
    OFF = "off"
    #: Decide per game from metadata (18+ content -> PRIVATE, else FULL).
    AUTO = "auto"


def slugify(value: str) -> str:
    """Turn a title into a stable, filesystem-safe profile id."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    value = re.sub(r"[\s_-]+", "-", value)
    return value or "game"


@dataclass
class GameProfile:
    """A game the user added. Serialised as one YAML file in the library.

    Everything a normal user needs is here; nothing in this class requires code.
    """

    id: str
    title: str
    path: str = ""
    args: list[str] = field(default_factory=list)
    working_dir: str | None = None

    # Metadata lookup
    vndb_id: str | None = None  # e.g. "v17"
    image_url: str | None = None  # overrides the cover from the provider
    description: str | None = None  # overrides the provider description

    # Process tracking
    process_names: list[str] = field(default_factory=list)
    launcher_grace: float = 12.0  # seconds to wait for a relaunched process

    # Presence
    privacy: PrivacyMode = PrivacyMode.AUTO
    status_text: str | None = None  # overrides the second presence line
    client_id: str | None = None  # advanced: per-game Discord application
    show_buttons: bool | None = None  # None -> follow global config
    show_playtime: bool | None = None  # None -> follow global config

    # Plugins
    plugin: str | None = None  # name of a StateProvider plugin
    plugin_options: dict[str, Any] = field(default_factory=dict)
    metadata_provider: str | None = None  # force a MetadataProvider by name

    #: Old profile keys and what they are called now. Profiles written by an
    #: older version have to keep loading: renaming a key without an alias
    #: would turn someone's library into "unknown profile key" errors.
    RENAMED = {"show_progress": "show_playtime"}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameProfile:
        data = dict(data)
        for old, new in cls.RENAMED.items():
            if old in data:
                data.setdefault(new, data.pop(old))
                data.pop(old, None)
        known = {f for f in cls.__dataclass_fields__}  # noqa: PLC0206
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown profile key(s): {', '.join(sorted(unknown))}")
        if "title" not in data:
            raise ValueError("profile is missing required key: title")
        data.setdefault("id", slugify(str(data["title"])))
        if "privacy" in data and data["privacy"] is not None:
            data["privacy"] = PrivacyMode(str(data["privacy"]).lower())
        if isinstance(data.get("args"), str):
            data["args"] = [data["args"]]
        if isinstance(data.get("process_names"), str):
            data["process_names"] = [data["process_names"]]
        if data.get("vndb_id"):
            data["vndb_id"] = normalise_vndb_id(str(data["vndb_id"]))
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        defaults = GameProfile(id=self.id, title=self.title)
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name in ("id", "title"):
                out[name] = value
                continue
            if value == getattr(defaults, name):
                continue  # keep the YAML minimal and readable
            out[name] = value.value if isinstance(value, PrivacyMode) else value
        return out


def looks_like_vndb_ref(text: str) -> bool:
    """True when this is a VNDB link or id rather than a game's name.

    Searching by name cannot separate a novel from its sequel when they share
    one - "Rewrite" and "Rewrite+" - so anywhere a name is asked for, a link is
    accepted instead. The test is deliberately strict: a bare id has to be the
    whole string, or a title like "Clannad v2" would be read as an id.
    """
    text = text.strip()
    if not text:
        return False
    if "vndb.org" in text.lower():
        return True
    return re.fullmatch(r"v\d+", text, flags=re.IGNORECASE) is not None


def normalise_vndb_id(raw: str) -> str:
    """Accept ``17``, ``v17`` or a full VNDB URL and return ``v17``."""
    raw = raw.strip()
    match = re.search(r"v(\d+)", raw)
    if match:
        return f"v{match.group(1)}"
    if raw.isdigit():
        return f"v{raw}"
    raise ValueError(f"not a VNDB id: {raw!r}")


@dataclass
class GameMetadata:
    """Descriptive information about a visual novel, from any provider."""

    title: str
    alt_title: str | None = None
    image_url: str | None = None
    description: str | None = None
    released: str | None = None
    languages: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    length: str | None = None
    rating: float | None = None
    #: How many people rated it. Not for display: it is how a well-known novel
    #: is told from a near-empty entry that happens to share its name.
    votes: int = 0
    nsfw: bool = False
    url: str | None = None
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "alt_title": self.alt_title,
            "image_url": self.image_url,
            "description": self.description,
            "released": self.released,
            "languages": list(self.languages),
            "platforms": list(self.platforms),
            "length": self.length,
            "rating": self.rating,
            "votes": self.votes,
            "nsfw": self.nsfw,
            "url": self.url,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameMetadata:
        allowed = {f for f in cls.__dataclass_fields__}  # noqa: PLC0206
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class PresenceState:
    """Live, changing information about the current session.

    Built-in providers return a static state; a plugin can return the current
    chapter, route, or play time instead.
    """

    status_text: str | None = None
    small_text: str | None = None
    small_image: str | None = None
    #: Total time this game has been read, in seconds, across every session.
    #: The session fills this in from the history it keeps; a plugin with a
    #: better figure - one the game itself reports - can set it directly.
    playtime_seconds: float | None = None
    #: Restart the elapsed timer from this unix timestamp (rarely needed).
    start_timestamp: int | None = None
