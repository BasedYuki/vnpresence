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
