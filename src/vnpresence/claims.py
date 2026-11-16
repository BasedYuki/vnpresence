"""One game, one session: who is tracking which game right now.

VNPresence can be tracking a game from two places at once without knowing it:
the window (Play) and the background watcher (auto-detect) are separate
processes. Press Play with auto-detect on, and the watcher sees the game start
and attaches to it too - two sessions, each adding the same evening to the
history, and a total that comes out doubled.

So a session claims its game first, with a small file in ``active/`` that names
the process holding it. The other side sees the claim and stays out of the
way. A claim left behind by a process that crashed is not respected: the file
records the owner's start time as well as its pid, so a reused pid does not
look like the old owner come back.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import psutil

from .config import config_dir

log = logging.getLogger(__name__)


def claims_dir() -> Path:
    return config_dir() / "active"


def claim_path(game_id: str) -> Path:
    return claims_dir() / f"{game_id}.json"


def _me() -> dict:
    try:
        started = psutil.Process(os.getpid()).create_time()
    except Exception:  # pragma: no cover
        started = 0.0
    return {"pid": os.getpid(), "started": started}


def _alive(owner: dict) -> bool:
    try:
        process = psutil.Process(int(owner["pid"]))
        return abs(process.create_time() - float(owner.get("started") or 0)) < 2.0
    except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, TypeError, ValueError):
        return False


def holder(game_id: str) -> int | None:
    """The pid of *another* live VNPresence process tracking this game, if any."""
    try:
        owner = json.loads(claim_path(game_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(owner, dict) or owner.get("pid") == os.getpid():
        return None
    return int(owner["pid"]) if _alive(owner) else None


def claim(game_id: str) -> bool:
    """Take the game for this process. False if another live session has it."""
    if holder(game_id) is not None:
        return False
    path = claim_path(game_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(_me()), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:  # pragma: no cover - a read-only folder must not stop the game
        log.debug("could not write the claim for %s", game_id, exc_info=True)
    return True


def release(game_id: str) -> None:
    """Let go - only of a claim this process holds."""
    path = claim_path(game_id)
    try:
        owner = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(owner, dict) and owner.get("pid") == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        pass


def held_elsewhere(game_ids) -> set[str]:
    """Which of these games another session is tracking right now."""
    return {game_id for game_id in game_ids if holder(game_id) is not None}
