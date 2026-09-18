"""A deliberately small Tkinter window: list, play, add, privacy.

Tkinter ships with Python, so the frozen .exe needs no extra GUI dependency.
The window is a thin shell over the same API the CLI uses - no logic lives here.
"""

from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import startup
from .config import AppConfig
from .daemon import running_pid, spawn_background, stop_background
from .launcher import LaunchError
from .library import Library
from .models import GameProfile, PrivacyMode
from .session import GameSession, format_duration
from .titles import guess_title
from .vndb import VNDBClient, VNDBError

log = logging.getLogger(__name__)

PRIVACY_HELP = {
    PrivacyMode.AUTO: "Auto - hide the title for 18+ games",
    PrivacyMode.FULL: "Full - show title, cover and button",
    PrivacyMode.PRIVATE: "Private - neutral activity, no title",
    PrivacyMode.OFF: "Off - publish nothing",
}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("VNPresence")
        self.geometry("560x380")
        self.minsize(460, 320)

        self.config_data = AppConfig.load()
        self.library = Library()
        self.session: GameSession | None = None
        self.worker: threading.Thread | None = None

        self._build_widgets()
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- layout -----------------------------------------------------------
    def _build_widgets(self) -> None:
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            frame, columns=("title", "privacy", "vndb"), show="headings", height=10
        )
        for column, heading, width in (
            ("title", "Game", 300),
            ("privacy", "Privacy", 90),
            ("vndb", "VNDB", 80),
        ):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, side="top")
        self.tree.bind("<Double-1>", lambda _event: self.play_selected())

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 4))
        ttk.Button(buttons, text="Play", command=self.play_selected).pack(side="left")
        ttk.Button(buttons, text="Add game…", command=self.add_game).pack(side="left", padx=4)
        ttk.Button(buttons, text="Remove", command=self.remove_selected).pack(side="left")
        ttk.Button(buttons, text="Stop", command=self.stop_session).pack(side="left", padx=4)

        privacy_row = ttk.Frame(frame)
        privacy_row.pack(fill="x")
        ttk.Label(privacy_row, text="Privacy:").pack(side="left")
        self.privacy_var = tk.StringVar(value=PrivacyMode.AUTO.value)
        combo = ttk.Combobox(
            privacy_row,
            textvariable=self.privacy_var,
            values=[m.value for m in PrivacyMode],
            state="readonly",
            width=10,
        )
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_privacy())

        # The two switches that make the app hands-off: no terminal needed.
        switches = ttk.Frame(frame)
        switches.pack(fill="x", pady=(10, 0))

        self.watch_var = tk.BooleanVar(value=running_pid() is not None)
        ttk.Checkbutton(
            switches,
            text="Auto-detect games I start myself",
            variable=self.watch_var,
            command=self.toggle_watch,
        ).pack(anchor="w")

        self.startup_var = tk.BooleanVar(value=self._startup_state())
        self.startup_box = ttk.Checkbutton(
            switches,
            text="Start with Windows",
            variable=self.startup_var,
            command=self.toggle_startup,
        )
        self.startup_box.pack(anchor="w")
        if sys.platform != "win32":
            self.startup_box.state(["disabled"])

        self.status = tk.StringVar(value="Ready")
        ttk.Label(frame, textvariable=self.status, foreground="#555").pack(
            fill="x", pady=(8, 0)
        )

    # -- data -------------------------------------------------------------
    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for profile in self.library.load_all():
            self.tree.insert(
                "",
                "end",
                iid=profile.id,
                values=(profile.title, profile.privacy.value, profile.vndb_id or "-"),
            )

    def selected_profile(self) -> GameProfile | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.library.get(selection[0])

    # -- actions ----------------------------------------------------------
    def add_game(self) -> None:
        path = filedialog.askopenfilename(
            title="Select the game executable",
            filetypes=[("Programs", "*.exe"), ("All files", "*.*")],
        )
        if not path:
            return
        # The .exe is usually named after the engine, the folder after the game.
        guess = guess_title(path)
        metadata, vndb_id = self._lookup(guess)

        if metadata is None or not messagebox.askyesno(
            "VNDB match",
            f"Is this the right game?\n\n{metadata.title}" if metadata else
            f"Nothing on VNDB matches “{guess}”.\n\nSearch by another name?",
        ):
            typed = simpledialog.askstring(
                "Game name", "Type the game's name:", initialvalue=guess, parent=self
            )
            if typed:
                metadata, vndb_id = self._lookup(typed)
                if metadata is None:
                    metadata, vndb_id = None, None
                    guess = typed
            else:
                metadata, vndb_id = None, None

        title = metadata.title if metadata else guess

        profile = GameProfile(
            id=self.library.unique_id(title),
            title=title,
            path=path,
            vndb_id=vndb_id,
            privacy=PrivacyMode(self.config_data.default_privacy),
        )
        self.library.save(profile)
        self.refresh()
        self.status.set(f"Added {title}")

    def _lookup(self, term: str):
        """Search VNDB for a name; returns (metadata, vndb_id) or (None, None)."""
        try:
            results = VNDBClient(cache_days=self.config_data.cache_days).search(term, limit=1)
        except VNDBError as exc:
            log.warning("VNDB search failed: %s", exc)
            return None, None
        if not results:
            return None, None
        metadata = results[0]
        return metadata, (metadata.url or "").rsplit("/", 1)[-1] or None

    def remove_selected(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        if messagebox.askyesno("Remove", f"Remove {profile.title} from the library?"):
            self.library.remove(profile.id)
            self.refresh()

    def apply_privacy(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        profile.privacy = PrivacyMode(self.privacy_var.get())
        self.library.save(profile)
        self.refresh()
        self.status.set(PRIVACY_HELP[profile.privacy])

    # -- the two switches -------------------------------------------------
    def _startup_state(self) -> bool:
        try:
            return startup.is_enabled()
        except Exception:  # pragma: no cover - registry trouble
            log.debug("could not read the autostart setting", exc_info=True)
            return False

    def toggle_watch(self) -> None:
        """Start or stop the background watcher."""
        if self.watch_var.get():
            if running_pid() is not None:
                self.status.set("Already watching in the background.")
                return
            if not self.library.load_all():
                self.watch_var.set(False)
                messagebox.showinfo("VNPresence", "Add a game first.")
                return
            try:
                pid = spawn_background()
            except Exception as exc:
                self.watch_var.set(False)
                messagebox.showerror("VNPresence", f"Could not start watching:\n{exc}")
                return
            self.status.set(
                f"Watching in the background (pid {pid}) - start a game any way you like."
            )
        else:
            stopped = stop_background()
            self.status.set("Stopped watching." if stopped else "Nothing was watching.")

    def toggle_startup(self) -> None:
        """Add or remove VNPresence from the Windows startup entries."""
        wanted = self.startup_var.get()
        try:
            startup.set_enabled(wanted)
        except startup.StartupUnsupported as exc:
            self.startup_var.set(False)
            messagebox.showinfo("VNPresence", str(exc))
            return
        except Exception as exc:  # pragma: no cover - registry trouble
            self.startup_var.set(not wanted)
            messagebox.showerror("VNPresence", f"Could not change that setting:\n{exc}")
            return
        self.status.set(
            "VNPresence will start watching when you log in."
            if wanted
            else "VNPresence will no longer start with Windows."
        )

    def play_selected(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("VNPresence", "A session is already running.")
            return
        profile = self.selected_profile()
        if profile is None:
            messagebox.showinfo("VNPresence", "Pick a game first.")
            return
        self.session = GameSession(profile, self.config_data)
        self.worker = threading.Thread(target=self._run_session, daemon=True)
        self.worker.start()

    def _run_session(self) -> None:
        assert self.session is not None
        try:
            result = self.session.run(on_event=self._on_event)
            self._set_status(f"{result.title}: {format_duration(result.seconds)}")
        except LaunchError as exc:
            self._set_status(f"Error: {exc}")
            messagebox.showerror("VNPresence", str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("session crashed")
            self._set_status(f"Error: {exc}")

    def stop_session(self) -> None:
        if self.session is not None:
            self.session.stop()
            self.status.set("Stopping…")

    def _on_event(self, kind: str, message: str) -> None:
        self._set_status(f"{kind}: {message}")

    def _set_status(self, text: str) -> None:
        self.after(0, lambda: self.status.set(text))

    def _on_close(self) -> None:
        if self.session is not None:
            self.session.stop()
        self.destroy()


def run_gui() -> None:
    App().mainloop()


if __name__ == "__main__":  # pragma: no cover
    run_gui()
