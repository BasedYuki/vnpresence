"""Minimal VNDB (Kana) API client with an on-disk cache.

The public API needs no authentication. Limits: 200 requests / 5 minutes.
Docs: https://api.vndb.org/kana
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from .config import cache_dir
from .models import GameMetadata, normalise_vndb_id
from .playtime import BUCKET_MINUTES

log = logging.getLogger(__name__)

API_URL = "https://api.vndb.org/kana/vn"
USER_AGENT = "VNPresence (+https://github.com/BasedYuki/vnpresence)"

FIELDS = (
    "id, title, alttitle, image.url, image.sexual, image.violence, "
    "description, released, languages, platforms, length, length_minutes, "
    "length_votes, rating, "
    "tags.name, tags.category, tags.rating, tags.spoiler"
)

#: Bumped whenever the shape of a cached entry changes, so an old cache is
#: refetched instead of silently missing the new fields.
CACHE_SCHEMA = 2

LENGTH_LABELS = {
    1: "Very short (< 2h)",
    2: "Short (2-10h)",
    3: "Medium (10-30h)",
    4: "Long (30-50h)",
    5: "Very long (> 50h)",
}


class VNDBError(RuntimeError):
    pass


class VNDBClient:
    """Queries VNDB and caches responses as JSON files."""

    def __init__(
        self,
        cache_path: Path | None = None,
        cache_days: int = 30,
        timeout: float = 10.0,
        session: Any | None = None,
    ) -> None:
        self.cache_path = (cache_path or cache_dir()) / "vndb"
        self.cache_days = cache_days
        self.timeout = timeout
        self._session = session

    # -- public -----------------------------------------------------------
    def get(self, vndb_id: str, *, refresh: bool = False) -> GameMetadata | None:
        vndb_id = normalise_vndb_id(vndb_id)
        if not refresh:
            cached = self._read_cache(vndb_id)
            if cached is not None:
                return GameMetadata.from_dict(cached)
        results = self._query({"filters": ["id", "=", vndb_id], "fields": FIELDS})
        if not results:
            return None
        metadata = parse_vn(results[0])
        self._write_cache(vndb_id, metadata.to_dict())
        return metadata

    def search(self, term: str, limit: int = 10) -> list[GameMetadata]:
        results = self._query(
            {
                "filters": ["search", "=", term],
                "fields": FIELDS,
                "sort": "searchrank",
                "results": limit,
            }
        )
        return [parse_vn(item) for item in results]

    # -- internals --------------------------------------------------------
    def _query(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        session = self._session or requests
        try:
            response = session.post(
                API_URL,
                json=payload,
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except Exception as exc:  # network down, proxy, DNS...
            raise VNDBError(f"could not reach VNDB: {exc}") from exc
        if response.status_code == 429:
            raise VNDBError("VNDB rate limit reached, try again in a few minutes")
        if response.status_code >= 400:
            raise VNDBError(f"VNDB returned HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        return list(data.get("results", []))

    def _cache_file(self, vndb_id: str) -> Path:
        return self.cache_path / f"{vndb_id}.json"

    def _read_cache(self, vndb_id: str) -> dict[str, Any] | None:
        path = self._cache_file(vndb_id)
        if not path.exists():
            return None
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days > self.cache_days:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict) or data.get("_schema") != CACHE_SCHEMA:
            return None  # written by an older version: fetch it again
        return data

    def _write_cache(self, vndb_id: str, data: dict[str, Any]) -> None:
        data = {**data, "_schema": CACHE_SCHEMA}
        try:
            self.cache_path.mkdir(parents=True, exist_ok=True)
            self._cache_file(vndb_id).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:  # pragma: no cover - cache is best effort
            log.debug("could not write VNDB cache for %s", vndb_id, exc_info=True)


def parse_vn(item: dict[str, Any]) -> GameMetadata:
    """Map a VNDB ``vn`` object onto :class:`GameMetadata`."""
    image = item.get("image") or {}
    length = item.get("length")
    rating = item.get("rating")
    votes = item.get("length_votes")
    votes = int(votes) if isinstance(votes, (int, float)) else 0
    minutes = item.get("length_minutes")
    minutes = int(minutes) if isinstance(minutes, (int, float)) and minutes > 0 else None
    if minutes is None and isinstance(length, int):
        # Nobody reported a play time: fall back to the middle of the bucket,
        # and leave length_votes at 0 so the guess is recognisable as one.
        minutes = BUCKET_MINUTES.get(length)
        votes = 0
    return GameMetadata(
        title=item.get("title") or item.get("alttitle") or "Unknown",
        alt_title=item.get("alttitle"),
        image_url=image.get("url"),
        description=clean_description(item.get("description")),
        released=item.get("released"),
        languages=list(item.get("languages") or []),
        platforms=list(item.get("platforms") or []),
        length=LENGTH_LABELS.get(length) if isinstance(length, int) else None,
        length_minutes=minutes,
        length_votes=votes,
        rating=round(rating / 10, 1) if isinstance(rating, (int, float)) else None,
        nsfw=is_nsfw(item),
        url=f"https://vndb.org/{item.get('id')}" if item.get("id") else None,
        source="vndb",
    )


def is_nsfw(item: dict[str, Any]) -> bool:
    """Best-effort 18+ detection, used by the ``auto`` privacy mode.

    Two independent signals, because neither alone is reliable:
    the cover art's sexual rating (0-2), and VNDB content tags.
    """
    image = item.get("image") or {}
    sexual = image.get("sexual")
    if isinstance(sexual, (int, float)) and sexual >= 1.0:
        return True
    for tag in item.get("tags") or []:
        if tag.get("category") != "cont":
            continue
        name = (tag.get("name") or "").lower()
        rating = tag.get("rating") or 0
        if rating >= 1.5 and any(
            word in name for word in ("sex", "erotic", "hentai", "nukige", "rape", "porn")
        ):
            return True
    return False


def clean_description(raw: str | None, limit: int = 300) -> str | None:
    """Strip VNDB markup and shorten to something that fits a presence line."""
    if not raw:
        return None
    text = raw
    for marker in ("[spoiler]", "[/spoiler]", "[i]", "[/i]", "[b]", "[/b]"):
        text = text.replace(marker, "")
    while "[url=" in text:
        start = text.index("[url=")
        end = text.find("]", start)
        if end == -1:
            break
        text = text[:start] + text[end + 1 :]
    text = text.replace("[/url]", "").replace("\r", "")
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or None
