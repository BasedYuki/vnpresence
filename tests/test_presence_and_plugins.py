from vnpresence.models import GameProfile, PresenceState
from vnpresence.plugins import PluginRegistry, build_registry
from vnpresence.presence import DiscordPresence
from vnpresence.providers.base import StateProvider


class FakeRPC:
    def __init__(self, client_id):
        self.client_id = client_id
        self.updates = []
        self.cleared = 0
        self.fail_next = False

    def connect(self):
        return None

    def update(self, **kwargs):
        if self.fail_next:
            self.fail_next = False
            raise OSError("pipe closed")
        self.updates.append(kwargs)

    def clear(self):
        self.cleared += 1

    def close(self):
        return None


def make_presence():
    created = {}

    def backend(client_id):
        rpc = FakeRPC(client_id)
        created["rpc"] = rpc
        return rpc

    return DiscordPresence("123", backend=backend), created


def test_first_update_is_sent():
    presence, created = make_presence()
    assert presence.update({"details": "A"}, force=True) is True
    assert created["rpc"].updates == [{"details": "A"}]


def test_identical_payload_is_not_resent():
    presence, created = make_presence()
    presence.update({"details": "A"}, force=True)
    assert presence.update({"details": "A"}) is False
    assert len(created["rpc"].updates) == 1


def test_rate_limit_blocks_rapid_changes():
    presence, _ = make_presence()
    presence.update({"details": "A"}, force=True)
    assert presence.update({"details": "B"}) is False  # under 15 seconds


def test_broken_pipe_disconnects_instead_of_raising():
    presence, created = make_presence()
    presence.update({"details": "A"}, force=True)
    created["rpc"].fail_next = True
    assert presence.update({"details": "B"}, force=True) is False
    assert presence.connected is False


def test_builtin_registry_has_providers_and_formatter():
    info = build_registry().describe()
    assert info["metadata_providers"] == ["vndb", "local"]
    assert info["formatters"] == ["default"]


def test_state_plugin_is_instantiated_with_options():
    class Fake(StateProvider):
        name = "fake"

        def __init__(self, marker="default"):
            self.marker = marker

        def poll(self):
            return PresenceState(status_text=self.marker)

    registry = PluginRegistry()
    registry.add_state_provider(Fake)
    profile = GameProfile(id="x", title="X", plugin="fake", plugin_options={"marker": "ch1"})
    provider = registry.state_provider_for(profile)
    assert provider.poll().status_text == "ch1"


def test_missing_plugin_is_ignored():
    registry = PluginRegistry()
    profile = GameProfile(id="x", title="X", plugin="nope")
    assert registry.state_provider_for(profile) is None


# -- the activity `name` field -------------------------------------------
def test_to_activity_shapes_the_payload_for_discord():
    from vnpresence.presence import to_activity

    activity = to_activity(
        {
            "name": "Steins;Gate",
            "details": "Reading",
            "state": "Long (30-50h)",
            "start": 1000,
            "large_image": "https://t.vndb.org/cv/sg.jpg",
            "large_text": "SG",
            "small_image": "icon",
            "small_text": "VN",
            "buttons": [{"label": "View on VNDB", "url": "https://vndb.org/v2002"}],
        }
    )
    assert activity["type"] == 0
    assert activity["name"] == "Steins;Gate"
    assert activity["timestamps"] == {"start": 1000}
    assert activity["assets"]["large_image"].endswith("sg.jpg")
    assert activity["assets"]["small_text"] == "VN"
    assert activity["buttons"][0]["label"] == "View on VNDB"


def test_to_activity_omits_empty_sections():
    from vnpresence.presence import to_activity

    activity = to_activity({"details": "Reading"})
    assert "assets" not in activity
    assert "timestamps" not in activity
    assert "buttons" not in activity


class RawRPC(FakeRPC):
    """A client that records raw frames, like pypresence's sync Presence."""

    def __init__(self, client_id):
        super().__init__(client_id)
        self.frames = []
        self.loop = self
        self.raw_fails = False

    def send_data(self, op, payload):
        if self.raw_fails:
            raise OSError("pipe closed")
        self.frames.append(payload)

    def read_output(self):
        return {"evt": None}

    def run_until_complete(self, value):  # stands in for the asyncio loop
        return value


def make_raw_presence():
    created = {}

    def backend(client_id):
        created["rpc"] = RawRPC(client_id)
        return created["rpc"]

    return DiscordPresence("123", backend=backend), created


def test_a_name_is_sent_through_the_raw_protocol():
    presence, created = make_raw_presence()
    presence.update({"name": "Steins;Gate", "details": "Reading"}, force=True)
    frame = created["rpc"].frames[0]
    assert frame["cmd"] == "SET_ACTIVITY"
    assert frame["args"]["activity"]["name"] == "Steins;Gate"
    assert created["rpc"].updates == []  # the library call was not used


def test_payloads_without_a_name_use_the_library_call():
    presence, created = make_raw_presence()
    presence.update({"details": "Steins;Gate"}, force=True)
    assert created["rpc"].updates == [{"details": "Steins;Gate"}]
    assert created["rpc"].frames == []


def test_a_broken_raw_send_falls_back_to_the_library():
    presence, created = make_raw_presence()
    presence.connect()  # the fake client only exists once connected
    created["rpc"].raw_fails = True
    assert presence.update({"name": "Steins;Gate", "details": "Reading"}, force=True) is True
    # It still got published, just without the custom name.
    assert created["rpc"].updates == [{"details": "Reading"}]
