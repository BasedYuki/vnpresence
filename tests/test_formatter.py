from vnpresence.config import AppConfig
from vnpresence.formatter import DefaultFormatter, clamp, effective_privacy
from vnpresence.models import GameMetadata, GameProfile, PresenceState, PrivacyMode

CONFIG = AppConfig(client_id="123", small_image="https://example.com/icon.png")


def profile(**kwargs):
    base = {"id": "sg", "title": "Steins;Gate"}
    base.update(kwargs)
    return GameProfile(**base)


def metadata(**kwargs):
    base = {
        "title": "Steins;Gate",
        "image_url": "https://t.vndb.org/cv/sg.jpg",
        "url": "https://vndb.org/v2002",
        "length": "Long (30-50h)",
        "released": "2009-10-15",
        "source": "vndb",
    }
    base.update(kwargs)
    return GameMetadata(**base)


def build(prof, meta, state=None, config=CONFIG):
    return DefaultFormatter().format(
        prof, meta, state or PresenceState(), {"config": config, "start": 1000}
    )


def test_full_payload_has_every_requested_field():
    payload = build(profile(), metadata())
    # The header itself is the game: "Playing Steins;Gate".
    assert payload["name"] == "Steins;Gate"
    assert payload["details"] == "Reading"
    assert payload["state"] == "Long (30-50h) \u2022 2009"
    assert payload["large_image"] == "https://t.vndb.org/cv/sg.jpg"
    assert payload["small_image"] == "https://example.com/icon.png"
    assert payload["start"] == 1000
    assert payload["buttons"] == [{"label": "View on VNDB", "url": "https://vndb.org/v2002"}]


def test_nsfw_auto_hides_title_and_art():
    payload = build(profile(), metadata(nsfw=True))
    assert payload["details"] == CONFIG.private_title
    assert "large_image" not in payload
    assert "buttons" not in payload


def test_nsfw_auto_can_be_disabled():
    config = AppConfig(nsfw_auto_private=False)
    payload = build(profile(), metadata(nsfw=True), config=config)
    assert payload["name"] == "Steins;Gate"


def test_privacy_off_publishes_nothing():
    assert build(profile(privacy=PrivacyMode.OFF), metadata()) is None


def test_explicit_full_overrides_nsfw():
    payload = build(profile(privacy=PrivacyMode.FULL), metadata(nsfw=True))
    assert payload["name"] == "Steins;Gate"


def test_state_provider_overrides_status_line():
    payload = build(profile(), metadata(), PresenceState(status_text="Chapter 3 - Butterfly"))
    assert payload["details"] == "Chapter 3 - Butterfly"


def test_legacy_layout_keeps_the_title_on_the_second_line():
    """Old clients ignore `name`, so the title must stay in `details` there."""
    config = AppConfig(client_id="1", use_activity_name=False)
    payload = build(profile(), metadata(), config=config)
    assert "name" not in payload
    assert payload["details"] == "Steins;Gate"
    assert payload["state"] == "Reading"


def test_private_mode_never_puts_the_title_in_the_header():
    payload = build(profile(privacy=PrivacyMode.PRIVATE), metadata())
    assert "name" not in payload
    assert payload["details"] == CONFIG.private_title
    assert "Steins;Gate" not in str(payload)


def test_a_game_without_metadata_still_gets_a_name():
    payload = build(profile(), None)
    assert payload["name"] == "Steins;Gate"
    assert payload.get("state") is None or payload["state"] == ""


def test_profile_image_override_wins():
    payload = build(profile(image_url="https://example.com/custom.png"), metadata())
    assert payload["large_image"] == "https://example.com/custom.png"


def test_buttons_can_be_disabled_per_game():
    payload = build(profile(show_buttons=False), metadata())
    assert "buttons" not in payload


def test_no_cover_means_no_small_image():
    payload = build(profile(), metadata(image_url=None))
    assert "large_image" not in payload
    assert "small_image" not in payload


def test_clamp_respects_discord_limits():
    assert len(clamp("x" * 300)) <= 128
    assert len(clamp("a")) >= 2
    assert clamp(None) is None
    assert clamp("  spaced   out  ") == "spaced out"


def test_effective_privacy_resolves_auto():
    assert effective_privacy(profile(), metadata(nsfw=True), CONFIG) is PrivacyMode.PRIVATE
    assert effective_privacy(profile(), metadata(), CONFIG) is PrivacyMode.FULL
    assert effective_privacy(profile(), None, CONFIG) is PrivacyMode.FULL
