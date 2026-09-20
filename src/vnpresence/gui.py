"""The desktop window: a library, the buttons that act on it, and a theme.

Tkinter ships with Python, so the frozen .exe needs no extra GUI dependency.
The window is a thin shell over the same API the CLI uses - no logic lives
here, which is what keeps it testable without a display: everything that makes
a decision is a plain function or a method that takes what it needs.

Layout rules the window follows:
* one accent-coloured button for the main action, everything else quiet;
* actions that need a selected game sit together and grey out without one;
* the list carries what you look things up by - name, time read, privacy;
* nothing is more than one click deep.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__, startup, theme, update
from .config import AppConfig
from .daemon import running_pid, spawn_background, stop_background
from .emulators import is_emulator
from .emulators import label as emulator_label
from .emulators import running as running_emulators
from .launcher import LaunchError
from .library import Library
from .models import GameProfile, PrivacyMode, looks_like_vndb_ref, normalise_vndb_id
from .notes import read_note, write_note
from .playtime import Playtime, format_reading_time, parse_duration
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


def matches(profile: GameProfile, query: str) -> bool:
    """Is this game worth showing while the filter box says `query`?

    Matched against the name and the id, case-insensitively, so typing "muv"
    finds "Muv-Luv Alternative" and typing "sg" finds the game whose id is
    steins-gate.
    """
    query = " ".join(query.split()).casefold()
    if not query:
        return True
    return query in (profile.title or "").casefold() or query in profile.id.casefold()


def row_values(profile: GameProfile, seconds: float = 0.0) -> tuple[str, str, str, str]:
    """One line of the library list."""
    read = format_reading_time(seconds) or "-"
    return (
        profile.title,
        read.replace(" read", ""),
        profile.privacy.value,
        profile.vndb_id or "-",
    )


def _first_lines(notes: str, limit: int = 8) -> str:
    """A few lines of the release notes, for a message box that stays a box."""
    if not notes:
        return ""
    lines = [line for line in notes.splitlines() if line.strip()][:limit]
    return "\n".join(lines) + "\n"


def _vndb_id_of(metadata) -> str | None:
    """The v-number out of a VNDB url - what a profile stores."""
    if metadata is None:
        return None
    return (metadata.url or "").rsplit("/", 1)[-1] or None


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
        # Off the main thread and a moment late: a slow GitHub must never keep
        # the window from appearing.
        if self.config_data.check_updates:
            self.after(2000, lambda: threading.Thread(
                target=self._check_updates_quietly, daemon=True
            ).start())

    # -- layout -----------------------------------------------------------
    def _build_widgets(self) -> None:
        self.palette = theme.apply(self, self.config_data.theme)

        frame = ttk.Frame(self, padding=(14, 12))
        frame.pack(fill="both", expand=True)

        # Header: what this is, and the two things that are not about a game.
        header = ttk.Frame(frame)
        header.pack(fill="x")
        ttk.Label(header, text="Your library", style="Heading.TLabel").pack(side="left")
        ttk.Button(header, text="Updates", command=self.check_for_updates).pack(side="right")
        self.theme_var = tk.StringVar(value=theme.get(self.config_data.theme).label)
        theme_box = ttk.Combobox(
            header, textvariable=self.theme_var, values=theme.labels(),
            state="readonly", width=18,
        )
        theme_box.pack(side="right", padx=8)
        theme_box.bind("<<ComboboxSelected>>", lambda _e: self.apply_theme())
        ttk.Label(header, text="Theme", style="Muted.TLabel").pack(side="right")

        # Filter: a library of forty games needs one, and it costs one row.
        filter_row = ttk.Frame(frame)
        filter_row.pack(fill="x", pady=(10, 6))
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(filter_row, textvariable=self.filter_var)
        self.filter_entry.pack(side="left", fill="x", expand=True)
        self.filter_var.trace_add("write", lambda *_: self.refresh())
        ttk.Button(filter_row, text="Clear", command=self.clear_filter).pack(side="left", padx=6)

        # The library itself.
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            list_frame, columns=("title", "read", "privacy", "vndb"),
            show="headings", height=11, selectmode="browse",
        )
        for column, heading, width, anchor in (
            ("title", "Game", 280, "w"),
            ("read", "Time read", 90, "e"),
            ("privacy", "Privacy", 80, "center"),
            ("vndb", "VNDB", 70, "center"),
        ):
            self.tree.heading(column, text=heading, command=lambda c=column: self.sort_by(c))
            self.tree.column(column, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Rows alternate, and the selected game drives the buttons below.
        self.tree.tag_configure("odd", background=self.palette.stripe)
        self.tree.bind("<Double-1>", lambda _event: self.play_selected())
        self.tree.bind("<Return>", lambda _event: self.play_selected())
        self.tree.bind("<Delete>", lambda _event: self.remove_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.on_select())

        # Primary action, alone, so it is obvious what to press first.
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))
        self.play_button = ttk.Button(
            actions, text="\u25b6  Play", style="Accent.TButton", command=self.play_selected
        )
        self.play_button.pack(side="left")
        ttk.Button(actions, text="Add game\u2026", command=self.add_game).pack(
            side="left", padx=(8, 0)
        )
        self.stop_button = ttk.Button(actions, text="Stop", command=self.stop_session)
        self.stop_button.pack(side="right")

        # Everything that needs a game selected, together, greyed out without one.
        self.needs_selection: list[ttk.Button] = []
        game_row = ttk.Frame(frame)
        game_row.pack(fill="x", pady=(8, 0))
        for text, command in (
            ("VNDB link\u2026", self.relink_selected),
            ("Rename\u2026", self.rename_selected),
            ("Time read\u2026", self.set_playtime),
            ("Remove", self.remove_selected),
        ):
            button = ttk.Button(game_row, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self.needs_selection.append(button)

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=12)

        # Per-game settings, on one line each, with what they mean beside them.
        privacy_row = ttk.Frame(frame)
        privacy_row.pack(fill="x")
        ttk.Label(privacy_row, text="Privacy:").pack(side="left")
        self.privacy_var = tk.StringVar(value=PrivacyMode.AUTO.value)
        combo = ttk.Combobox(
            privacy_row, textvariable=self.privacy_var,
            values=[m.value for m in PrivacyMode], state="readonly", width=10,
        )
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_privacy())
        self.needs_selection.append(combo)

        # Set it once here instead of fixing every game after adding it.
        ttk.Label(privacy_row, text="New games:", style="Muted.TLabel").pack(
            side="left", padx=(16, 0)
        )
        self.default_privacy_var = tk.StringVar(value=self.config_data.default_privacy)
        default_combo = ttk.Combobox(
            privacy_row, textvariable=self.default_privacy_var,
            values=[m.value for m in PrivacyMode if m is not PrivacyMode.OFF],
            state="readonly", width=8,
        )
        default_combo.pack(side="left", padx=6)
        default_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_default_privacy())

        # No engine reliably says which route you are on, so the reader can.
        # Typing here while a game is running changes the activity within one
        # update - there is nothing to restart.
        note_row = ttk.Frame(frame)
        note_row.pack(fill="x", pady=(8, 0))
        ttk.Label(note_row, text="Route / chapter:").pack(side="left")
        self.note_var = tk.StringVar()
        note_entry = ttk.Entry(note_row, textvariable=self.note_var)
        note_entry.pack(side="left", fill="x", expand=True, padx=6)
        note_entry.bind("<Return>", lambda _e: self.apply_note())
        ttk.Button(note_row, text="Set", command=self.apply_note).pack(side="left")
        ttk.Button(note_row, text="Clear", command=self.clear_note).pack(side="left", padx=4)

        # The two switches that make the app hands-off: no terminal needed.
        switches = ttk.Frame(frame)
        switches.pack(fill="x", pady=(12, 0))

        self.watch_var = tk.BooleanVar(value=running_pid() is not None)
        ttk.Checkbutton(
            switches, text="Auto-detect games I start myself",
            variable=self.watch_var, command=self.toggle_watch,
        ).pack(anchor="w")

        self.startup_var = tk.BooleanVar(value=self._startup_state())
        self.startup_box = ttk.Checkbutton(
            switches, text="Start with Windows",
            variable=self.startup_var, command=self.toggle_startup,
        )
        self.startup_box.pack(anchor="w")
        if sys.platform != "win32":
            self.startup_box.state(["disabled"])

        self.status = tk.StringVar(value=f"VNPresence {__version__} - pick a game and press Play")
        ttk.Label(frame, textvariable=self.status, style="Muted.TLabel").pack(
            fill="x", pady=(12, 0)
        )

        self.bind("<Control-f>", lambda _e: self.filter_entry.focus_set())
        self.bind("<F5>", lambda _e: self.refresh())
        self.on_select()

    # -- data -------------------------------------------------------------
    def visible_profiles(self) -> list[GameProfile]:
        """The library, filtered by the box and in the chosen order."""
        query = self.filter_var.get() if hasattr(self, "filter_var") else ""
        profiles = [p for p in self.library.load_all() if matches(p, query)]
        history = Playtime().load()

        def key(profile: GameProfile):
            column = self.sort_column
            if column == "read":
                entry = history.get(profile.id)
                return -(entry.seconds if entry else 0.0)
            if column == "privacy":
                return profile.privacy.value
            if column == "vndb":
                return profile.vndb_id or "zzz"  # unmatched games last
            return (profile.title or "").casefold()

        return sorted(profiles, key=key, reverse=self.sort_reverse)

    def refresh(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        history = Playtime().load()
        shown = self.visible_profiles()
        for index, profile in enumerate(shown):
            entry = history.get(profile.id)
            self.tree.insert(
                "",
                "end",
                iid=profile.id,
                values=row_values(profile, entry.seconds if entry else 0.0),
                tags=("odd",) if index % 2 else (),
            )
        # Keep the selection across a refresh, or the buttons flicker off.
        if selected and selected[0] in {p.id for p in shown}:
            self.tree.selection_set(selected[0])
        self.on_select()

    #: The list starts alphabetical, which is what a library of names wants.
    sort_column = "title"
    sort_reverse = False

    def sort_by(self, column: str) -> None:
        """Clicking a heading sorts by it; clicking the same one reverses."""
        self.sort_reverse = (not self.sort_reverse) if column == self.sort_column else False
        self.sort_column = column
        self.refresh()

    def clear_filter(self) -> None:
        self.filter_var.set("")
        self.filter_entry.focus_set()

    def on_select(self) -> None:
        """Keep the buttons honest: no game selected, nothing to press."""
        profile = self.selected_profile()
        state = "!disabled" if profile is not None else "disabled"
        for widget in getattr(self, "needs_selection", []):
            # A stubbed widget in the tests has no state(); nothing to do.
            with contextlib.suppress(Exception):
                widget.state([state])
        if profile is None:
            self.load_note()
            return
        self.privacy_var.set(profile.privacy.value)
        self.load_note()
        self.status.set(PRIVACY_HELP[profile.privacy])

    def selected_profile(self) -> GameProfile | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.library.get(selection[0])

    def apply_theme(self) -> None:
        """Repaint the window and remember the choice."""
        palette = theme.by_label(self.theme_var.get())
        self.palette = theme.apply(self, palette.name)
        self.tree.tag_configure("odd", background=self.palette.stripe)
        self.config_data.theme = palette.name
        try:
            self.config_data.save()
        except Exception as exc:  # pragma: no cover - disk trouble
            log.debug("could not save the theme: %s", exc)
        self.status.set(f"Theme: {palette.label}")

    # -- actions ----------------------------------------------------------
    def add_game(self) -> None:
        path = filedialog.askopenfilename(
            title="Select the game executable",
            filetypes=[("Programs", "*.exe"), ("All files", "*.*")],
        )
        if not path:
            return
        # An emulator is not a game: it runs a whole library, and only its
        # window title says which one. Ask before anything else, because the
        # answer changes what we search VNDB for.
        window_match = self._ask_emulator(path)
        if window_match is False:  # they cancelled
            return

        # The .exe is usually named after the engine, the folder after the game.
        guess = guess_title(path)
        if isinstance(window_match, str) and window_match:
            guess = self._emulator_guess or guess
        candidates, problem = self._candidates(guess)
        metadata = candidates[0] if candidates else None

        if metadata is None or not messagebox.askyesno(
            "VNDB match",
            f"Is this the right game?\n\n{metadata.title}" if metadata else
            f"Nothing on VNDB matches “{guess}”.\n\nTry another name or a VNDB link?",
        ):
            picked, typed_name = self._ask_for_another(guess, candidates)
            metadata = picked
            if picked is None and typed_name:
                guess = typed_name  # at least call it what they typed

        vndb_id = _vndb_id_of(metadata)
        title = metadata.title if metadata else guess

        profile = GameProfile(
            id=self.library.unique_id(title),
            title=title,
            path=path,
            vndb_id=vndb_id,
            window_match=window_match or None,
            privacy=PrivacyMode(self.config_data.default_privacy),
        )
        self.library.save(profile)
        self.refresh()
        if profile.vndb_id is None:
            # Silence is what left games sitting with no cover and no reason
            # given - a windowed .exe has nowhere to print a warning to.
            messagebox.showinfo(
                "VNPresence",
                f"{title} was added without a VNDB match, so it has no cover "
                f"art or details.\n\n{problem or ''}"
                "To fix it any time: select the game, press "
                "“VNDB link…” and type its name or paste its VNDB link.",
            )
        clashes = self.library.sharing_exe_name(profile)
        if clashes:
            # Series share one launcher executable; matching by path handles it,
            # but the game's own .exe is steadier and only they can pick it.
            messagebox.showinfo(
                "VNPresence",
                f"{title} is started by the same file as "
                f"{', '.join(p.title for p in clashes[:3])}.\n\n"
                "That is normal for a series - they share a launcher - and "
                "VNPresence tells them apart by their full path.\n\n"
                "If auto-detect ever picks the wrong one, add the game's own "
                "executable instead of the launcher.",
            )
        self.status.set(f"Added {title}")

    def _ask_emulator(self, path: str):
        """For an emulator, work out which game is loaded. False = cancelled.

        The reader is asked once, with the answer already filled in from the
        title bar when the game is open - which is the easy case, and the one
        worth making one keypress long.
        """
        self._emulator_guess = ""
        if not is_emulator(path):
            return ""
        name = emulator_label(path) or "an emulator"

        suggestion, loaded_name = "", ""
        for item in running_emulators():
            if item.loaded and item.process.lower() in path.lower():
                suggestion, loaded_name = item.match, item.game
                break

        typed = simpledialog.askstring(
            "Emulated game",
            f"{name} runs every game you own, so VNPresence needs to know which "
            f"one this is.\n\n"
            "Type a disc serial or a distinctive part of the name as it appears "
            "in the emulator's title bar"
            + (f"\n\n(it is running {loaded_name} now)" if loaded_name else "")
            + ":",
            initialvalue=suggestion,
            parent=self,
        )
        if typed is None:
            return False
        self._emulator_guess = loaded_name
        return typed.strip()

    def _candidates(self, term: str):
        """VNDB matches for a name or a link, and why there are none if so.

        The reason matters. "Nothing is called that" and "VNDB did not answer"
        need different things from the reader, and a windowed .exe has no
        console to tell them apart in.
        """
        client = VNDBClient(cache_days=self.config_data.cache_days)
        try:
            if looks_like_vndb_ref(term):
                found = client.get(normalise_vndb_id(term))
                return ([found] if found else []), None
            return client.search(term, limit=5), None
        except VNDBError as exc:
            log.warning("VNDB lookup failed: %s", exc)
            return [], f"VNDB could not be reached: {exc}\n\n"
        except ValueError:
            return [], None

    def _ask_for_another(self, guess: str, candidates: list):
        """Offer the runners-up, a name, or a link. Returns (match, typed).

        Showing the other matches is the point: a side story sits right next to
        its parent in the results ("Tsukihime PLUS-DISC" under "Tsukihime"), and
        before this the only way past a wrong first guess was to type a better
        name - which for a side story does not exist.
        """
        others = candidates[1:5]
        prompt = "Type the game's name, or paste its VNDB link\n(e.g. https://vndb.org/v2002)"
        if others:
            listed = "\n".join(f"{i}. {item.title}" for i, item in enumerate(others, start=2))
            prompt = (
                "Did you mean one of these? Type its number.\n\n"
                + listed
                + "\n\nOr type another name, or paste a VNDB link"
            )
        typed = (
            simpledialog.askstring("Game name", prompt + ":", initialvalue=guess, parent=self)
            or ""
        ).strip()
        if not typed:
            return None, ""
        if typed.isdigit():
            index = int(typed) - 2
            return (others[index] if 0 <= index < len(others) else None), ""
        found, _ = self._candidates(typed)
        return (found[0] if found else None), typed

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
            # Not limit=1: VNDB's top hit for a common name can be a near-empty
            # entry with the same title, so ask for several and let `rank`
            # prefer the one people actually mean.
            results = client.search(term, limit=5)
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
            "VNDB match",
            f"Type a name or paste a VNDB link for {profile.title}\n"
            "(e.g. Kagetsu Tooya, or https://vndb.org/v47):",
            initialvalue=f"https://vndb.org/{profile.vndb_id}" if profile.vndb_id else "",
            parent=self,
        )
        if not typed:
            return
        candidates, problem = self._candidates(typed)
        metadata = candidates[0] if candidates else None
        if metadata is None or not messagebox.askyesno(
            "VNDB match", f"Use this one?\n\n{metadata.title}" if metadata else
            f"{problem or ''}Nothing on VNDB matches “{typed}”.\n\nTry something else?",
        ):
            metadata, _ = self._ask_for_another(typed, candidates)
        vndb_id = _vndb_id_of(metadata)
        if metadata is None or vndb_id is None:
            messagebox.showinfo("VNPresence", "Nothing was changed.")
            return
        profile.vndb_id = vndb_id
        # Keep a name the reader gave this game themselves: a release VNDB
        # folds into its parent (STEINS;GATE Re:Boot) still wants the parent's
        # cover, under its own name.
        if profile.title == metadata.title or messagebox.askyesno(
            "Title",
            f"Rename it to VNDB's title?\n\n{profile.title}  ->  {metadata.title}",
        ):
            profile.title = metadata.title
        self.library.save(profile)
        self.refresh()
        self.status.set(f"{profile.title} is now linked to {metadata.url}")

    def set_playtime(self) -> None:
        """Seed the total for a game that was being read long before this app.

        Nothing can read that number out of the game - no engine exposes its
        play time in a portable way - so the reader types what their own save
        screen says, once.
        """
        profile = self.selected_profile()
        if profile is None:
            messagebox.showinfo("VNPresence", "Pick a game first.")
            return
        history = Playtime()
        current = history.total(profile.id)
        typed = simpledialog.askstring(
            "Time read",
            f"How long have you read {profile.title} in total?\n"
            "(e.g. 50h, 50h 30m, 90m or 50:30)",
            initialvalue=f"{current / 3600:.1f}h" if current else "",
            parent=self,
        )
        if not typed:
            return
        try:
            seconds = parse_duration(typed)
        except ValueError as exc:
            messagebox.showerror("VNPresence", str(exc))
            return
        entry = history.set(profile.id, seconds)
        self.status.set(
            f"{profile.title}: {format_reading_time(entry.seconds) or 'nothing'} in total"
        )

    def rename_selected(self) -> None:
        """Change what the presence calls this game, and nothing else.

        For releases VNDB has no entry of its own for - a fan translation, a
        remake, a cut like STEINS;GATE Re:Boot - where the parent entry is the
        right source of cover art but the wrong name.
        """
        profile = self.selected_profile()
        if profile is None:
            messagebox.showinfo("VNPresence", "Pick a game first.")
            return
        typed = simpledialog.askstring(
            "Rename",
            "What should the presence call this game?",
            initialvalue=profile.title,
            parent=self,
        )
        if not typed or not typed.strip():
            return
        profile.title = typed.strip()
        self.library.save(profile)
        self.refresh()
        self.status.set(f"Now called {profile.title}")

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
    # -- updates ----------------------------------------------------------
    def _check_updates_quietly(self) -> None:
        """The once-a-day check. Silent unless there is something to say."""
        try:
            release = update.check()
        except Exception:  # pragma: no cover - a check must never crash the app
            log.debug("update check failed", exc_info=True)
            return
        if release is not None:
            self.after(0, lambda: self._offer_update(release))

    def check_for_updates(self) -> None:
        """The Updates button: says so either way, and ignores "skip"."""
        self.status.set("Checking for updates\u2026")

        def work() -> None:
            release = update.check(force=True)
            self.after(0, lambda: self._offer_update(release, quiet=False))

        threading.Thread(target=work, daemon=True).start()

    def _offer_update(self, release, *, quiet: bool = True) -> None:
        if release is None:
            self.status.set(f"VNPresence {__version__} is the newest build.")
            if not quiet:
                messagebox.showinfo(
                    "VNPresence", f"You are on the newest build ({__version__})."
                )
            return

        self.status.set(f"VNPresence {release.version} is available.")
        message = (
            f"A new version of VNPresence is available.\n\n"
            f"You have: {__version__}\n"
            f"Latest:   {release.version}"
            + (f"  ({release.published})" if release.published else "")
            + "\n\n"
            + _first_lines(release.notes)
            + "\nDownload and install it now?"
        )
        if messagebox.askyesno("Update available", message):
            self._install_update(release)
            return
        if messagebox.askyesno(
            "Update available", f"Stop mentioning {release.version}?"
        ):
            update.skip_version(release.version)
            self.status.set(f"Will not mention {release.version} again.")

    def _install_update(self, release) -> None:
        self.status.set("Downloading the update\u2026")

        def work() -> None:
            try:
                message = update.install(release)
            except update.UpdateError as exc:
                # Bound here, not inside the lambda: by the time tkinter runs
                # it the except block is long gone and `exc` with it.
                reason = str(exc)
                self.after(0, lambda: self._update_failed(release, reason))
                return
            except Exception as exc:  # pragma: no cover - network, disk
                log.exception("update failed")
                reason = str(exc)
                self.after(0, lambda: self._update_failed(release, reason))
                return
            self.after(0, lambda: self._update_ready(message))

        threading.Thread(target=work, daemon=True).start()

    def _update_ready(self, message: str) -> None:
        self.status.set(message)
        if messagebox.askyesno("Update ready", message + "\n\nClose VNPresence now?"):
            self._on_close()

    def _update_failed(self, release, reason: str) -> None:
        self.status.set("The update could not be installed.")
        messagebox.showerror(
            "VNPresence",
            f"The update could not be installed:\n\n{reason}\n\n"
            f"You can download it yourself from:\n{release.url}",
        )

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
        if kind == "focus":
            # The one event the reader is actually watching for: whether the
            # clock is running. It deserves a sentence, not "focus: paused".
            title = self.session.profile.title if self.session else "the game"
            if message == "paused":
                text = "⏸ Paused - you are using another window"
            elif message == "idle":
                minutes = int(self.config_data.idle_after // 60)
                text = f"⏸ Idle - nothing touched for {minutes} minutes"
            else:
                text = f"▶ Reading {title}"
            self._set_status(text)
            return
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
