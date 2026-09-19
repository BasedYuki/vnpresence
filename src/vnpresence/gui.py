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
from .models import GameProfile, PrivacyMode, looks_like_vndb_ref, normalise_vndb_id
from .notes import read_note, write_note
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
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.load_note())

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 4))
        ttk.Button(buttons, text="Play", command=self.play_selected).pack(side="left")
        ttk.Button(buttons, text="Add game…", command=self.add_game).pack(side="left", padx=4)
        ttk.Button(buttons, text="Remove", command=self.remove_selected).pack(side="left")
        ttk.Button(buttons, text="VNDB link…", command=self.relink_selected).pack(
            side="left", padx=4
        )
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

        # Set it once here instead of fixing every game after adding it.
        ttk.Label(privacy_row, text="New games:").pack(side="left", padx=(16, 0))
        self.default_privacy_var = tk.StringVar(value=self.config_data.default_privacy)
        default_combo = ttk.Combobox(
            privacy_row,
            textvariable=self.default_privacy_var,
            values=[m.value for m in PrivacyMode if m is not PrivacyMode.OFF],
            state="readonly",
            width=8,
        )
        default_combo.pack(side="left", padx=6)
        default_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_default_privacy())

        # No engine reliably says which route you are on, so the reader can.
        # Typing here while a game is running changes the activity within one
        # update - there is nothing to restart.
        note_row = ttk.Frame(frame)
        note_row.pack(fill="x", pady=(10, 0))
        ttk.Label(note_row, text="Route / chapter:").pack(side="left")
        self.note_var = tk.StringVar()
        entry = ttk.Entry(note_row, textvariable=self.note_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda _e: self.apply_note())
        ttk.Button(note_row, text="Set", command=self.apply_note).pack(side="left")
        ttk.Button(note_row, text="Clear", command=self.clear_note).pack(side="left", padx=4)

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
            f"Nothing on VNDB matches “{guess}”.\n\nTry another name or a VNDB link?",
        ):
            # Offering the link here is the point: if the search picked the
            # sequel, no other name will fix it - the two share one.
            typed = simpledialog.askstring(
                "Game name",
                "Type the game's name, or paste its VNDB link\n"
                "(e.g. https://vndb.org/v2002):",
                initialvalue=guess,
                parent=self,
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
        """Find a game on VNDB by name **or** by link; (metadata, id) or (None, None).

        A name is a guess and a link is not, so a pasted VNDB URL skips the
        search entirely. That is the only way to tell a novel from a sequel
        that shares its name - "Rewrite" and "Rewrite+" both answer to
        "Rewrite", and the search cannot know which one is on disk.
        """
        client = VNDBClient(cache_days=self.config_data.cache_days)
        try:
            if looks_like_vndb_ref(term):
                metadata = client.get(normalise_vndb_id(term))
                if metadata is None:
                    return None, None
                return metadata, (metadata.url or "").rsplit("/", 1)[-1] or None
            results = client.search(term, limit=1)
        except (VNDBError, ValueError) as exc:
            log.warning("VNDB lookup failed: %s", exc)
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

    def relink_selected(self) -> None:
        """Repoint a game at the right VNDB entry.

        The name search cannot tell a novel from its sequel when they share a
        name, so this is the fix for "it found Rewrite, I am playing Rewrite+".
        """
        profile = self.selected_profile()
        if profile is None:
            messagebox.showinfo("VNPresence", "Pick a game first.")
            return
        typed = simpledialog.askstring(
            "VNDB link",
            f"Paste the VNDB link for {profile.title}\n(e.g. https://vndb.org/v2400):",
            initialvalue=f"https://vndb.org/{profile.vndb_id}" if profile.vndb_id else "",
            parent=self,
        )
        if not typed:
            return
        metadata, vndb_id = self._lookup(typed)
        if metadata is None or vndb_id is None:
            messagebox.showerror(
                "VNPresence", f"VNDB has nothing at “{typed}”, so nothing was changed."
            )
            return
        profile.vndb_id = vndb_id
        profile.title = metadata.title
        self.library.save(profile)
        self.refresh()
        self.status.set(f"{profile.title} is now linked to {metadata.url}")

    def apply_note(self) -> None:
        """Save what is typed in the route box for the selected game."""
        profile = self.selected_profile()
        if profile is None:
            self.status.set("Pick a game first.")
            return
        text = self.note_var.get().strip()
        write_note(profile.id, text)
        self.status.set(
            f"{profile.title}: {text}" if text else f"Cleared the note for {profile.title}."
        )

    def clear_note(self) -> None:
        self.note_var.set("")
        self.apply_note()

    def load_note(self) -> None:
        """Show the selected game's note, so it can be edited rather than retyped."""
        profile = self.selected_profile()
        self.note_var.set(read_note(profile.id) or "" if profile else "")

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

    def apply_default_privacy(self) -> None:
        """Remember the privacy mode new games should start with."""
        chosen = self.default_privacy_var.get()
        self.config_data.default_privacy = chosen
        try:
            self.config_data.save()
        except Exception as exc:  # pragma: no cover - disk trouble
            messagebox.showerror("VNPresence", f"Could not save that setting:\n{exc}")
            return
        self.status.set(
            "New games will show their title and cover."
            if chosen == PrivacyMode.FULL.value
            else f"New games will be added as '{chosen}'."
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
