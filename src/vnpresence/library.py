"""The game library: one YAML file per game in the user's config directory."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .config import games_dir
from .models import GameProfile, slugify

log = logging.getLogger(__name__)


class Library:
    """Loads, saves and validates game profiles."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or games_dir()

    # -- reading ----------------------------------------------------------
    def path_for(self, game_id: str) -> Path:
        return self.directory / f"{game_id}.yaml"

    def load_all(self) -> list[GameProfile]:
        profiles: list[GameProfile] = []
        if not self.directory.exists():
            return profiles
        for path in sorted(self.directory.glob("*.y*ml")):
            try:
                profiles.append(self.load_file(path))
            except Exception as exc:
                log.error("skipping %s: %s", path.name, exc)
        return profiles

    def load_file(self, path: Path) -> GameProfile:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("profile must be a YAML mapping")
        data.setdefault("id", path.stem)
        return GameProfile.from_dict(data)

    def get(self, game_id: str) -> GameProfile | None:
        path = self.path_for(game_id)
        if path.exists():
            return self.load_file(path)
        for profile in self.load_all():
            if profile.id == game_id:
                return profile
        return None

    def find(self, needle: str) -> GameProfile | None:
        """Match by id first, then by a case-insensitive title substring."""
        exact = self.get(needle)
        if exact:
            return exact
        needle_low = needle.lower()
        matches = [p for p in self.load_all() if needle_low in p.title.lower()]
        return matches[0] if len(matches) == 1 else None

    # -- writing ----------------------------------------------------------
    def unique_id(self, title: str) -> str:
        base = slugify(title)
        candidate, n = base, 2
        while self.path_for(candidate).exists():
            candidate = f"{base}-{n}"
            n += 1
        return candidate

    def save(self, profile: GameProfile) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(profile.id)
        data = profile.to_dict()
        data.pop("id", None)  # the filename is the id
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    def remove(self, game_id: str) -> bool:
        path = self.path_for(game_id)
        if path.exists():
            path.unlink()
            return True
        return False
