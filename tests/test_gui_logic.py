"""The GUI's two switches.

Tkinter cannot open a window on a build machine (and is missing entirely on
some Linux images), so the widgets are stubbed and the *logic* behind the
checkboxes is exercised directly. That is the part worth testing: whether
ticking a box starts the watcher, and what happens when it fails.
"""

from __future__ import annotations

import sys
import types

import pytest


def _install_tk_stubs() -> None:
    """Make `import tkinter` work headlessly, before gui.py is imported."""
    if "tkinter" in sys.modules:
        return
    tk = types.ModuleType("tkinter")

    class Widget:
        def __init__(self, *args, **kwargs):
            pass

        def pack(self, *args, **kwargs):
            return None

        def bind(self, *args, **kwargs):
            return None

        def state(self, *args, **kwargs):
            return ()

    class Variable(Widget):
        def __init__(self, value=None, **kwargs):
            self._value = value

        def get(self):
            return self._value

        def set(self, value):
            self._value = value

    tk.Tk = Widget
    tk.Frame = Widget
    tk.Label = Widget
    tk.StringVar = Variable
    tk.BooleanVar = Variable

    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Treeview", "Button", "Label", "Combobox", "Checkbutton"):
        setattr(ttk, name, Widget)

    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askopenfilename = lambda **kwargs: ""

    messagebox = types.ModuleType("tkinter.messagebox")
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    messagebox.askyesno = lambda *a, **k: True

    tk.ttk = ttk
    tk.filedialog = filedialog
    tk.messagebox = messagebox
    sys.modules.update(
        {
            "tkinter": tk,
            "tkinter.ttk": ttk,
            "tkinter.filedialog": filedialog,
            "tkinter.messagebox": messagebox,
        }
    )


_install_tk_stubs()

from vnpresence import gui  # noqa: E402
from vnpresence.library import Library  # noqa: E402
from vnpresence.models import GameProfile  # noqa: E402


class Box:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@pytest.fixture()
def app(tmp_path):
    """An App instance with only the attributes the switches touch."""
    instance = object.__new__(gui.App)
    instance.library = Library(tmp_path / "games")
    instance.library.save(GameProfile(id="x", title="X", path="/x.exe"))
    instance.watch_var = Box(False)
    instance.startup_var = Box(False)
    instance.status = Box("")
    return instance


def test_ticking_auto_detect_starts_the_watcher(app, monkeypatch):
    started = []
    monkeypatch.setattr(gui, "running_pid", lambda: None)
    monkeypatch.setattr(gui, "spawn_background", lambda: started.append(True) or 4242)
    app.watch_var.set(True)
    app.toggle_watch()
    assert started == [True]
    assert "4242" in app.status.get()


def test_unticking_stops_the_watcher(app, monkeypatch):
    monkeypatch.setattr(gui, "stop_background", lambda: 4242)
    app.watch_var.set(False)
    app.toggle_watch()
    assert "Stopped" in app.status.get()


def test_ticking_with_an_empty_library_is_refused(tmp_path, monkeypatch):
    instance = object.__new__(gui.App)
    instance.library = Library(tmp_path / "empty")
    instance.watch_var = Box(True)
    instance.status = Box("")
    monkeypatch.setattr(gui, "running_pid", lambda: None)
    monkeypatch.setattr(gui, "spawn_background", lambda: pytest.fail("must not start"))
    instance.toggle_watch()
    assert instance.watch_var.get() is False  # the box unticks itself


def test_a_failed_start_unticks_the_box(app, monkeypatch):
    def boom():
        raise OSError("no")

    monkeypatch.setattr(gui, "running_pid", lambda: None)
    monkeypatch.setattr(gui, "spawn_background", boom)
    app.watch_var.set(True)
    app.toggle_watch()
    assert app.watch_var.get() is False


def test_startup_switch_writes_the_setting(app, monkeypatch):
    calls = []
    monkeypatch.setattr(gui.startup, "set_enabled", lambda value: calls.append(value))
    app.startup_var.set(True)
    app.toggle_startup()
    assert calls == [True]
    assert "log in" in app.status.get()


def test_startup_switch_unticks_on_an_unsupported_platform(app, monkeypatch):
    def refuse(value):
        raise gui.startup.StartupUnsupported("Windows only")

    monkeypatch.setattr(gui.startup, "set_enabled", refuse)
    app.startup_var.set(True)
    app.toggle_startup()
    assert app.startup_var.get() is False
