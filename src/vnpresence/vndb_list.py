"""Your VNDB list: a game's status and your rating, sent from the game page.

VNDB's API lets a program edit a reader's list with a personal token, made on
the website - My Profile, the Applications tab - with "Access to my list" and
"Write to my list" ticked. The token is kept in its own file in the
VNPresence folder - not in config.yaml, which people paste into bug reports -
and it is never written to a log.

Status is one of VNDB's four reading labels, which the website treats as one
choice: setting "Finished" there takes "Playing" off. The API does not do that
for us, so setting one here also unsets the other three.

Docs: https://api.vndb.org/kana#patch-ulistid
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import config_dir
from .models import normalise_vndb_id
from .vndb import USER_AGENT

log = logging.getLogger(__name__)

API = "https://api.vndb.org/kana"
#: Where a token is made: sign in, then My Profile -> Applications.
TOKEN_PAGE = "https://vndb.org/"
TOKEN_HOWTO = ("On vndb.org: sign in, open My Profile, go to the Applications tab and "
               "make a new token with \"Access to my list\" and \"Write to my list\" "
               "ticked. Paste it here.")

#: VNDB's built-in reading labels: the same ids for every user.
PLAYING, FINISHED, STALLED, DROPPED = 1, 2, 3, 4
STATUSES = {PLAYING: "Playing", FINISHED: "Finished", STALLED: "Stalled", DROPPED: "Dropped"}

#: A token is groups of letters and digits joined by dashes.
_TOKEN = re.compile(r"[a-z0-9]{4,}(?:-[a-z0-9]{4,}){3,}")


class VNDBListError(RuntimeError):
    """Something a reader can act on: a bad token, no permission, no network."""


@dataclass
class Account:
    token: str
    user: str  # "u12345"
    username: str
    can_write: bool


@dataclass
class ListEntry:
    """What your VNDB list says about one novel."""

    on_list: bool = False
    status: int | None = None  # one of STATUSES, or None
    vote: int | None = None  # VNDB's 10-100

    @property
    def rating(self) -> int | None:
        """The vote as the 1-10 the page shows."""
        return None if self.vote is None else int(round(self.vote / 10))


# -- the token on disk ----------------------------------------------------
def token_file() -> Path:
    return config_dir() / "vndb-account.json"


def looks_like_token(text: str) -> bool:
    return _TOKEN.fullmatch((text or "").strip().lower()) is not None


def load_account() -> Account | None:
    try:
        data = json.loads(token_file().read_text(encoding="utf-8"))
        return Account(token=str(data["token"]), user=str(data["user"]),
                       username=str(data.get("username") or ""),
                       can_write=bool(data.get("can_write")))
    except Exception:
        return None


def save_account(account: Account) -> None:
    path = token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "token": account.token, "user": account.user,
        "username": account.username, "can_write": account.can_write,
    }), encoding="utf-8")


def forget_account() -> None:
    token_file().unlink(missing_ok=True)


# -- the API --------------------------------------------------------------
def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Token {token}", "User-Agent": USER_AGENT,
            "Content-Type": "application/json"}


def _call(method: str, path: str, token: str, *, body: Any = None,
          session: Any = None, timeout: float = 15.0) -> Any:
    http = session or requests
    try:
        response = http.request(method, f"{API}{path}", headers=_headers(token),
                                data=None if body is None else json.dumps(body),
                                timeout=timeout)
    except Exception as exc:
        raise VNDBListError(f"could not reach VNDB: {exc.__class__.__name__}") from exc
    if response.status_code == 401:
        raise VNDBListError("VNDB did not accept the token - it may have been deleted. "
                            "Make a new one and connect again.")
    if response.status_code == 429:
        raise VNDBListError("VNDB is rate limiting; try again in a few minutes.")
    if response.status_code >= 400:
        raise VNDBListError(f"VNDB answered HTTP {response.status_code}")
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def connect(token: str, *, session: Any = None) -> Account:
    """Check a token with VNDB and say whose it is and what it may do."""
    token = (token or "").strip()
    if not looks_like_token(token):
        raise VNDBListError("That does not look like a VNDB token. It is the long "
                            "code with dashes from My Profile -> Applications on VNDB.")
    info = _call("GET", "/authinfo", token, session=session) or {}
    permissions = set(info.get("permissions") or [])
    if "listread" not in permissions:
        raise VNDBListError("That token cannot read your list. Make one with both "
                            "\"Access to my list\" and \"Write to my list\" ticked.")
    return Account(token=token, user=str(info.get("id") or ""),
                   username=str(info.get("username") or ""),
                   can_write="listwrite" in permissions)


def get_entry(account: Account, vndb_id: str, *, session: Any = None) -> ListEntry:
    vid = normalise_vndb_id(vndb_id)
    body = {"user": account.user, "filters": ["id", "=", vid],
            "fields": "labels.id, vote", "results": 1}
    data = _call("POST", "/ulist", account.token, body=body, session=session) or {}
    results = data.get("results") or []
    if not results:
        return ListEntry()
    item = results[0]
    labels = {label.get("id") for label in item.get("labels") or [] if isinstance(label, dict)}
    status = next((s for s in STATUSES if s in labels), None)
    vote = item.get("vote")
    return ListEntry(on_list=True, status=status,
                     vote=vote if isinstance(vote, int) else None)


def _require_write(account: Account) -> None:
    if not account.can_write:
        raise VNDBListError("This token can read your list but not change it. Make "
                            "one with \"Write to my list\" ticked and connect again.")


def status_change(status: int | None) -> dict[str, list[int]]:
    """The PATCH body that leaves exactly this one reading label set."""
    others = [s for s in STATUSES if s != status]
    change: dict[str, list[int]] = {"labels_unset": others}
    if status is not None:
        if status not in STATUSES:
            raise ValueError(f"not a reading status: {status}")
        change["labels_set"] = [status]
    return change


def vote_for(rating: int | float | None) -> int | None:
    """1-10 on the page is 10-100 on VNDB; None clears the vote."""
    if rating is None:
        return None
    rating = float(rating)
    if not 1 <= rating <= 10:
        raise ValueError("a rating is between 1 and 10")
    return int(round(rating * 10))


def set_status(account: Account, vndb_id: str, status: int | None, *,
               session: Any = None) -> None:
    _require_write(account)
    _call("PATCH", f"/ulist/{normalise_vndb_id(vndb_id)}", account.token,
          body=status_change(status), session=session)


def set_rating(account: Account, vndb_id: str, rating: int | float | None, *,
               session: Any = None) -> None:
    _require_write(account)
    _call("PATCH", f"/ulist/{normalise_vndb_id(vndb_id)}", account.token,
          body={"vote": vote_for(rating)}, session=session)
