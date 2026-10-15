"""Cover art on disk, and screenshots into a game's gallery."""

from __future__ import annotations

import io
import os
import time

import pytest
from PIL import Image

from vnpresence import covers, screenshots
from vnpresence.screenshots import HotkeyError, Window, parse_hotkey, pick_game_window


def jpeg_bytes(size=(60, 85), colour="navy") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, "JPEG")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.content = body
        self.status_code = status


class FakeHTTP:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        return self.response


URL = "https://t.vndb.org/cv/12/34567.jpg"


# -- covers ---------------------------------------------------------------
def test_a_cover_is_downloaded_once_and_then_found_on_disk():
    http = FakeHTTP(FakeResponse(jpeg_bytes()))
    path = covers.download(URL, session=http)
    assert path is not None and path.is_file()
    assert covers.cached(URL) == path
    assert covers.download(URL, session=http) == path
    assert http.calls == 1  # the second time it never went out


def test_an_error_page_served_with_200_is_not_kept_as_a_cover():
    http = FakeHTTP(FakeResponse(b"<html>rate limited</html>"))
    assert covers.download(URL, session=http) is None
    assert covers.cached(URL) is None


def test_a_failed_download_is_quiet():
    assert covers.download(URL, session=FakeHTTP(FakeResponse(b"", status=404))) is None

    class Broken:
        def get(self, *a, **k):
            raise OSError("no network")

    assert covers.download(URL, session=Broken()) is None
    assert covers.download(None) is None
    assert covers.download("file:///etc/passwd") is None  # only http(s)


def test_a_rematched_game_gets_its_new_cover_not_the_old_one():
    """Named after the URL, so a new VNDB entry is a new file."""
    assert covers.cover_path(URL) != covers.cover_path("https://t.vndb.org/cv/99/1.jpg")


def test_every_tile_is_exactly_the_requested_size():
    """Whatever the source shape, the grid gets uniform boxes."""
    wide = covers.cover_dir() / "wide.png"
    wide.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 200), "red").save(wide)
    assert covers.tile(wide, (150, 213)).size == (150, 213)
    assert covers.tile(None, (150, 213), title="No cover at all").size == (150, 213)


def test_a_broken_image_file_becomes_a_title_card_not_a_crash():
    broken = covers.cover_dir() / "broken.jpg"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"\xff\xd8\xff not really a jpeg")
    assert covers.tile(broken, (150, 213), title="X").size == (150, 213)


# -- the gallery ----------------------------------------------------------
def test_a_gallery_is_per_game_and_newest_first():
    folder = screenshots.gallery_dir("woh")
    folder.mkdir(parents=True)
    old, new = folder / "a.png", folder / "b.png"
    Image.new("RGB", (8, 8)).save(old)
    Image.new("RGB", (8, 8)).save(new)
    os.utime(old, (time.time() - 100,) * 2)
    (folder / "notes.txt").write_text("not a picture")
    assert screenshots.shots("woh") == [new, old]
    assert screenshots.shots("some-other-game") == []


def test_two_shots_in_one_second_do_not_overwrite_each_other(tmp_path):
    when = time.mktime((2026, 10, 15, 21, 30, 5, 0, 0, -1))
    first = screenshots.next_name(tmp_path, when)
    assert first.name == "2026-10-15 21-30-05.png"
    first.write_bytes(b"x")
    second = screenshots.next_name(tmp_path, when)
    assert second.name == "2026-10-15 21-30-05-2.png"


def test_the_game_window_is_the_biggest_one_not_a_splash_or_a_tooltip():
    windows = [
        Window(1, 10, "Launcher", (0, 0, 400, 300)),
        Window(2, 10, "Ryujinx - MAMIYA", (0, 0, 1920, 1080)),
        Window(3, 10, "", (0, 0, 40, 20)),  # a tooltip
    ]
    assert pick_game_window(windows).hwnd == 2
    assert pick_game_window([Window(3, 10, "", (0, 0, 40, 20))]) is None
    assert pick_game_window([]) is None


def test_capture_saves_the_game_window_into_its_gallery():
    grabbed = []

    def grab(rect):
        grabbed.append(rect)
        return Image.new("RGB", (rect[2] - rect[0], rect[3] - rect[1]), "teal")

    find = lambda pids: [Window(7, 4242, "Game", (100, 50, 1380, 770))]  # noqa: E731
    saved = screenshots.capture("woh", {4242}, find=find, grab=grab)
    assert saved is not None and saved.parent == screenshots.gallery_dir("woh")
    assert grabbed == [(100, 50, 1380, 770)]  # exactly the game's client area
    with Image.open(saved) as picture:
        assert picture.size == (1280, 720)


def test_no_window_on_screen_means_nothing_saved_and_no_crash():
    assert screenshots.capture("woh", {1}, find=lambda pids: [], grab=None) is None
    assert screenshots.shots("woh") == []


def test_a_grab_that_fails_is_reported_as_nothing_saved():
    def grab(rect):
        raise OSError("screen locked")

    find = lambda pids: [Window(7, 1, "Game", (0, 0, 800, 600))]  # noqa: E731
    assert screenshots.capture("woh", {1}, find=find, grab=grab) is None


# -- the hotkey -----------------------------------------------------------
def test_hotkeys_parse_the_way_people_write_them():
    assert parse_hotkey("F8") == (0, 0x77)
    assert parse_hotkey("f1") == (0, 0x70)
    mods, vk = parse_hotkey("Ctrl+Shift+S")
    assert vk == ord("S") and mods == screenshots.MOD_CONTROL | screenshots.MOD_SHIFT
    assert parse_hotkey("Alt-PrintScreen") == (screenshots.MOD_ALT, 0x2C)


def test_f12_is_refused_because_windows_reserves_it():
    with pytest.raises(HotkeyError, match="reserved"):
        parse_hotkey("F12")


def test_a_bare_letter_is_refused_or_nobody_could_type_it():
    with pytest.raises(HotkeyError, match="typing"):
        parse_hotkey("S")


def test_nonsense_is_refused_with_a_reason():
    for text in ("", "Hyper+F8", "F99", "Ctrl+Banana"):
        with pytest.raises(HotkeyError):
            parse_hotkey(text)


# -- the session's side ---------------------------------------------------
def test_a_bad_hotkey_in_the_config_warns_instead_of_breaking_the_session():
    from vnpresence.config import AppConfig
    from vnpresence.models import GameProfile
    from vnpresence.session import GameSession

    events = []
    session = GameSession(GameProfile(id="x", title="X"),
                          AppConfig(client_id="1", screenshot_hotkey="F12"),
                          presence=object())
    assert session._start_screenshot_hotkey(lambda k, m: events.append((k, m))) is None
    assert events and events[0][0] == "warning" and "F12" in events[0][1]


def test_an_empty_hotkey_turns_screenshots_off_silently():
    from vnpresence.config import AppConfig
    from vnpresence.models import GameProfile
    from vnpresence.session import GameSession

    events = []
    session = GameSession(GameProfile(id="x", title="X"),
                          AppConfig(client_id="1", screenshot_hotkey=""), presence=object())
    assert session._start_screenshot_hotkey(lambda k, m: events.append((k, m))) is None
    assert events == []
