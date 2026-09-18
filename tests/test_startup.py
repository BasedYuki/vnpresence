"""Starting with Windows, tested against a fake registry."""

import pytest

from vnpresence import startup


class FakeRegistry:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read(self, name):
        return self.values.get(name)

    def write(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


def test_disabled_by_default():
    assert startup.is_enabled(FakeRegistry()) is False


def test_enable_then_disable():
    registry = FakeRegistry()
    command = startup.enable(registry)
    assert startup.is_enabled(registry) is True
    assert "watch" in command
    assert registry.values["VNPresence"] == command

    startup.disable(registry)
    assert startup.is_enabled(registry) is False


def test_enable_is_idempotent():
    registry = FakeRegistry()
    startup.enable(registry)
    startup.enable(registry)
    assert list(registry.values) == ["VNPresence"]


def test_disable_when_absent_is_harmless():
    registry = FakeRegistry()
    startup.disable(registry)  # must not raise
    assert registry.values == {}


def test_set_enabled_both_ways():
    registry = FakeRegistry()
    startup.set_enabled(True, registry)
    assert startup.is_enabled(registry)
    startup.set_enabled(False, registry)
    assert not startup.is_enabled(registry)


def test_command_is_quoted_for_paths_with_spaces(monkeypatch):
    monkeypatch.setattr(startup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(startup.sys, "executable", r"C:\Program Files\VNPresence.exe")
    command = startup.startup_command()
    assert command == r'"C:\Program Files\VNPresence.exe" watch'


def test_unsupported_platform_refuses_clearly():
    backend = startup.Unsupported()
    assert startup.is_enabled(backend) is False
    with pytest.raises(startup.StartupUnsupported, match="Windows"):
        startup.enable(backend)
    startup.disable(backend)  # turning it off is always fine
