"""Checking for a new VNPresence, and replacing the running one with it.

This is the one feature that downloads a file and then runs it, so the tests
are about the guard rails as much as the happy path: only this repository, only
something that looks like a real build, never without being asked, and never
leaving someone with a broken .exe and no way back.
"""

from __future__ import annotations

import json
import sys

import pytest

from vnpresence import update
from vnpresence.update import Release


class FakeResponse:
    def __init__(self, payload=None, status=200, body=b""):
        self.status_code = status
        self._payload = payload
        self._body = body

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


RELEASE_JSON = {
    "tag_name": "v9.9.9",
    "html_url": "https://github.com/BasedYuki/vnpresence/releases/tag/v9.9.9",
    "published_at": "2026-09-19T21:00:00Z",
    "body": "presence: something new\n\n- and a fix",
    "assets": [
        {
            "name": "VNPresence.exe",
            "browser_download_url": "https://example.invalid/VNPresence.exe",
            "size": 15_000_000,
        },
        {
            "name": "VNPresence-cli.exe",
            "browser_download_url": "https://example.invalid/VNPresence-cli.exe",
            "size": 15_000_000,
        },
    ],
}


# -- comparing versions ---------------------------------------------------
@pytest.mark.parametrize(
    ("newer", "older"),
    [
        ("0.11.0", "0.9.2"),   # the one a string comparison gets backwards
        ("0.11.0", "0.10.0"),
        ("1.0.0", "0.99.9"),
        ("v0.12.0", "0.11.0"),
        ("0.11.1", "0.11.0"),
    ],
)
def test_version_order(newer, older):
    assert update.is_newer(newer, older)
    assert not update.is_newer(older, newer)


def test_the_same_version_is_not_newer():
    assert not update.is_newer("0.11.0", "0.11.0")
    assert not update.is_newer("v0.11.0", "0.11.0")


def test_nonsense_never_counts_as_an_update():
    assert not update.is_newer("", "0.11.0")
    assert not update.is_newer("dev", "0.11.0")


# -- asking GitHub --------------------------------------------------------
def test_a_release_is_read_out_of_githubs_answer():
    release = update.latest_release(session=FakeHttp(FakeResponse(RELEASE_JSON)))
    assert release.version == "9.9.9"  # the v is not part of the version
    assert release.published == "2026-09-19"
    assert "something new" in release.notes
    assert release.asset_for("VNPresence.exe")[0] == "VNPresence.exe"


def test_the_console_build_updates_itself_not_the_windowed_one():
    release = update.parse_release(RELEASE_JSON)
    assert release.asset_for("VNPresence-cli.exe")[0] == "VNPresence-cli.exe"


def test_github_being_unreachable_is_silent():
    assert update.latest_release(session=FakeHttp(OSError("no network"))) is None


def test_a_rate_limit_is_silent_too():
    assert update.latest_release(session=FakeHttp(FakeResponse(status=403))) is None


def test_rubbish_json_is_silent():
    assert update.latest_release(session=FakeHttp(FakeResponse(payload={"x": 1}))) is None


def test_only_this_repository_is_ever_asked():
    http = FakeHttp(FakeResponse(RELEASE_JSON))
    update.latest_release(session=http)
    assert http.calls == [update.RELEASES_API]
    assert "BasedYuki/vnpresence" in update.RELEASES_API


# -- what the reader already answered -------------------------------------
def test_a_skipped_version_is_not_mentioned_again():
    update.skip_version("9.9.9")
    assert update.is_skipped("9.9.9")
    assert not update.is_skipped("9.9.10")  # but the next one is


def test_check_respects_a_skip(monkeypatch):
    monkeypatch.setattr(update, "latest_release", lambda **k: Release(version="9.9.9"))
    update.skip_version("9.9.9")
    assert update.check() is None
    # ... unless the reader asked, by pressing the button
    assert update.check(force=True) is not None


def test_check_does_not_ask_github_more_than_once_a_day(monkeypatch):
    asked = []
    monkeypatch.setattr(
        update, "latest_release", lambda **k: asked.append(1) or Release(version="9.9.9")
    )
    assert update.check() is not None
    assert update.check() is None  # too soon
    assert len(asked) == 1
    assert update.check(force=True) is not None  # the button always asks
    assert len(asked) == 2


def test_an_older_release_is_not_an_update(monkeypatch):
    monkeypatch.setattr(update, "latest_release", lambda **k: Release(version="0.0.1"))
    assert update.check(force=True) is None


def test_a_broken_state_file_does_not_stop_the_check(monkeypatch):
    update.state_file().parent.mkdir(parents=True, exist_ok=True)
    update.state_file().write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(update, "latest_release", lambda **k: Release(version="9.9.9"))
    assert update.check(force=True) is not None


# -- downloading ----------------------------------------------------------
def _exe_bytes(size=update.MIN_ASSET_BYTES + 10):
    return b"MZ" + b"\0" * (size - 2)


def test_a_downloaded_build_is_kept(tmp_path):
    http = FakeHttp(FakeResponse(body=_exe_bytes()))
    out = update.download("https://example.invalid/x.exe", tmp_path / "new.exe", session=http)
    assert out.exists() and out.stat().st_size > update.MIN_ASSET_BYTES


def test_a_tiny_download_is_refused_and_deleted(tmp_path):
    """An error page saved as .exe must never be left lying around to run."""
    http = FakeHttp(FakeResponse(body=b"MZ404 not found"))
    target = tmp_path / "new.exe"
    with pytest.raises(update.UpdateError, match="not a VNPresence build"):
        update.download("https://example.invalid/x.exe", target, session=http)
    assert not target.exists()


def test_something_that_is_not_an_executable_is_refused(tmp_path):
    http = FakeHttp(FakeResponse(body=b"<!DOCTYPE html>" + b" " * update.MIN_ASSET_BYTES))
    target = tmp_path / "new.exe"
    with pytest.raises(update.UpdateError, match="not a Windows executable"):
        update.download("https://example.invalid/x.exe", target, session=http)
    assert not target.exists()


def test_a_failed_download_raises_rather_than_writing_rubbish(tmp_path):
    http = FakeHttp(FakeResponse(status=404, body=b""))
    with pytest.raises(update.UpdateError, match="HTTP 404"):
        update.download("https://example.invalid/x.exe", tmp_path / "new.exe", session=http)


# -- the swap -------------------------------------------------------------
def test_the_swap_waits_for_this_process_and_keeps_the_old_build(tmp_path):
    current = tmp_path / "VNPresence.exe"
    new = tmp_path / "VNPresence.new.exe"
    command = update.swap_command(current, new, pid=4242)
    joined = " ".join(command)
    assert command[0] == "powershell"
    assert "Wait-Process -Id 4242" in joined     # not before we have exited
    assert str(current) in joined and str(new) in joined
    assert "VNPresence.exe.old" in joined        # the old build is kept, not deleted
    assert "Start-Process" in joined             # and the new one is started


def test_a_path_with_a_quote_in_it_cannot_break_out_of_the_command(tmp_path):
    odd = tmp_path / "it's here" / "VNPresence.exe"
    joined = " ".join(update.swap_command(odd, odd.with_suffix(".new.exe"), pid=1))
    assert "it''s here" in joined  # doubled, the way PowerShell escapes it


# -- installing -----------------------------------------------------------
def test_running_from_source_says_so_instead_of_pretending(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    with pytest.raises(update.UpdateError, match="runs from source"):
        update.install(update.parse_release(RELEASE_JSON))


def test_a_release_with_no_exe_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "running_exe", lambda: tmp_path / "VNPresence.exe")
    monkeypatch.setattr(sys, "platform", "win32")
    empty = Release(version="9.9.9", assets={})
    with pytest.raises(update.UpdateError, match="no VNPresence.exe"):
        update.install(empty)


def test_a_successful_install_downloads_then_schedules_the_swap(monkeypatch, tmp_path):
    current = tmp_path / "VNPresence.exe"
    current.write_bytes(b"MZ old build")
    monkeypatch.setattr(update, "running_exe", lambda: current)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        update, "download", lambda url, dest, **k: dest.write_bytes(b"MZ new") or dest
    )
    spawned = []
    message = update.install(update.parse_release(RELEASE_JSON), spawn=spawned.append)

    assert (tmp_path / "VNPresence.new.exe").exists()   # beside the old one
    assert current.exists()                             # which is still running
    assert spawned and "Wait-Process" in " ".join(spawned[0])
    assert "9.9.9" in message


def test_nothing_is_downloaded_just_by_checking(monkeypatch):
    """The check is read-only; installing is a separate, asked-for step."""
    monkeypatch.setattr(
        update, "download", lambda *a, **k: pytest.fail("a check must not download")
    )
    monkeypatch.setattr(update, "latest_release", lambda **k: Release(version="9.9.9"))
    assert update.check(force=True).version == "9.9.9"


def test_the_state_file_stays_readable(monkeypatch):
    monkeypatch.setattr(update, "latest_release", lambda **k: Release(version="9.9.9"))
    update.check(force=True)
    update.skip_version("9.9.9")
    data = json.loads(update.state_file().read_text(encoding="utf-8"))
    assert data["skipped"] == "9.9.9"
    assert data["checked_at"] > 0
