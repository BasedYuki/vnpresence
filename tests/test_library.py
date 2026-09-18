import pytest
import yaml

from vnpresence.library import Library
from vnpresence.models import GameProfile, PrivacyMode, normalise_vndb_id, slugify


@pytest.fixture()
def library(tmp_path):
    return Library(tmp_path / "games")


def test_roundtrip_keeps_values(library):
    profile = GameProfile(
        id="steins-gate",
        title="Steins;Gate",
        path="/games/sg/sg.exe",
        vndb_id="v2002",
        process_names=["sg_main.exe"],
        privacy=PrivacyMode.FULL,
    )
    library.save(profile)
    loaded = library.get("steins-gate")
    assert loaded.title == "Steins;Gate"
    assert loaded.vndb_id == "v2002"
    assert loaded.process_names == ["sg_main.exe"]
    assert loaded.privacy is PrivacyMode.FULL


def test_saved_yaml_stays_minimal(library):
    library.save(GameProfile(id="a", title="A", path="/a.exe"))
    data = yaml.safe_load((library.directory / "a.yaml").read_text())
    assert set(data) == {"title", "path"}  # defaults are not written out


def test_unique_id_avoids_collisions(library):
    library.save(GameProfile(id="clannad", title="Clannad"))
    assert library.unique_id("Clannad") == "clannad-2"


def test_find_matches_by_title_substring(library):
    library.save(GameProfile(id="clannad", title="Clannad"))
    assert library.find("clan").id == "clannad"
    assert library.find("nothing here") is None


def test_broken_profile_is_skipped_not_fatal(library, caplog):
    library.directory.mkdir(parents=True)
    (library.directory / "bad.yaml").write_text("title: Good\nnope: 1\n")
    (library.directory / "good.yaml").write_text("title: Good\n")
    assert [p.id for p in library.load_all()] == ["good"]


def test_profile_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown profile key"):
        GameProfile.from_dict({"title": "X", "typo_here": 1})


def test_profile_requires_title():
    with pytest.raises(ValueError, match="title"):
        GameProfile.from_dict({"path": "/x.exe"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("v17", "v17"), ("17", "v17"), ("https://vndb.org/v17", "v17")],
)
def test_normalise_vndb_id(raw, expected):
    assert normalise_vndb_id(raw) == expected


def test_slugify_handles_punctuation_and_unicode():
    assert slugify("Steins;Gate 0") == "steinsgate-0"
    assert slugify("シュタインズ・ゲート") == "game"
