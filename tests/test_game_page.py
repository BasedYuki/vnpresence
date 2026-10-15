"""The game page's numbers, chart, VNDB list, launch modes and screenshot tools."""

from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from vnpresence import chart, shell, stats, vndb_list
from vnpresence.config import AppConfig
from vnpresence.launcher import LaunchError, build_command, launch_mode
from vnpresence.models import GameProfile
from vnpresence.playtime import Entry, Playtime
from vnpresence.vndb import parse_vn

TODAY = dt.date(2026, 10, 15)  # a Thursday


def entry(**days) -> Entry:
    return Entry(seconds=sum(days.values()), days={k.replace("_", "-")[1:]: v
                                                   for k, v in days.items()})


# -- the per-day history ----------------------------------------------------
def test_time_is_written_against_the_day_it_was_read(monkeypatch, tmp_path):
    clock = Playtime(tmp_path / "p.yaml")
    monkeypatch.setattr("vnpresence.playtime.time.strftime",
                        lambda fmt: "2026-10-15" if fmt == "%Y-%m-%d" else "2026-10-15T21:00:00")
    clock.add("g", 3600, new_session=True)
    clock.add("g", 600)
    assert clock.get("g").days == {"2026-10-15": 4200.0}
    assert clock.get("g").seconds == 4200.0


def test_idle_time_taken_back_comes_off_the_day_too(monkeypatch, tmp_path):
    clock = Playtime(tmp_path / "p.yaml")
    monkeypatch.setattr("vnpresence.playtime.time.strftime",
                        lambda fmt: "2026-10-15" if fmt == "%Y-%m-%d" else "x")
    clock.add("g", 900)
    clock.add("g", -1200)  # more than the day had: the day empties, never negative
    assert clock.get("g").days == {}


def test_a_hand_set_total_does_not_invent_history(tmp_path):
    clock = Playtime(tmp_path / "p.yaml")
    clock.set("g", 50 * 3600)
    assert clock.get("g").days == {}
    assert stats.history_since(clock.get("g")) is None


def test_old_history_files_still_load(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("g:\n  seconds: 100\n  sessions: 2\n  last_played: ''\n")
    assert Playtime(path).get("g").days == {}


def test_junk_in_the_day_list_is_dropped_not_fatal():
    loaded = Entry.from_dict({"seconds": 1, "days": {"2026-10-15": 60, "yesterday": 5,
                                                     "2026-10-14": "lots", "2026-10-13": -4}})
    assert loaded.days == {"2026-10-15": 60.0}


# -- stats ------------------------------------------------------------------
def test_daily_has_every_day_even_the_empty_ones():
    points = stats.daily(entry(_2026_10_15=600, _2026_10_13=1200), 5, TODAY)
    assert [d.isoformat() for d, _ in points] == [
        "2026-10-11", "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"]
    assert [s for _, s in points] == [0, 0, 1200, 0, 600]


def test_weekly_groups_by_monday():
    e = entry(_2026_10_12=600, _2026_10_15=600, _2026_10_05=60, _2026_06_01=9999)
    weeks = stats.weekly(e, 3, TODAY)
    assert [(d.isoformat(), s) for d, s in weeks] == [
        ("2026-09-28", 0.0), ("2026-10-05", 60.0), ("2026-10-12", 1200.0)]


def test_last_seven_days_includes_today_and_not_day_eight():
    e = entry(_2026_10_15=60, _2026_10_09=60, _2026_10_08=6000)
    assert stats.last_days(e, 7, TODAY) == 120


def test_clock_format_pads_minutes_like_the_reference():
    assert stats.format_clock(32 * 3600 + 9 * 60) == "32h 09m"
    assert stats.format_clock(540) == "9m"
    assert stats.format_clock(None) == "0m"


def test_axis_steps_are_times_a_person_would_say():
    assert stats.axis_ticks(100 * 60) == [0, 1800, 3600, 5400, 7200]
    assert stats.axis_ticks(6 * 3600)[-1] >= 6 * 3600
    assert len(stats.axis_ticks(40 * 3600)) <= 5
    assert stats.format_axis(5400) == "1h 30m"


def test_progress_against_vndb():
    progress = stats.progress(32 * 3600, 40 * 60)
    assert progress.percent == 80
    assert progress.describe() == "80% \u00b7 average ~40h"
    assert stats.progress(60 * 3600, 40 * 60).bar == 1.0  # past the average: a full bar
    assert stats.progress(3600, None) is None
    assert stats.progress(3600, 0) is None


def test_vndb_average_length_is_read_from_the_api():
    item = {"id": "v3770", "title": "Aiyoku no Eustia", "length_minutes": 2460}
    assert parse_vn(item).length_minutes == 2460
    assert parse_vn({"id": "v1", "title": "x", "length_minutes": None}).length_minutes is None


def test_an_old_cache_still_draws_a_cover(tmp_path):
    from vnpresence.vndb import VNDBClient

    client = VNDBClient(cache_path=tmp_path)
    (tmp_path / "vndb").mkdir()
    (tmp_path / "vndb" / "v1.json").write_text(json.dumps({"title": "Old", "_schema": 4}))
    assert client.peek("v1").title == "Old"
    assert client._read_cache("v1") is None  # but get() fetches the new fields


# -- chart layout -----------------------------------------------------------
def test_bars_sit_on_the_baseline_and_the_tallest_is_labelled():
    points = stats.daily(entry(_2026_10_15=3600, _2026_10_14=1800), 30, TODAY)
    plan = chart.layout(points, 600, 230)
    assert len(plan.bars) == 2
    assert all(bar.y1 == plan.bars[0].y1 for bar in plan.bars)
    assert plan.peak.seconds == 3600
    assert plan.bars[-1].x1 <= 600  # inside the canvas
    assert 4 <= len(plan.labels) <= 8


def test_an_empty_chart_has_an_axis_and_no_bars():
    plan = chart.layout(stats.daily(None, 30, TODAY), 600, 230)
    assert plan.bars == [] and plan.peak is None and plan.gridlines


# -- your VNDB list ---------------------------------------------------------
class Reply:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.content = b"" if body is None else json.dumps(body).encode()
        self._body = body

    def json(self):
        return self._body


class FakeVNDB:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, method, url, headers=None, data=None, timeout=None):
        self.calls.append((method, url, headers, json.loads(data) if data else None))
        return self.replies.pop(0)


TOKEN = "abcd-efghi-jklmn-opqr-stuvw-xyz12-3456"


def account(write=True):
    return vndb_list.Account(TOKEN, "u42", "yuki", write)


def test_a_token_is_checked_and_its_owner_remembered():
    http = FakeVNDB(Reply(body={"id": "u42", "username": "yuki",
                                "permissions": ["listread", "listwrite"]}))
    got = vndb_list.connect(TOKEN, session=http)
    assert (got.user, got.username, got.can_write) == ("u42", "yuki", True)
    method, url, headers, _ = http.calls[0]
    assert (method, url) == ("GET", "https://api.vndb.org/kana/authinfo")
    assert headers["Authorization"] == f"Token {TOKEN}"


def test_garbage_is_refused_before_bothering_vndb():
    with pytest.raises(vndb_list.VNDBListError, match="token"):
        vndb_list.connect("my password", session=FakeVNDB())


def test_a_read_only_token_says_so():
    http = FakeVNDB(Reply(body={"id": "u42", "username": "y", "permissions": ["listread"]}))
    assert vndb_list.connect(TOKEN, session=http).can_write is False
    with pytest.raises(vndb_list.VNDBListError, match="Write to my list"):
        vndb_list.set_status(account(write=False), "v3770", vndb_list.FINISHED)


def test_a_deleted_token_is_explained():
    with pytest.raises(vndb_list.VNDBListError, match="did not accept"):
        vndb_list.connect(TOKEN, session=FakeVNDB(Reply(401)))


def test_the_list_entry_is_read_with_status_and_vote():
    http = FakeVNDB(Reply(body={"results": [{"id": "v3770", "vote": 90,
                                             "labels": [{"id": 2}, {"id": 7}]}]}))
    got = vndb_list.get_entry(account(), "v3770", session=http)
    assert (got.on_list, got.status, got.vote, got.rating) == (True, 2, 90, 9)
    _, url, _, body = http.calls[0]
    assert url.endswith("/ulist") and body["user"] == "u42"
    assert body["filters"] == ["id", "=", "v3770"]


def test_not_on_the_list_is_not_an_error():
    got = vndb_list.get_entry(account(), "v1", session=FakeVNDB(Reply(body={"results": []})))
    assert got.on_list is False and got.status is None


def test_setting_a_status_unsets_the_other_three():
    http = FakeVNDB(Reply(204))
    vndb_list.set_status(account(), "v3770", vndb_list.FINISHED, session=http)
    method, url, _, body = http.calls[0]
    assert (method, url) == ("PATCH", "https://api.vndb.org/kana/ulist/v3770")
    assert body == {"labels_set": [2], "labels_unset": [1, 3, 4]}


def test_clearing_the_status_unsets_all_four():
    assert vndb_list.status_change(None) == {"labels_unset": [1, 2, 3, 4]}


def test_ratings_become_vndb_votes():
    http = FakeVNDB(Reply(204), Reply(204))
    vndb_list.set_rating(account(), "v3770", 9, session=http)
    vndb_list.set_rating(account(), "v3770", None, session=http)
    assert [c[3] for c in http.calls] == [{"vote": 90}, {"vote": None}]
    with pytest.raises(ValueError):
        vndb_list.vote_for(11)


def test_the_token_lives_in_its_own_file_and_can_be_forgotten():
    vndb_list.save_account(account())
    assert vndb_list.load_account().token == TOKEN
    assert TOKEN not in (AppConfig().save().read_text())
    vndb_list.forget_account()
    assert vndb_list.load_account() is None
    vndb_list.forget_account()  # twice is fine


# -- launch with --------------------------------------------------------------
def profile(mode="normal"):
    return GameProfile(id="g", title="Game", path="C:/g/game.exe", args=["-x"],
                       launch_with=mode)


def test_normal_is_just_the_game():
    assert build_command(profile(), Path("C:/g/game.exe")) == [str(Path("C:/g/game.exe")), "-x"]


def test_locale_emulator_is_handed_the_game(tmp_path):
    le = tmp_path / "LEProc.exe"
    le.write_text("")
    config = AppConfig(locale_emulator_path=str(le))
    command = build_command(profile("locale-emulator"), Path("C:/g/game.exe"), config)
    assert command[:2] == [str(le), str(Path("C:/g/game.exe"))]


def test_ntlea_gets_the_japanese_settings(tmp_path):
    nt = tmp_path / "ntleas.exe"
    nt.write_text("")
    command = build_command(profile("ntlea"), Path("C:/g/game.exe"),
                            AppConfig(ntlea_path=str(nt)))
    assert command == [str(nt), str(Path("C:/g/game.exe")), "C932", "L1041", "FMS PGothic", "P4"]


def test_a_wrapper_nobody_located_is_a_clear_error(tmp_path):
    with pytest.raises(LaunchError, match="has not been set"):
        build_command(profile("ntlea"), Path("C:/g/game.exe"), AppConfig())
    with pytest.raises(LaunchError, match="not found"):
        build_command(profile("ntlea"), Path("C:/g/game.exe"),
                      AppConfig(ntlea_path=str(tmp_path / "gone.exe")))


def test_an_unknown_mode_falls_back_to_normal():
    assert launch_mode(profile("magic")) == "normal"
    assert GameProfile.from_dict({"title": "x"}).launch_with == "normal"
    assert "launch_with" not in GameProfile(id="x", title="x").to_dict()  # stays minimal


# -- screenshot tools -----------------------------------------------------------
def test_copy_puts_a_real_dib_and_png_together(tmp_path):
    path = tmp_path / "shot.png"
    Image.new("RGB", (32, 18), (200, 60, 60)).save(path)
    dib, png = shell.image_formats(path)
    assert int.from_bytes(dib[:4], "little") == 40  # BITMAPINFOHEADER, no file header
    assert int.from_bytes(dib[4:8], "little", signed=True) == 32
    with Image.open(io.BytesIO(png)) as again:
        assert again.size == (32, 18)


def test_winrt_generic_ids_follow_the_published_algorithm():
    # IIterable<String>, a value every WinRT projection agrees on.
    iid = shell.pinterface_iid("pinterface({faa585ea-6214-4217-afda-7f46de5869b3};string)")
    assert str(iid) == "e2fcc7c1-3bfc-5a0b-b2b0-72e769d1cb7e"


def test_share_and_copy_refuse_politely_off_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(shell.sys, "platform", "linux")
    path = tmp_path / "shot.png"
    Image.new("RGB", (4, 4)).save(path)
    with pytest.raises(shell.ShareError):
        shell.share_image(path, 0)
    with pytest.raises(shell.ShareError):
        shell.copy_image(path)
