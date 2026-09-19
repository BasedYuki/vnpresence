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

    simpledialog = types.ModuleType("tkinter.simpledialog")
    simpledialog.askstring = lambda *a, **k: None

    tk.ttk = ttk
    tk.filedialog = filedialog
    tk.messagebox = messagebox
    tk.simpledialog = simpledialog
    sys.modules.update(
        {
            "tkinter": tk,
            "tkinter.ttk": ttk,
            "tkinter.filedialog": filedialog,
            "tkinter.messagebox": messagebox,
            "tkinter.simpledialog": simpledialog,
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


class Selection:
    """Stands in for the Treeview: it is only ever asked what is selected."""

    def __init__(self, *ids):
        self.ids = ids

    def selection(self):
        return self.ids


@pytest.fixture()
def app(tmp_path):
    """An App instance with only the attributes these actions touch."""
    instance = object.__new__(gui.App)
    instance.library = Library(tmp_path / "games")
    instance.library.save(GameProfile(id="x", title="X", path="/x.exe"))
    instance.tree = Selection("x")
    instance.watch_var = Box(False)
    instance.startup_var = Box(False)
    instance.note_var = Box("")
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


def test_add_game_names_the_game_after_its_folder(app, monkeypatch):
    """The engine's exe name must never become the game's title."""
    chosen = r"K:\Games\Rewrite\SiglusEngine_SteamEN.exe"
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **k: chosen)
    searched = []

    def fake_lookup(term):
        searched.append(term)
        return None, None  # VNDB offline / no match

    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: None)
    app._lookup = fake_lookup
    app.config_data = gui.AppConfig(client_id="1")
    app.refresh = lambda: None
    app.add_game()

    assert searched[0] == "Rewrite"  # searched by folder, not by SiglusEngine
    saved = app.library.load_all()
    assert any(p.title == "Rewrite" for p in saved)


def test_add_game_accepts_a_typed_name_when_vndb_finds_nothing(app, monkeypatch):
    monkeypatch.setattr(
        gui.filedialog, "askopenfilename", lambda **k: r"D:\VN\folder\game.exe"
    )
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: "Clannad")
    app._lookup = lambda term: (None, None)
    app.config_data = gui.AppConfig(client_id="1")
    app.refresh = lambda: None
    app.add_game()
    assert any(p.title == "Clannad" for p in app.library.load_all())


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


def test_default_privacy_is_full_out_of_the_box():
    assert gui.AppConfig().default_privacy == "full"


def test_changing_the_default_privacy_is_saved(app, tmp_path, monkeypatch):
    saved = {}
    app.config_data = gui.AppConfig(client_id="1")
    app.default_privacy_var = Box("auto")
    def remember(self, path=None):
        saved["mode"] = self.default_privacy

    monkeypatch.setattr(gui.AppConfig, "save", remember)
    app.apply_default_privacy()
    assert saved["mode"] == "auto"
    assert "auto" in app.status.get()


def test_added_games_use_the_configured_default(app, monkeypatch):
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **k: r"D:\VN\Clannad\game.exe")
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: None)
    app._lookup = lambda term: (None, None)
    app.config_data = gui.AppConfig(client_id="1", default_privacy="auto")
    app.refresh = lambda: None
    app.add_game()
    added = [p for p in app.library.load_all() if p.title == "Clannad"][0]
    assert added.privacy.value == "auto"


# -- the route box and the VNDB link ---------------------------------------
def test_the_route_box_writes_a_note_the_session_can_read(app):
    from vnpresence import notes

    app.note_var = Box(" Ayamine route ")
    app.apply_note()
    assert notes.read_note("x") == "Ayamine route"
    assert "Ayamine route" in app.status.get()


def test_selecting_a_game_shows_its_existing_note(app):
    from vnpresence import notes

    notes.write_note("x", "Chapter 3")
    app.note_var = Box("")
    app.load_note()
    assert app.note_var.get() == "Chapter 3"


def test_clearing_the_box_removes_the_note(app):
    from vnpresence import notes

    notes.write_note("x", "Chapter 3")
    app.note_var = Box("Chapter 3")
    app.clear_note()
    assert notes.read_note("x") is None


def test_a_pasted_vndb_link_skips_the_name_search(app, monkeypatch):
    """The whole point: a sequel shares its parent's name, a link does not."""
    app.config_data = gui.AppConfig(client_id="1")
    searched, fetched = [], []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def search(self, term, limit=1):
            searched.append(term)
            return []

        def get(self, vndb_id):
            fetched.append(vndb_id)
            return gui_metadata()

    monkeypatch.setattr(gui, "VNDBClient", FakeClient)
    metadata, vndb_id = app._lookup("https://vndb.org/v2400")
    assert fetched == ["v2400"] and searched == []
    assert vndb_id == "v2400"
    assert metadata.title == "Rewrite+"


def test_a_plain_name_still_goes_through_the_search(app, monkeypatch):
    app.config_data = gui.AppConfig(client_id="1")
    searched = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def search(self, term, limit=1):
            searched.append(term)
            return [gui_metadata()]

        def get(self, vndb_id):  # pragma: no cover - must not be reached
            raise AssertionError("a name is not a link")

    monkeypatch.setattr(gui, "VNDBClient", FakeClient)
    app._lookup("Rewrite")
    assert searched == ["Rewrite"]


def test_relinking_repoints_an_already_added_game(app, monkeypatch):
    app.config_data = gui.AppConfig(client_id="1")
    app.refresh = lambda: None
    app.selected_profile = lambda: app.library.get("x")
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: "https://vndb.org/v2400")
    app._lookup = lambda term: (gui_metadata(), "v2400")
    app.relink_selected()
    saved = app.library.get("x")
    assert saved.vndb_id == "v2400"
    assert saved.title == "Rewrite+"


def test_a_bad_link_changes_nothing(app, monkeypatch):
    app.config_data = gui.AppConfig(client_id="1")
    app.refresh = lambda: None
    app.selected_profile = lambda: app.library.get("x")
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: "https://vndb.org/v999999")
    app._lookup = lambda term: (None, None)
    app.relink_selected()
    saved = app.library.get("x")
    assert saved.vndb_id is None
    assert saved.title == "X"


def gui_metadata():
    from vnpresence.models import GameMetadata

    return GameMetadata(title="Rewrite+", url="https://vndb.org/v2400", source="vndb")
