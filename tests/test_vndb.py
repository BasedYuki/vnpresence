import json

import pytest

from vnpresence.vndb import VNDBClient, VNDBError, clean_description, is_nsfw, parse_vn

SAMPLE = {
    "id": "v2002",
    "title": "Steins;Gate",
    "alttitle": "シュタインズ・ゲート",
    "image": {"url": "https://t.vndb.org/cv/33/33033.jpg", "sexual": 0.2, "violence": 0.1},
    "description": "A [i]tale[/i] about [url=/v2002]time travel[/url].",
    "released": "2009-10-15",
    "languages": ["ja", "en"],
    "platforms": ["win"],
    "length": 4,
    "rating": 89.0,
    "tags": [],
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(json)
        return self.response


def test_parse_maps_every_field():
    meta = parse_vn(SAMPLE)
    assert meta.title == "Steins;Gate"
    assert meta.image_url.endswith("33033.jpg")
    assert meta.length == "Long (30-50h)"
    assert meta.rating == 8.9
    assert meta.url == "https://vndb.org/v2002"
    assert meta.nsfw is False
    assert meta.description == "A tale about time travel."


def test_nsfw_from_cover_rating():
    assert is_nsfw({"image": {"sexual": 1.4}}) is True
    assert is_nsfw({"image": {"sexual": 0.4}}) is False


def test_nsfw_from_content_tags():
    item = {"tags": [{"name": "Sexual Content", "category": "cont", "rating": 2.4}]}
    assert is_nsfw(item) is True


def test_non_content_tags_do_not_trigger_nsfw():
    item = {"tags": [{"name": "Sexual Content", "category": "tech", "rating": 2.4}]}
    assert is_nsfw(item) is False


def test_description_is_trimmed():
    assert len(clean_description("x " * 500)) <= 300


def test_get_uses_cache_on_second_call(tmp_path):
    session = FakeSession(FakeResponse({"results": [SAMPLE]}))
    client = VNDBClient(cache_path=tmp_path, session=session)
    first = client.get("v2002")
    second = client.get("v2002")
    assert first.title == second.title == "Steins;Gate"
    assert len(session.calls) == 1  # the second call came from disk


def test_rate_limit_raises_a_clear_error(tmp_path):
    client = VNDBClient(cache_path=tmp_path, session=FakeSession(FakeResponse({}, 429)))
    with pytest.raises(VNDBError, match="rate limit"):
        client.get("v2002")


def test_search_sends_search_filter(tmp_path):
    session = FakeSession(FakeResponse({"results": [SAMPLE]}))
    VNDBClient(cache_path=tmp_path, session=session).search("steins")
    assert session.calls[0]["filters"] == ["search", "=", "steins"]
