"""The background watcher's pid record."""

import json
import os

import psutil
import pytest

from vnpresence import daemon


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VNPRESENCE_HOME", str(tmp_path))
    return tmp_path


def test_record_roundtrip():
    daemon.write_record()
    assert daemon.running_pid() == os.getpid()  # this test process is alive


def test_no_record_means_not_running():
    assert daemon.running_pid() is None


def test_dead_process_record_is_cleared(monkeypatch):
    daemon.write_record(pid=999999)

    def missing(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", missing)
    assert daemon.running_pid() is None
    assert not daemon.pid_file().exists()  # the stale record is gone


def test_recycled_pid_is_not_trusted(monkeypatch):
    daemon.pid_file().parent.mkdir(parents=True, exist_ok=True)
    daemon.pid_file().write_text(json.dumps({"pid": os.getpid(), "started": 1.0}))
    # The live process with this pid started at a completely different time.
    assert daemon.running_pid() is None


def test_corrupt_record_is_ignored():
    daemon.pid_file().parent.mkdir(parents=True, exist_ok=True)
    daemon.pid_file().write_text("not json at all")
    assert daemon.read_record() is None
    assert daemon.running_pid() is None


def test_stop_without_a_watcher_returns_none():
    assert daemon.stop_background() is None


def test_stop_terminates_and_clears(monkeypatch):
    daemon.write_record()
    real_start = psutil.Process(os.getpid()).create_time()
    calls = []

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            return real_start

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(psutil, "Process", FakeProcess)
    assert daemon.stop_background() == os.getpid()
    assert calls == ["terminate"]
    assert not daemon.pid_file().exists()


def test_self_command_uses_the_module_when_not_frozen():
    command = daemon._self_command(["watch"])
    assert command[1:] == ["-m", "vnpresence", "watch"]


def test_self_command_uses_the_exe_when_frozen(monkeypatch):
    monkeypatch.setattr(daemon.sys, "frozen", True, raising=False)
    monkeypatch.setattr(daemon.sys, "executable", r"C:\VNPresence.exe")
    assert daemon._self_command(["watch"]) == [r"C:\VNPresence.exe", "watch"]
