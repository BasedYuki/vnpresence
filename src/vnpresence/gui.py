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
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__, covers, screenshots, startup, theme, update
from .config import AppConfig
from .daemon import running_pid, spawn_background, stop_background
from .emulators import is_emulator, is_rom, rom_kind
from .emulators import label as emulator_label
from .emulators import running as running_emulators
from .launcher import LaunchError
from .library import Library
from .library_view import Card, card_for, last_played_key, row_values, vndb_page
from .models import GameProfile, PrivacyMode, looks_like_vndb_ref, normalise_vndb_id
from .notes import read_note, write_note
from .playtime import Playtime, format_reading_time, parse_duration
from .session import GameSession, describe_session
from .titles import guess_title
from .vndb import VNDBClient, VNDBError

log = logging.getLogger(__name__)

#: How often the library list re-reads the reading history while a session is
#: running. The session writes it once a minute, so anything faster would be
#: redrawing the same numbers.
REFRESH_WHILE_PLAYING = 60_000  # milliseconds

#: One cover in the grid, in pixels. Portrait, the shape of a game box.
COVER_SIZE = (150, 213)
#: A tile is the cover plus room around it for the title and the time.
TILE_WIDTH = COVER_SIZE[0] + 24

#: The window's size when it is not maximized and has never been resized.
DEFAULT_GEOMETRY = "1040x680"

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


def _quietly(action) -> None:
    """Run a UI touch-up that may find its window already closed."""
    with contextlib.suppress(Exception):
        action()


def open_path(path) -> None:
    """Show a file or folder in whatever the desktop uses for it."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603, S607
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607
    except Exception:
        log.debug("could not open %s", path, exc_info=True)


def open_url(url: str) -> None:
    """A web page in the default browser; quietly nothing if there is none."""
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:
        log.debug("could not open %s", url, exc_info=True)


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
        self.minsize(720, 480)

        self.config_data = AppConfig.load()
        self.library = Library()
        self.session: GameSession | None = None
        self.worker: threading.Thread | None = None
        #: Covers drawn for the grid, kept so Tk does not garbage-collect the
        #: image out from under a tile that is still on screen.
        self._tile_images: dict[str, object] = {}
        self._tile_cache: dict[tuple, object] = {}
        self._cards: list[Card] = []
        self._fetching_covers = False
        self._details = None

        self.geometry(self.config_data.window_geometry or DEFAULT_GEOMETRY)
        if self.config_data.start_maximized:
            self._maximize()

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
        # List or covers - the two ways PCSX2 shows a library, and the choice
        # survives a restart.
        self.view_var = tk.StringVar(value=self.config_data.library_view or "list")
        for value, text in (("list", "\u2630  List"), ("grid", "\u25a6  Grid")):
            ttk.Radiobutton(
                filter_row, text=text, value=value, variable=self.view_var,
                style="View.Toolbutton", command=self.set_view,
            ).pack(side="left", padx=(0, 4))
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(filter_row, textvariable=self.filter_var)
        self.filter_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.filter_var.trace_add("write", lambda *_: self.refresh())
        ttk.Button(filter_row, text="Clear", command=self.clear_filter).pack(side="left", padx=6)

        # The library itself: the list and the grid share one spot, and one
        # selection - the list is the source of truth even when hidden, so
        # every button below works the same whichever view is showing.
        self.library_area = ttk.Frame(frame)
        self.library_area.pack(fill="both", expand=True)
        list_frame = self.list_frame = ttk.Frame(self.library_area)
        self.tree = ttk.Treeview(
            list_frame, columns=("title", "read", "last", "sessions", "privacy", "vndb"),
            show="headings", height=11, selectmode="browse",
        )
        for column, heading, width, anchor in (
            ("title", "Game", 340, "w"),
            ("read", "Time played", 100, "e"),
            ("last", "Last played", 110, "center"),
            ("sessions", "Sessions", 80, "center"),
            ("privacy", "Privacy", 80, "center"),
            ("vndb", "VNDB", 70, "center"),
        ):
            self.tree.heading(column, text=heading, command=lambda c=column: self.sort_by(c))
            self.tree.column(column, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._build_grid()

        # Rows alternate, and the selected game drives the buttons below.
        self.tree.tag_configure("odd", background=self.palette.stripe)
        self.tree.bind("<Double-1>", lambda _event: self.play_selected())
        self.tree.bind("<Return>", lambda _event: self.play_selected())
        self.tree.bind("<Delete>", lambda _event: self.remove_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.on_select())
        self.tree.bind("<Button-3>", self._row_menu)

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
            ("Details\u2026", self.open_details),
            ("VNDB link\u2026", self.relink_selected),
            ("Rename\u2026", self.rename_selected),
            ("Time played\u2026", self.set_playtime),
            ("Remove", self.remove_selected),
        ):
            button = ttk.Button(game_row, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self.needs_selection.append(button)

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)

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

        # The two switches that make the app hands-off, at the end of the
        # privacy row: one row less under the library is a row more of covers.
        self.startup_var = tk.BooleanVar(value=self._startup_state())
        self.startup_box = ttk.Checkbutton(
            privacy_row, text="Start with Windows",
            variable=self.startup_var, command=self.toggle_startup,
        )
        self.startup_box.pack(side="right")
        if sys.platform != "win32":
            self.startup_box.state(["disabled"])

        self.watch_var = tk.BooleanVar(value=running_pid() is not None)
        ttk.Checkbutton(
            privacy_row, text="Auto-detect games I start myself",
            variable=self.watch_var, command=self.toggle_watch,
        ).pack(side="right", padx=(0, 16))

        self.status = tk.StringVar(value=f"VNPresence {__version__} - pick a game and press Play")
        ttk.Label(frame, textvariable=self.status, style="Muted.TLabel").pack(
            fill="x", pady=(8, 0)
        )

        self.bind("<Control-f>", lambda _e: self.filter_entry.focus_set())
        self.bind("<F5>", lambda _e: self.refresh())
        self.bind("<Control-i>", lambda _e: self.open_details())
        self.bind("<Control-g>", lambda _e: self.toggle_view())
        self.bind("<Control-o>", lambda _e: self.open_vndb_page())
        self._show_view()
        self.on_select()

    # -- data -------------------------------------------------------------
    def visible_profiles(self) -> list[GameProfile]:
        """The library, filtered by the box and in the chosen order."""
        query = self.filter_var.get() if hasattr(self, "filter_var") else ""
        profiles = [p for p in self.library.load_all() if matches(p, query)]
        history = Playtime().load()

        def key(profile: GameProfile):
            column = self.sort_column
            entry = history.get(profile.id)
            # Most first, for the three numbers: what you want at the top of a
            # "Last played" column is what you played last.
            if column == "read":
                return -(entry.seconds if entry else 0.0)
            if column == "last":
                return -last_played_key(entry.last_played if entry else None)
            if column == "sessions":
                return -(entry.sessions if entry else 0)
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
            self.tree.insert(
                "",
                "end",
                iid=profile.id,
                values=row_values(profile, history.get(profile.id)),
                tags=("odd",) if index % 2 else (),
            )
        # Keep the selection across a refresh, or the buttons flicker off.
        if selected and selected[0] in {p.id for p in shown}:
            self.tree.selection_set(selected[0])
        if getattr(self, "view_var", None) is not None and self.view_var.get() == "grid":
            self.refresh_grid(shown, history)
        self.on_select()

    #: The list starts alphabetical, which is what a library of names wants.
    sort_column = "title"
    sort_reverse = False

    def sort_by(self, column: str) -> None:
        """Clicking a heading sorts by it; clicking the same one reverses."""
        self.sort_reverse = (not self.sort_reverse) if column == self.sort_column else False
        self.sort_column = column
        self.refresh()

    # -- list or grid -------------------------------------------------------
    def set_view(self) -> None:
        """The switch was pressed: show that view and remember the choice."""
        self.config_data.library_view = self.view_var.get()
        with contextlib.suppress(Exception):
            self.config_data.save()
        self._show_view()
        self.refresh()

    def toggle_view(self) -> None:
        self.view_var.set("list" if self.view_var.get() == "grid" else "grid")
        self.set_view()

    def _show_view(self) -> None:
        if self.view_var.get() == "grid":
            self.list_frame.pack_forget()
            self.grid_frame.pack(fill="both", expand=True)
        else:
            self.grid_frame.pack_forget()
            self.list_frame.pack(fill="both", expand=True)

    def _build_grid(self) -> None:
        """A scrolling shelf of covers: a canvas, with a frame of tiles inside."""
        self.grid_frame = ttk.Frame(self.library_area)
        self.grid_canvas = tk.Canvas(
            self.grid_frame, highlightthickness=0, borderwidth=0,
            background=self.palette.background,
        )
        scroll = ttk.Scrollbar(self.grid_frame, orient="vertical",
                               command=self.grid_canvas.yview)
        self.grid_canvas.configure(yscrollcommand=scroll.set)
        self.grid_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.grid_inner = ttk.Frame(self.grid_canvas)
        self._grid_window = self.grid_canvas.create_window(
            (0, 0), window=self.grid_inner, anchor="nw")
        self.grid_inner.bind("<Configure>", lambda _e: self.grid_canvas.configure(
            scrollregion=self.grid_canvas.bbox("all")))
        self.grid_canvas.bind("<Configure>", lambda _e: self._layout_grid())
        # The wheel scrolls the shelf wherever the pointer is over it.
        for widget in (self.grid_canvas, self.grid_inner):
            widget.bind("<MouseWheel>", self._wheel)
            widget.bind("<Button-4>", self._wheel)
            widget.bind("<Button-5>", self._wheel)
        self._tiles: dict[str, ttk.Frame] = {}
        self._columns = 0

    def _wheel(self, event) -> str:
        if getattr(event, "num", None) == 4:
            step = -3
        elif getattr(event, "num", None) == 5:
            step = 3
        else:
            step = -int(event.delta / 40) or (-1 if event.delta > 0 else 1)
        self.grid_canvas.yview_scroll(step, "units")
        return "break"

    def refresh_grid(self, shown=None, history=None) -> None:
        """Rebuild the tiles for whatever the list is showing, in its order."""
        shown = self.visible_profiles() if shown is None else shown
        history = Playtime().load() if history is None else history
        client = VNDBClient(cache_days=self.config_data.cache_days)
        self._cards = [
            card_for(profile, history.get(profile.id),
                     client.peek(profile.vndb_id) if profile.vndb_id else None,
                     self.config_data)
            for profile in shown
        ]
        for child in self.grid_inner.winfo_children():
            child.destroy()
        self._tiles = {}
        self._tile_images = {}
        for card in self._cards:
            self._tiles[card.id] = self._make_tile(card)
        self._columns = 0  # force a re-layout
        self._layout_grid()
        self._paint_selection()
        self._fetch_missing_covers()

    def _make_tile(self, card: Card):
        tile = ttk.Frame(self.grid_inner, style="Tile.TFrame", padding=6)
        image = self._tile_image(card)
        self._tile_images[card.id] = image
        cover = ttk.Label(tile, image=image, style="Tile.TLabel")
        cover.pack()
        name = ttk.Label(tile, text=card.title, style="Tile.TLabel",
                         wraplength=COVER_SIZE[0], justify="center", anchor="center")
        name.pack(fill="x", pady=(6, 0))
        played = ttk.Label(tile, text=card.time_played if card.time_played != "-" else "",
                           style="TileMuted.TLabel", anchor="center")
        played.pack(fill="x")
        tile._labels = (cover, name, played)  # type: ignore[attr-defined]
        for widget in (tile, cover, name, played):
            widget.bind("<Button-1>", lambda _e, i=card.id: self._select_card(i))
            widget.bind("<Double-1>", lambda _e, i=card.id: self._play_card(i))
            widget.bind("<Button-3>", lambda e, i=card.id: self._card_menu(e, i))
            widget.bind("<MouseWheel>", self._wheel)
            widget.bind("<Button-4>", self._wheel)
            widget.bind("<Button-5>", self._wheel)
        return tile

    def _tile_image(self, card: Card, size=COVER_SIZE):
        """The cover as a Tk image - or a card with the title on it."""
        path = None if card.hide_cover else covers.cached(card.cover_url)
        key = (str(path), card.title, size, self.palette.name,
               path.stat().st_mtime if path else 0)
        picture = self._tile_cache.get(key)
        if picture is None:
            picture = covers.tile(path, size, title=card.title,
                                  background=self.palette.surface,
                                  foreground=self.palette.muted)
            self._tile_cache[key] = picture
        try:
            from PIL import ImageTk

            return ImageTk.PhotoImage(picture, master=self)
        except Exception:  # pragma: no cover - Pillow ships in the .exe
            # Loudly, once: a broken Tk bridge looks like a grid of empty
            # boxes, and the log is the only place that can say why.
            if not getattr(self, "_warned_images", False):
                self._warned_images = True
                log.warning("cannot draw covers", exc_info=True)
            return ""

    def _layout_grid(self) -> None:
        """As many columns as fit; recomputed when the window is resized."""
        width = max(self.grid_canvas.winfo_width(), TILE_WIDTH)
        columns = max(width // (TILE_WIDTH + 12), 1)
        self.grid_canvas.itemconfigure(self._grid_window, width=width)
        if columns == self._columns:
            return
        self._columns = columns
        for index, card in enumerate(self._cards):
            tile = self._tiles.get(card.id)
            if tile is not None:
                tile.grid(row=index // columns, column=index % columns,
                          padx=6, pady=6, sticky="n")

    def _select_card(self, game_id: str) -> None:
        self.tree.selection_set(game_id)
        self.tree.see(game_id)
        self.on_select()
        self._paint_selection()

    def _play_card(self, game_id: str) -> None:
        self._select_card(game_id)
        self.play_selected()

    def _paint_selection(self) -> None:
        """Light the chosen tile the way the list lights the chosen row."""
        selection = self.tree.selection()
        chosen = selection[0] if selection else None
        for game_id, tile in getattr(self, "_tiles", {}).items():
            on = game_id == chosen
            tile.configure(style="TileSelected.TFrame" if on else "Tile.TFrame")
            cover, name, played = tile._labels  # type: ignore[attr-defined]
            for label in (cover, name):
                label.configure(style="TileSelected.TLabel" if on else "Tile.TLabel")
            played.configure(style="TileSelectedMuted.TLabel" if on else "TileMuted.TLabel")

    def _fetch_missing_covers(self) -> None:
        """Download the covers the grid is missing, off the main thread.

        One trip per missing cover, once: they go into the cache folder and
        the next refresh finds them there. The window redraws when the batch
        is done rather than per image, so the shelf does not flicker.
        """
        wanted = [c for c in self._cards if not c.hide_cover]
        missing = [c for c in wanted if not covers.cached(c.cover_url)]
        if not missing or self._fetching_covers:
            return
        self._fetching_covers = True
        profiles = {p.id: p for p in self.library.load_all()}

        def work() -> None:
            got = False
            client = VNDBClient(cache_days=self.config_data.cache_days)
            try:
                for card in missing:
                    url = card.cover_url
                    if not url:
                        profile = profiles.get(card.id)
                        if profile is None or not profile.vndb_id:
                            continue
                        try:
                            metadata = client.get(profile.vndb_id)
                        except Exception:
                            continue
                        url = metadata.image_url if metadata else None
                    if covers.download(url) is not None:
                        got = True
            finally:
                self._fetching_covers = False
            if got:
                self.after(0, self.refresh)

        threading.Thread(target=work, daemon=True).start()

    # -- right-click ------------------------------------------------------
    def _row_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self._card_menu(event, row)

    def _card_menu(self, event, game_id: str) -> None:
        self._select_card(game_id)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="▶  Play", command=self.play_selected)
        menu.add_command(label="Details…", command=self.open_details)
        menu.add_command(label="Screenshots folder", command=self.open_gallery)
        profile = self.selected_profile()
        linked = profile is not None and vndb_page(profile)[1]
        menu.add_command(label="Open on VNDB" if linked else "Search on VNDB",
                         command=self.open_vndb_page)
        menu.add_separator()
        menu.add_command(label="Rename…", command=self.rename_selected)
        menu.add_command(label="VNDB link…", command=self.relink_selected)
        menu.add_command(label="Remove", command=self.remove_selected)
        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    # -- details and the gallery --------------------------------------------
    def open_details(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        from .details_window import DetailsWindow

        if self._details is not None:
            with contextlib.suppress(Exception):
                self._details.destroy()
        self._details = DetailsWindow(self, profile)

    def open_vndb_page(self) -> None:
        """The game's VNDB entry in the browser - for logging it there."""
        profile = self.selected_profile()
        if profile is None:
            return
        url, linked = vndb_page(profile)
        open_url(url)
        self.status.set(f"Opened {profile.title} on VNDB" if linked else
                        f"{profile.title} is not linked to VNDB yet - searched for it there")

    def open_gallery(self) -> None:
        profile = self.selected_profile()
        if profile is None:
            return
        folder = screenshots.gallery_dir(profile.id)
        folder.mkdir(parents=True, exist_ok=True)
        open_path(folder)

    # -- the window itself ----------------------------------------------------
    def _maximize(self) -> None:
        """Maximized, not fullscreen: the title bar and taskbar stay."""
        try:
            self.state("zoomed")  # Windows, macOS
        except Exception:
            with contextlib.suppress(Exception):
                self.attributes("-zoomed", True)  # X11

    def _is_maximized(self) -> bool:
        with contextlib.suppress(Exception):
            if self.state() == "zoomed":
                return True
        with contextlib.suppress(Exception):
            return bool(self.attributes("-zoomed"))
        return False

    def _remember_window(self) -> None:
        """Keep how the reader left it: maximized, or the size they chose."""
        maximized = self._is_maximized()
        self.config_data.start_maximized = maximized
        if not maximized:
            with contextlib.suppress(Exception):
                self.config_data.window_geometry = self.geometry()
        with contextlib.suppress(Exception):
            self.config_data.save()

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
        if hasattr(self, "_tiles"):
            self._paint_selection()

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
        # Placeholder cards are drawn in the theme's colours: draw them again.
        getattr(self, "_tile_cache", {}).clear()
        with contextlib.suppress(Exception):
            self.grid_canvas.configure(background=self.palette.background)
            if self.view_var.get() == "grid":
                self.refresh_grid()
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
        rom = self._ask_for_the_emulator(path)
        if rom is False:  # a game file, and they did not pick an emulator
            return
        if rom:  # they picked one: the emulator is the program, the ROM its argument
            path, rom_path = rom
        else:
            rom_path = None
        # An emulator is not a game: it runs a whole library, and only its
        # window title says which one. Ask before anything else, because the
        # answer changes what we search VNDB for.
        window_match = self._ask_emulator(path)
        if window_match is False:  # they cancelled
            return

        # The .exe is usually named after the engine, the folder after the
        # game - and with an emulator, neither: the ROM's name is the game.
        guess = guess_title(rom_path or path)
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
            # The emulator is started with the game as its argument, which is
            # what makes Play open the novel rather than an empty emulator.
            args=[rom_path] if rom_path else [],
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

    def _ask_for_the_emulator(self, path: str):
        """Picked a ROM? Offer to point at the emulator instead.

        Returns None when the file is an ordinary program, False when they
        gave up, or (emulator, rom) when they picked one. Choosing the ROM is
        the natural mistake - it is the thing a reader thinks of as the game -
        and the only thing Windows says about it is "%1 is not a valid Win32
        application", hours later, when they press Play.
        """
        if not is_rom(path):
            return None
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        if not messagebox.askyesno(
            "That is a game file, not a program",
            f"{name} is a {rom_kind(path)}.\n\n"
            "VNPresence starts a program and follows it. For an emulated game "
            "that program is the emulator, and the game is what you tell it to "
            "open.\n\nPick the emulator now?",
        ):
            return False
        emulator = filedialog.askopenfilename(
            title="Select the emulator (Ryujinx, RPCS3, PPSSPP…)",
            filetypes=[("Programs", "*.exe"), ("All files", "*.*")],
        )
        if not emulator:
            return False
        if not is_emulator(emulator) and not messagebox.askyesno(
            "VNPresence",
            f"{emulator.replace(chr(92), '/').rsplit('/', 1)[-1]} is not an "
            "emulator VNPresence knows by name.\n\nUse it anyway?",
        ):
            return False
        return emulator, path

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

        messagebox.showinfo(
            "One more thing about emulators",
            f"{name} publishes a Discord activity of its own, and Discord only "
            "shows one game at a time - so while the emulator's is on, "
            "VNPresence's sits underneath it and you never see it.\n\n"
            "Turn it off in the emulator's settings (usually \u201cEnable "
            "Discord Rich Presence\u201d) and VNPresence's takes over.",
        )
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
        self.after(REFRESH_WHILE_PLAYING, self.keep_the_total_fresh)

    def _run_session(self) -> None:
        assert self.session is not None
        try:
            result = self.session.run(on_event=self._on_event)
            self._set_status(f"{result.title}: {describe_session(result)}")
        except LaunchError as exc:
            self._set_status(f"Error: {exc}")
            messagebox.showerror("VNPresence", str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("session crashed")
            self._set_status(f"Error: {exc}")
        finally:
            # The session has just written the evening to the history. Without
            # this the Time read column would go on showing what it said when
            # the window opened, which reads as "it never updates" - and was
            # reported as exactly that. after() because this is a worker
            # thread and the widgets belong to the main one.
            self.after(0, self.refresh)

    def keep_the_total_fresh(self) -> None:
        """Re-read the reading history while a session is running.

        The session writes it once a minute, so the number on screen can
        follow the evening instead of being a snapshot from whenever the
        window happened to open. Stops by itself when the session does.
        """
        if self.worker is not None and self.worker.is_alive():
            self.refresh()
            self.after(REFRESH_WHILE_PLAYING, self.keep_the_total_fresh)

    def stop_session(self) -> None:
        if self.session is not None:
            self.session.stop()
            self.status.set("Stopping…")

    def _on_event(self, kind: str, message: str) -> None:
        if kind == "screenshot":
            self._set_status(f"\U0001f4f7 {message}")
            # An open details page for this game shows the new picture at once.
            details = self._details
            if details is not None and message.startswith("saved"):
                self.after(0, lambda: _quietly(details.refresh_gallery))
            return
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
        self._remember_window()
        if self.session is not None:
            self.session.stop()
        self.destroy()


def run_gui() -> None:
    App().mainloop()


if __name__ == "__main__":  # pragma: no cover
    run_gui()
