"""One game, on its own page.

A banner across the top - the cover, blurred into colour, with the title over
it - and the page's accent taken from that cover, so each novel's page looks
like that novel. Under it the numbers that matter at a glance, and then tabs
for everything else:

* **Overview** - a heatmap of the last six months, streaks, how far through
  the novel you are next to VNDB's average, and your VNDB list status.
* **Routes & Notes** - your own route list, ticked off as you go, and notes.
* **Sessions** - every time you played: when, and how long really counted.
* **About** - VNDB's description, developers and tags, spoilers held back.
* **Screenshots** - the gallery: open, show in folder, copy, share.
* **Settings** - how the game is started.

Everything slow (VNDB) happens on a background thread and lands on the page
when it is back; the page itself always opens at once, offline included.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import (
    banner,
    chart,
    cover_colors,
    covers,
    journal,
    screenshots,
    session_log,
    shell,
    stats,
    theme,
    vndb_list,
)
from .launcher import LAUNCH_MODES, launch_mode
from .library_view import card_for, format_last_played, vndb_page
from .notes import read_note, write_note
from .playtime import Playtime
from .vndb import VNDBClient, about_text, visible_tags

log = logging.getLogger(__name__)

#: The sharp cover sitting on the banner.
BANNER_COVER = (132, 188)
BANNER_HEIGHT = 230
#: Screenshot thumbnails: 16:9, the shape most novels run in.
THUMB = (200, 113)
MAX_THUMBS = 24
#: Sessions shown before "Show all".
RECENT_SESSIONS = 10
#: How many lines of VNDB's description show before "More".
ABOUT_PREVIEW = 360


class DetailsWindow(tk.Toplevel):
    def __init__(self, app, profile) -> None:
        super().__init__(app)
        self.app = app
        self.profile = profile
        self.title(profile.title)
        self.geometry("1120x860")
        self.minsize(900, 640)
        self.transient(app)
        self.metadata = None
        self.account = vndb_list.load_account()
        self.show_spoilers = False
        self.about_expanded = False
        self.all_sessions = False
        #: Work finished on background threads waits here for Tk's thread:
        #: Tk itself must only ever be touched from the thread that runs it.
        self._inbox: queue.Queue = queue.Queue()
        self.after(100, self._drain)
        self.bind("<Escape>", lambda _e: self.destroy())
        self._build()
        self.focus_set()
        self._load_in_background()

    # -- the page ---------------------------------------------------------------
    def rebuild(self) -> None:
        """Draw it again - after a theme change, a new VNDB link, a new account."""
        tab = self._current_tab()
        for child in self.winfo_children():
            child.destroy()
        self._build()
        with contextlib.suppress(Exception):
            self.tabs.select(tab)
        self._load_in_background()

    def _current_tab(self) -> int:
        try:
            return self.tabs.index(self.tabs.select())
        except Exception:
            return 0

    def _build(self) -> None:
        app, profile = self.app, self.profile
        self._images: list = []
        self._thumb_images: list = []
        self._selected_shot = None
        client = VNDBClient(cache_days=app.config_data.cache_days)
        self.metadata = client.peek(profile.vndb_id) if profile.vndb_id else None
        self.entry = Playtime().get(profile.id)
        self.card = card_for(profile, self.entry, self.metadata, app.config_data)
        self.cover = None if self.card.hide_cover else covers.cached(self.card.cover_url)
        # The page's own colours: the theme, with the cover's accent.
        self.palette = cover_colors.page_palette(app.palette, self.cover)
        theme.apply_page(self, self.palette)
        self.configure(background=self.palette.background)

        self._banner()
        self._numbers()
        self.message = tk.StringVar()
        ttk.Label(self, textvariable=self.message, style="Muted.TLabel",
                  padding=(20, 0)).pack(side="bottom", fill="x", pady=(0, 8))

        self.tabs = ttk.Notebook(self, style="Page.TNotebook")
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(8, 8))
        for title, build in (("Overview", self._overview_tab),
                             ("Routes & Notes", self._journal_tab),
                             ("Sessions", self._sessions_tab),
                             ("About", self._about_tab),
                             ("Screenshots", self._screenshots_tab),
                             ("Settings", self._settings_tab)):
            frame = ttk.Frame(self.tabs, style="Inner.TFrame", padding=18)
            self.tabs.add(frame, text=title)
            build(frame)

    # -- banner -------------------------------------------------------------------
    def _banner(self) -> None:
        palette = self.palette
        self.banner = tk.Canvas(self, height=BANNER_HEIGHT, highlightthickness=0,
                                borderwidth=0, background=palette.background)
        self.banner.pack(fill="x")
        cover = covers.tile(self.cover, BANNER_COVER, title=self.card.title,
                            background=palette.surface, foreground=palette.muted)
        self._cover_image = _photo(cover, self)
        self._banner_image = None
        self._banner_width = 0

        url, linked = vndb_page(self.profile)
        bar = ttk.Frame(self.banner, style="TFrame")
        ttk.Button(bar, text="▶  Play", style="Page.Accent.TButton",
                   command=self._play).pack(side="left")
        ttk.Button(bar, text=f"VNDB {self.profile.vndb_id}" if linked else "Search on VNDB",
                   style="Card.TButton", command=lambda: _open_url(url)).pack(
            side="left", padx=(8, 0))
        if not linked:
            ttk.Button(bar, text="Link to VNDB…", style="Card.TButton",
                       command=self._relink).pack(side="left", padx=(8, 0))
        self._banner_bar = bar
        self.banner.bind("<Configure>", lambda e: self._paint_banner(e.width))

    def _subtitle(self) -> str:
        meta = self.metadata
        bits = []
        # A private game's page shows the name the reader gave it and nothing
        # from VNDB that would say which novel it really is.
        if meta is not None and not self.card.hide_cover:
            if meta.alt_title and meta.alt_title != self.card.title:
                bits.append(meta.alt_title)
            if meta.developers:
                bits.append(", ".join(meta.developers[:2]))
            if meta.released and meta.released[:4].isdigit():
                bits.append(meta.released[:4])
        return "  ·  ".join(bits)

    def _paint_banner(self, width: int) -> None:
        if width < 50 or abs(width - self._banner_width) < 8:
            return
        self._banner_width = width
        canvas, palette = self.banner, self.palette
        picture = banner.render(self.cover, (width, BANNER_HEIGHT), palette,
                                hide=self.card.hide_cover)
        self._banner_image = _photo(picture, self)
        canvas.delete("all")
        canvas.create_image(0, 0, image=self._banner_image, anchor="nw")
        # The cover itself, sharp, sitting on its own blur.
        left, top = 28, 22
        canvas.create_rectangle(left - 1, top - 1, left + BANNER_COVER[0] + 1,
                                top + BANNER_COVER[1] + 1, outline=palette.border)
        canvas.create_image(left, top, image=self._cover_image, anchor="nw")
        x = left + BANNER_COVER[0] + 26
        canvas.create_text(x, 40, text=self.card.title, anchor="nw", fill=palette.text,
                           font=("Segoe UI", 24, "bold"), width=width - x - 30)
        subtitle = self._subtitle()
        if subtitle:
            canvas.create_text(x, 86, text=subtitle, anchor="nw", fill=palette.muted,
                               font=("Segoe UI", 10), width=width - x - 30)
        note = read_note(self.profile.id)
        if note:
            canvas.create_text(x, 112, text=f"Now reading: {note}", anchor="nw",
                               fill=palette.accent, font=("Segoe UI", 10, "bold"),
                               width=width - x - 30)
        canvas.create_window(x, top + BANNER_COVER[1] - 4, window=self._banner_bar, anchor="sw")

    # -- the numbers ----------------------------------------------------------------
    def _numbers(self) -> None:
        row = ttk.Frame(self, padding=(20, 12, 20, 0))
        row.pack(fill="x")
        current, longest = stats.streaks(self.entry)
        values = [
            ("PLAYED", stats.format_clock(self.entry.seconds) if self.entry.seconds
             else "Not yet"),
            ("LAST 7 DAYS", stats.format_clock(stats.last_days(self.entry, 7))),
            ("SESSIONS", str(self.entry.sessions)),
            ("LAST PLAYED", format_last_played(self.entry.last_played)),
            ("STREAK", f"{current} day{'s' if current != 1 else ''}" if current else "–"),
        ]
        for column, (name, value) in enumerate(values):
            row.columnconfigure(column, weight=1, uniform="tiles")
            tile = ttk.Frame(row, style="Card.TFrame", padding=(14, 10))
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
            ttk.Label(tile, text=name, style="StatName.TLabel").pack(anchor="w")
            ttk.Label(tile, text=value, style="StatValue.TLabel").pack(anchor="w", pady=(4, 0))
            tile.bind("<Configure>", lambda e, t=tile: _rewrap(t, e.width - 28))
        self._longest_streak = longest

    # -- Overview -------------------------------------------------------------------
    def _overview_tab(self, tab) -> None:
        tab.columnconfigure(0, weight=3)
        tab.columnconfigure(1, weight=2)
        heat = ttk.Frame(tab, style="Inner.TFrame")
        heat.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        head = ttk.Frame(heat, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Last six months", style="CardHeading.TLabel").pack(side="left")
        self.heat_readout = tk.StringVar(value="Point at a day to see it.")
        ttk.Label(head, textvariable=self.heat_readout, style="CardMuted.TLabel").pack(
            side="right")
        self.heat = tk.Canvas(heat, height=170, highlightthickness=0, borderwidth=0,
                              background=self.palette.surface)
        self.heat.pack(fill="x", pady=(10, 6))
        self.heat.bind("<Configure>", lambda _e: self._draw_heat())
        self.heat.bind("<Motion>", self._heat_hover)
        self.heat.bind("<Leave>", lambda _e: self.heat_readout.set(""))
        self._cells: list = []

        facts = ttk.Frame(heat, style="Inner.TFrame")
        facts.pack(fill="x", pady=(4, 0))
        current, longest = stats.streaks(self.entry)
        best = stats.best_day(self.entry)
        for label, value in (
            ("Current streak", f"{current} day{'s' if current != 1 else ''}"),
            ("Longest streak", f"{longest} day{'s' if longest != 1 else ''}"),
            ("Best day", f"{stats.format_clock(best[1])}  ·  {_day_text(best[0])}"
             if best else "–"),
        ):
            cell = ttk.Frame(facts, style="Inner.TFrame")
            cell.pack(side="left", padx=(0, 28))
            ttk.Label(cell, text=label, style="CardMuted.TLabel").pack(anchor="w")
            ttk.Label(cell, text=value, style="CardHeading.TLabel").pack(anchor="w")
        since = stats.history_since(self.entry)
        ttk.Label(heat, style="CardMuted.TLabel", wraplength=560, justify="left",
                  text=("Every day you play from now on shows up here." if since is None
                        else f"Counted day by day since {_day_text(since)}; earlier time "
                             "is in the total only.")).pack(anchor="w", pady=(10, 0))

        side = ttk.Frame(tab, style="Inner.TFrame")
        side.grid(row=0, column=1, sticky="nsew")
        self._progress_block(side)
        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=16)
        self._vndb_block(side)

    def _draw_heat(self) -> None:
        with contextlib.suppress(Exception):
            self._cells = chart.draw_heatmap(self.heat, stats.heatmap(self.entry, 26),
                                             self.palette)

    def _heat_hover(self, event) -> None:
        for cell in self._cells:
            if cell.x0 <= event.x <= cell.x1 and cell.y0 <= event.y <= cell.y1:
                played = stats.format_clock(cell.seconds) if cell.seconds else "nothing"
                self.heat_readout.set(f"{_day_text(cell.when, weekday=True)}: {played}")
                return

    def _progress_block(self, parent) -> None:
        head = ttk.Frame(parent, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="How far through", style="CardHeading.TLabel").pack(side="left")
        self.progress_text = tk.StringVar()
        ttk.Label(head, textvariable=self.progress_text, style="CardMuted.TLabel").pack(
            side="right")
        self.progress_bar = tk.Canvas(parent, height=10, highlightthickness=0,
                                      borderwidth=0, background=self.palette.surface)
        self.progress_bar.pack(fill="x", pady=(10, 6))
        self.progress_bar.bind("<Configure>", lambda _e: self._paint_progress())
        self.progress_note = tk.StringVar()
        ttk.Label(parent, textvariable=self.progress_note, style="CardMuted.TLabel",
                  wraplength=360, justify="left").pack(anchor="w")
        self._show_progress()

    def _show_progress(self) -> None:
        minutes = getattr(self.metadata, "length_minutes", None)
        self._progress = stats.progress(self.entry.seconds, minutes)
        if self._progress is not None:
            self.progress_text.set(self._progress.describe())
            self.progress_note.set("Your time next to the average VNDB readers logged - "
                                   "a guide, not a finish line.")
        elif not self.profile.vndb_id:
            self.progress_text.set("")
            self.progress_note.set("Link the game to VNDB to compare with other readers.")
        else:
            self.progress_text.set("")
            self.progress_note.set("VNDB has no average length for this one yet.")
        self._paint_progress()

    def _paint_progress(self) -> None:
        bar, palette = self.progress_bar, self.palette
        bar.delete("all")
        width = bar.winfo_width() or 300
        bar.create_rectangle(0, 0, width, 10, fill=chart.shade(palette, 0), outline="")
        progress = getattr(self, "_progress", None)
        if progress is not None and progress.bar > 0:
            bar.create_rectangle(0, 0, max(width * progress.bar, 4), 10,
                                 fill=palette.accent, outline="")

    # -- VNDB list ------------------------------------------------------------------
    def _vndb_block(self, parent) -> None:
        head = ttk.Frame(parent, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="On your VNDB list", style="CardHeading.TLabel").pack(side="left")
        if self.account is not None:
            who = ttk.Label(head, text=f"{self.account.username} · disconnect",
                            style="CardMuted.TLabel", cursor="hand2")
            who.pack(side="right")
            who.bind("<Button-1>", lambda _e: self._disconnect())

        self.status_var = tk.IntVar(value=0)
        self._last_status = 0
        row = ttk.Frame(parent, style="Inner.TFrame")
        row.pack(fill="x", pady=(12, 0))
        self.status_buttons = []
        for value, text in vndb_list.STATUSES.items():
            button = ttk.Radiobutton(row, text=text, value=value, variable=self.status_var,
                                     style="Page.Chip.Toolbutton",
                                     command=lambda v=value: self._status_clicked(v))
            button.pack(side="left", padx=(0, 4))
            self.status_buttons.append(button)

        row = ttk.Frame(parent, style="Inner.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="Rating", style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.rating_var = tk.StringVar(value="-")
        self.rating_box = ttk.Combobox(row, textvariable=self.rating_var, state="readonly",
                                       width=5, style="Card.TCombobox",
                                       values=["-", *[str(n) for n in range(10, 0, -1)]])
        self.rating_box.pack(side="left")
        self.rating_box.bind("<<ComboboxSelected>>", lambda _e: self._rating_chosen())

        self.vndb_note = tk.StringVar()
        ttk.Label(parent, textvariable=self.vndb_note, style="CardMuted.TLabel",
                  wraplength=360, justify="left").pack(anchor="w", pady=(10, 0))

        if not self.profile.vndb_id:
            self._lock_list("Link this game to VNDB first - then its status and your "
                            "rating can go to your list.")
        elif self.account is None:
            self._lock_list("Connect your VNDB account and what you pick here is saved "
                            "to your list.")
            ttk.Button(parent, text="Connect VNDB account…", style="Card.TButton",
                       command=self._connect).pack(anchor="w", pady=(8, 0))
        else:
            self._lock_list("Reading your list…")

    def _lock_list(self, why: str) -> None:
        for widget in (*self.status_buttons, self.rating_box):
            with contextlib.suppress(Exception):
                widget.state(["disabled"])
        self.vndb_note.set(why)

    def _unlock_list(self) -> None:
        for button in self.status_buttons:
            button.state(["!disabled"])
        self.rating_box.state(["!disabled", "readonly"])
        if self.account is not None and not self.account.can_write:
            self.vndb_note.set("This token can read your list but not change it. Make a "
                               "new one with “Write to my list” ticked.")
        else:
            self.vndb_note.set("Saved to your VNDB list as you pick.")

    def _show_entry(self, entry: vndb_list.ListEntry) -> None:
        self.status_var.set(entry.status or 0)
        self.rating_var.set(str(entry.rating) if entry.rating else "-")
        self._unlock_list()

    def _status_clicked(self, value: int) -> None:
        # Clicking the status that is already lit takes it off again.
        status = None if value == self._last_status else value
        self.status_var.set(status or 0)
        self._last_status = status or 0
        self._send(lambda: vndb_list.set_status(self.account, self.profile.vndb_id, status),
                   f"Saved: {vndb_list.STATUSES[status]}" if status else "Status cleared")

    def _rating_chosen(self) -> None:
        text = self.rating_var.get()
        rating = None if text == "-" else int(text)
        self._send(lambda: vndb_list.set_rating(self.account, self.profile.vndb_id, rating),
                   f"Saved: rated {rating}" if rating else "Rating cleared")

    def _send(self, action, done: str) -> None:
        self.vndb_note.set("Saving to VNDB…")

        def work():
            try:
                action()
                message = f"{done} - on your VNDB list."
            except (vndb_list.VNDBListError, ValueError) as exc:
                message = str(exc)
            self._later(lambda: self.vndb_note.set(message))

        threading.Thread(target=work, daemon=True).start()

    def _connect(self) -> None:
        if messagebox.askyesno(
            "Connect VNDB", vndb_list.TOKEN_HOWTO + "\n\nOpen vndb.org now?", parent=self,
        ):
            _open_url(vndb_list.TOKEN_PAGE)
        token = simpledialog.askstring("Connect VNDB", "Paste your VNDB token:", parent=self,
                                       show="•")
        if not token:
            return
        self.vndb_note.set("Checking the token with VNDB…")

        def work():
            try:
                account = vndb_list.connect(token)
                vndb_list.save_account(account)
            except vndb_list.VNDBListError as exc:
                message = str(exc)
                self._later(lambda: self.vndb_note.set(message))
                return
            self._later(self._connected)

        threading.Thread(target=work, daemon=True).start()

    def _connected(self) -> None:
        self.account = vndb_list.load_account()
        self.rebuild()

    def _disconnect(self) -> None:
        if messagebox.askyesno("VNDB", "Forget the VNDB token on this computer?\n"
                               "(It stays valid on VNDB until you delete it there.)",
                               parent=self):
            vndb_list.forget_account()
            self.account = None
            self.rebuild()

    # -- Routes & Notes ---------------------------------------------------------------
    def _journal_tab(self, tab) -> None:
        tab.columnconfigure(0, weight=1, uniform="journal")
        tab.columnconfigure(1, weight=1, uniform="journal")
        tab.rowconfigure(0, weight=1)

        left = ttk.Frame(tab, style="Inner.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        head = ttk.Frame(left, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Routes", style="CardHeading.TLabel").pack(side="left")
        self.routes_count = tk.StringVar()
        ttk.Label(head, textvariable=self.routes_count, style="CardMuted.TLabel").pack(
            side="right")
        self.routes_box = ttk.Frame(left, style="Inner.TFrame")
        self.routes_box.pack(fill="x", pady=(10, 0))
        add = ttk.Frame(left, style="Inner.TFrame")
        add.pack(fill="x", pady=(12, 0))
        self.new_route = tk.StringVar()
        entry = ttk.Entry(add, textvariable=self.new_route)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self._add_route())
        ttk.Button(add, text="Add route", style="Card.TButton",
                   command=self._add_route).pack(side="left", padx=(8, 0))
        ttk.Label(left, style="CardMuted.TLabel", wraplength=420, justify="left",
                  text="Tick a route when you finish it - Discord shows “Routes 2/5” "
                       "(unless the game is private). “Reading” puts it on your "
                       "activity as the route you are on.").pack(anchor="w", pady=(10, 0))
        self._show_routes()

        right = ttk.Frame(tab, style="Inner.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        head = ttk.Frame(right, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Notes", style="CardHeading.TLabel").pack(side="left")
        self.notes_state = tk.StringVar(value="Only on this computer, never on Discord.")
        ttk.Label(head, textvariable=self.notes_state, style="CardMuted.TLabel").pack(
            side="right")
        palette = self.palette
        self.notes = tk.Text(right, wrap="word", height=14, relief="flat", borderwidth=0,
                             background=theme._mix(palette.surface, palette.background, 0.5),
                             foreground=palette.text, insertbackground=palette.text,
                             selectbackground=palette.accent,
                             selectforeground=palette.accent_text,
                             font=("Segoe UI", 10), padx=12, pady=10, undo=True)
        self.notes.pack(fill="both", expand=True, pady=(10, 0))
        self.notes.insert("1.0", journal.load(self.profile.id).notes)
        self.notes.edit_modified(False)
        self.notes.bind("<<Modified>>", self._notes_changed)
        self._notes_job = None

    def _show_routes(self) -> None:
        for child in self.routes_box.winfo_children():
            child.destroy()
        record = journal.load(self.profile.id)
        done, total = record.progress()
        self.routes_count.set(f"{done} of {total} finished" if total else "")
        current = (read_note(self.profile.id) or "").lower()
        if not record.routes:
            ttk.Label(self.routes_box, text="No routes yet - add the ones this novel has.",
                      style="CardMuted.TLabel").pack(anchor="w")
            return
        for index, route in enumerate(record.routes):
            row = ttk.Frame(self.routes_box, style="Inner.TFrame")
            row.pack(fill="x", pady=2)
            var = tk.BooleanVar(value=route.done)
            ttk.Checkbutton(row, text=route.name, variable=var, style="Page.TCheckbutton",
                            command=lambda i=index, v=var: self._tick(i, v.get())).pack(
                side="left")
            ttk.Button(row, text="✕", width=3, style="Card.TButton",
                       command=lambda i=index: self._remove_route(i)).pack(side="right")
            ttk.Button(row, text="↓", width=3, style="Card.TButton",
                       command=lambda i=index: self._move_route(i, 1)).pack(side="right",
                                                                           padx=(0, 4))
            ttk.Button(row, text="↑", width=3, style="Card.TButton",
                       command=lambda i=index: self._move_route(i, -1)).pack(side="right",
                                                                            padx=(0, 4))
            reading = route.name.lower() == current
            ttk.Button(row, text="● Reading" if reading else "Reading",
                       style="Page.Accent.TButton" if reading else "Card.TButton",
                       command=lambda name=route.name: self._reading(name)).pack(
                side="right", padx=(0, 8))

    def _add_route(self) -> None:
        name = self.new_route.get().strip()
        if name:
            journal.add_route(self.profile.id, name)
            self.new_route.set("")
            self._show_routes()

    def _tick(self, index: int, done: bool) -> None:
        journal.set_done(self.profile.id, index, done)
        self._show_routes()

    def _remove_route(self, index: int) -> None:
        journal.remove_route(self.profile.id, index)
        self._show_routes()

    def _move_route(self, index: int, step: int) -> None:
        journal.move_route(self.profile.id, index, step)
        self._show_routes()

    def _reading(self, name: str) -> None:
        """This route is the one being read: the activity says so, now."""
        write_note(self.profile.id, name)
        with contextlib.suppress(Exception):
            self.app.load_note()
        self._show_routes()
        self._banner_width = 0
        self._paint_banner(self.banner.winfo_width())
        self.message.set(f"Discord now shows: {name}")

    def _notes_changed(self, _event=None) -> None:
        if not self.notes.edit_modified():
            return
        self.notes.edit_modified(False)
        self.notes_state.set("Saving…")
        if self._notes_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._notes_job)
        self._notes_job = self.after(600, self._save_notes)

    def _save_notes(self) -> None:
        self._notes_job = None
        journal.set_notes(self.profile.id, self.notes.get("1.0", "end-1c"))
        self.notes_state.set("Saved")

    def destroy(self) -> None:
        # Typed a note and closed the page within the half-second: keep it.
        if getattr(self, "_notes_job", None) is not None:
            with contextlib.suppress(Exception):
                self._save_notes()
        super().destroy()

    # -- Sessions ----------------------------------------------------------------------
    def _sessions_tab(self, tab) -> None:
        head = ttk.Frame(tab, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Every time you played", style="CardHeading.TLabel").pack(
            side="left")
        self.sessions_button = ttk.Button(head, text="Show all", style="Card.TButton",
                                          command=self._toggle_sessions)
        self.sessions_button.pack(side="right")
        holder = ttk.Frame(tab, style="Inner.TFrame")
        holder.pack(fill="both", expand=True, pady=(10, 0))
        self.sessions = ttk.Treeview(holder, columns=("day", "time", "counted", "wall"),
                                     show="headings", style="Page.Treeview", height=10,
                                     selectmode="none")
        for column, heading, width, anchor in (
            ("day", "Day", 160, "w"), ("time", "From – to", 160, "w"),
            ("counted", "Counted", 110, "e"), ("wall", "Game open", 110, "e"),
        ):
            self.sessions.heading(column, text=heading)
            self.sessions.column(column, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.sessions.yview)
        self.sessions.configure(yscrollcommand=scroll.set)
        self.sessions.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.sessions_note = tk.StringVar()
        ttk.Label(tab, textvariable=self.sessions_note, style="CardMuted.TLabel",
                  wraplength=800, justify="left").pack(anchor="w", pady=(10, 0))
        self._show_sessions()

    def _show_sessions(self) -> None:
        import datetime as _dt

        self.sessions.delete(*self.sessions.get_children())
        every = session_log.newest_first(self.profile.id)
        shown = every if self.all_sessions else every[:RECENT_SESSIONS]
        now = _dt.datetime.now()
        for session in shown:
            day, span, counted = session_log.describe(session, now)
            self.sessions.insert("", "end", values=(day, span, counted,
                                                    stats.format_clock(session.wall)))
        self.sessions_button.configure(text="Show recent" if self.all_sessions else "Show all")
        if len(every) <= RECENT_SESSIONS:
            self.sessions_button.state(["disabled"])
        if not every:
            self.sessions_note.set("Sessions are listed from this version on - play and "
                                   "the first one appears here.")
        else:
            self.sessions_note.set("“Counted” is the time with the game in front "
                                   "and you there; “Game open” is the whole stretch.")

    def _toggle_sessions(self) -> None:
        self.all_sessions = not self.all_sessions
        self._show_sessions()

    # -- About -------------------------------------------------------------------------
    def _about_tab(self, tab) -> None:
        self.about_box = tab
        self._show_about()

    def _show_about(self) -> None:
        tab, meta = self.about_box, self.metadata
        for child in tab.winfo_children():
            child.destroy()
        if meta is None:
            ttk.Label(tab, style="CardMuted.TLabel", wraplength=700, justify="left",
                      text="Link this game to VNDB and its description, developers and "
                           "tags show up here." if not self.profile.vndb_id else
                           "Fetching from VNDB…").pack(anchor="w")
            return
        facts = ttk.Frame(tab, style="Inner.TFrame")
        facts.pack(fill="x")
        rows = [("Original title", meta.alt_title if meta.alt_title != meta.title else None),
                ("Developer", ", ".join(meta.developers) or None),
                ("Released", meta.released),
                ("Length", meta.length),
                ("VNDB rating", f"{meta.rating} / 10" if meta.rating else None),
                ("Languages", ", ".join(meta.languages[:8]) or None)]
        for row, (label, value) in enumerate(r for r in rows if r[1]):
            ttk.Label(facts, text=label, style="CardMuted.TLabel").grid(
                row=row, column=0, sticky="nw", padx=(0, 18), pady=2)
            ttk.Label(facts, text=value, style="Card.TLabel", wraplength=640,
                      justify="left").grid(row=row, column=1, sticky="w", pady=2)

        text = about_text(meta.about, spoilers=self.show_spoilers)
        if text:
            short = len(text) > ABOUT_PREVIEW and not self.about_expanded
            shown = text[:ABOUT_PREVIEW].rsplit(" ", 1)[0] + "…" if short else text
            ttk.Label(tab, text=shown, style="Card.TLabel", wraplength=820,
                      justify="left").pack(anchor="w", pady=(16, 0))
            if len(text) > ABOUT_PREVIEW:
                more = ttk.Label(tab, text="Less" if self.about_expanded else "More",
                                 style="Page.Link.TLabel", cursor="hand2")
                more.pack(anchor="w", pady=(4, 0))
                more.bind("<Button-1>", lambda _e: self._toggle_about())

        adult = not self.card.hide_cover
        names, hidden = visible_tags(meta.tags, spoilers=self.show_spoilers, adult=adult)
        if names or hidden:
            head = ttk.Frame(tab, style="Inner.TFrame")
            head.pack(fill="x", pady=(18, 6))
            ttk.Label(head, text="Tags", style="CardHeading.TLabel").pack(side="left")
            if hidden or self.show_spoilers:
                toggle = ttk.Label(
                    head, style="Page.Link.TLabel", cursor="hand2",
                    text="Hide spoilers" if self.show_spoilers else
                    f"Show spoilers ({hidden})")
                toggle.pack(side="left", padx=(12, 0))
                toggle.bind("<Button-1>", lambda _e: self._toggle_spoilers())
            flow = tk.Text(tab, height=3, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0, background=self.palette.surface,
                           cursor="arrow")
            flow.pack(fill="x")
            for name in names:
                flow.window_create("end", window=ttk.Label(flow, text=name,
                                                           style="Page.Tag.TLabel"),
                                   padx=3, pady=3)
            flow.configure(state="disabled")
            flow.bind("<Configure>", lambda _e, f=flow: _fit_text_height(f))

    def _toggle_about(self) -> None:
        self.about_expanded = not self.about_expanded
        self._show_about()

    def _toggle_spoilers(self) -> None:
        self.show_spoilers = not self.show_spoilers
        self._show_about()

    # -- Screenshots ----------------------------------------------------------------
    def _screenshots_tab(self, tab) -> None:
        head = ttk.Frame(tab, style="Inner.TFrame")
        head.pack(fill="x")
        self.gallery_title = tk.StringVar()
        ttk.Label(head, textvariable=self.gallery_title, style="CardHeading.TLabel").pack(
            side="left")
        ttk.Button(head, text="Open folder", style="Card.TButton",
                   command=self._open_folder).pack(side="right")
        self.shot_actions = ttk.Frame(head, style="Inner.TFrame")
        for text, command in (("Share", self._share_shot), ("Copy", self._copy_shot),
                              ("Show in folder", self._show_shot), ("Open", self._open_shot)):
            ttk.Button(self.shot_actions, text=text, style="Card.TButton",
                       command=command).pack(side="right", padx=(0, 6))
        holder = ttk.Frame(tab, style="Inner.TFrame")
        holder.pack(fill="both", expand=True, pady=(12, 0))
        self.shelf_canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0,
                                      background=self.palette.surface)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.shelf_canvas.yview)
        self.shelf_canvas.configure(yscrollcommand=scroll.set)
        self.shelf_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.shelf = ttk.Frame(self.shelf_canvas, style="Inner.TFrame")
        self._shelf_window = self.shelf_canvas.create_window((0, 0), window=self.shelf,
                                                             anchor="nw")
        self.shelf.bind("<Configure>", lambda _e: self.shelf_canvas.configure(
            scrollregion=self.shelf_canvas.bbox("all")))
        self.shelf_canvas.bind("<Configure>", lambda e: (
            self.shelf_canvas.itemconfigure(self._shelf_window, width=e.width),
            self._layout_thumbs()))
        self._thumbs: list = []
        self._cols = 0
        self.refresh_gallery()

    def refresh_gallery(self) -> None:
        for child in self.shelf.winfo_children():
            child.destroy()
        self._thumbs, self._thumb_images = [], []
        self._selected_shot = None
        self.shot_actions.pack_forget()
        found = screenshots.shots(self.profile.id)
        count = len(found)
        self.gallery_title.set(f"Screenshots  {count}" if count else "Screenshots")
        if not found:
            hotkey = (self.app.config_data.screenshot_hotkey or "").strip()
            hint = (f"None yet. Press {hotkey} while playing and they land here."
                    if hotkey else "None yet.")
            label = ttk.Label(self.shelf, text=hint, style="CardMuted.TLabel")
            label.grid(row=0, column=0, sticky="w")
            self._thumbs.append(label)
            return
        palette = self.palette
        for path in found[:MAX_THUMBS]:
            picture = covers.tile(path, THUMB, title=path.stem, background=palette.background,
                                  foreground=palette.muted)
            image = _photo(picture, self)
            self._thumb_images.append(image)
            thumb = ttk.Label(self.shelf, image=image, style="Thumb.TLabel", padding=3,
                              cursor="hand2")
            thumb.bind("<Button-1>", lambda _e, p=path, t=thumb: self._select_shot(p, t))
            thumb.bind("<Double-1>", lambda _e, p=path: _open_file(p))
            thumb.bind("<Button-3>", lambda e, p=path, t=thumb: self._shot_menu(e, p, t))
            self._thumbs.append(thumb)
        if count > MAX_THUMBS:
            self._thumbs.append(ttk.Button(self.shelf, text=f"+ {count - MAX_THUMBS} more…",
                                           style="Card.TButton", command=self._open_folder))
        self._cols = 0
        self._layout_thumbs()

    def _layout_thumbs(self) -> None:
        width = max(self.shelf_canvas.winfo_width(), THUMB[0])
        cols = max(width // (THUMB[0] + 14), 1)
        if cols == self._cols:
            return
        self._cols = cols
        for index, widget in enumerate(self._thumbs):
            widget.grid(row=index // cols, column=index % cols, padx=(0, 8), pady=(0, 8),
                        sticky="nw")

    def _select_shot(self, path, thumb) -> None:
        for widget in self._thumbs:
            with contextlib.suppress(Exception):
                if str(widget.cget("style")).startswith("Thumb"):
                    widget.configure(style="Thumb.TLabel")
        thumb.configure(style="ThumbSelected.TLabel")
        self._selected_shot = path
        self.shot_actions.pack(side="right", padx=(0, 6))

    def _shot_menu(self, event, path, thumb) -> None:
        self._select_shot(path, thumb)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open", command=self._open_shot)
        menu.add_command(label="Show in folder", command=self._show_shot)
        menu.add_command(label="Copy", command=self._copy_shot)
        menu.add_command(label="Share…", command=self._share_shot)
        with contextlib.suppress(Exception):
            menu.tk_popup(event.x_root, event.y_root)

    def _open_shot(self) -> None:
        if self._selected_shot:
            _open_file(self._selected_shot)

    def _show_shot(self) -> None:
        if self._selected_shot:
            shell.show_in_folder(self._selected_shot)

    def _copy_shot(self) -> None:
        if not self._selected_shot:
            return
        try:
            shell.copy_image(self._selected_shot)
            self.message.set("Copied - paste it into Discord, a browser or anywhere else.")
        except Exception as exc:
            self.message.set(f"Could not copy it: {exc}")

    def _share_shot(self) -> None:
        if not self._selected_shot:
            return
        try:
            shell.share_image(self._selected_shot, shell.toplevel_hwnd(self),
                              title=f"{self.profile.title} - screenshot")
        except shell.ShareError as exc:
            log.info("share sheet unavailable: %s", exc)
            try:
                shell.copy_image(self._selected_shot)
                self.message.set("Windows would not open its share sheet here, so the "
                                 "picture is copied instead - paste it anywhere.")
            except Exception:
                self.message.set(f"Could not share it: {exc}")

    def _open_folder(self) -> None:
        folder = screenshots.gallery_dir(self.profile.id)
        folder.mkdir(parents=True, exist_ok=True)
        _open_file(folder)

    # -- Settings ----------------------------------------------------------------------
    def _settings_tab(self, tab) -> None:
        ttk.Label(tab, text="Launch with", style="CardHeading.TLabel").pack(anchor="w")
        row = ttk.Frame(tab, style="Inner.TFrame")
        row.pack(fill="x", pady=(12, 0))
        self.launch_var = tk.StringVar(value=launch_mode(self.profile))
        for value, text in LAUNCH_MODES.items():
            ttk.Radiobutton(row, text=text, value=value, variable=self.launch_var,
                            style="Page.Chip.Toolbutton",
                            command=self._launch_chosen).pack(side="left", padx=(0, 4))
        self.launch_note = tk.StringVar()
        ttk.Label(tab, textvariable=self.launch_note, style="CardMuted.TLabel",
                  wraplength=700, justify="left").pack(anchor="w", pady=(10, 0))
        self._describe_launch()

    def _describe_launch(self) -> None:
        mode = self.launch_var.get()
        config = self.app.config_data
        if mode == "locale-emulator":
            self.launch_note.set("Through Locale Emulator's Japanese profile.\n"
                                 f"{config.locale_emulator_path}")
        elif mode == "ntlea":
            self.launch_note.set(f"Through NTLEA, as Japanese.\n{config.ntlea_path}")
        else:
            self.launch_note.set("For Japanese VNs with garbled text, or that will not "
                                 "start: Play can go through Locale Emulator or NTLEA.")

    def _launch_chosen(self) -> None:
        mode = self.launch_var.get()
        config = self.app.config_data
        field, exe = {"locale-emulator": ("locale_emulator_path", "LEProc.exe"),
                      "ntlea": ("ntlea_path", "ntleas.exe")}.get(mode, (None, None))
        if field and not getattr(config, field):
            chosen = filedialog.askopenfilename(
                parent=self, title=f"Where is {exe}?",
                filetypes=[(exe, exe), ("Programs", "*.exe")])
            if not chosen:
                self.launch_var.set(launch_mode(self.profile))
                return
            setattr(config, field, chosen)
            with contextlib.suppress(Exception):
                config.save()
        self.profile.launch_with = mode
        self.app.library.save(self.profile)
        self._describe_launch()
        self.message.set(f"{self.profile.title} now starts with {LAUNCH_MODES[mode]}.")

    # -- background work ------------------------------------------------------------
    def _later(self, action) -> None:
        """Run ``action`` on Tk's thread, soon. Safe to call from any thread."""
        self._inbox.put(action)

    def _drain(self) -> None:
        while True:
            try:
                action = self._inbox.get_nowait()
            except queue.Empty:
                break
            _quietly(action)
        with contextlib.suppress(tk.TclError):
            self.after(100, self._drain)

    def _load_in_background(self) -> None:
        profile, account = self.profile, self.account
        if not profile.vndb_id:
            return
        cache_days = self.app.config_data.cache_days

        def work():
            try:
                metadata = VNDBClient(cache_days=cache_days).get(profile.vndb_id)
            except Exception:
                metadata = None
            if metadata is not None:
                self._later(lambda: self._got_metadata(metadata))
            if account is None:
                return
            try:
                entry = vndb_list.get_entry(account, profile.vndb_id)
            except vndb_list.VNDBListError as exc:
                message = str(exc)
                self._later(lambda: self.vndb_note.set(message))
                return
            self._later(lambda: self._got_entry(entry))

        threading.Thread(target=work, daemon=True).start()

    def _got_metadata(self, metadata) -> None:
        fresher = (self.metadata is None or self.metadata.to_dict() != metadata.to_dict())
        self.metadata = metadata
        self._show_progress()
        if fresher:
            self._show_about()
            self._banner_width = 0
            self._paint_banner(self.banner.winfo_width())

    def _got_entry(self, entry) -> None:
        self._last_status = entry.status or 0
        self._show_entry(entry)

    # -- actions --------------------------------------------------------------------
    def _play(self) -> None:
        with contextlib.suppress(Exception):
            self.app.tree.selection_set(self.profile.id)
        self.app.play_selected()

    def _relink(self) -> None:
        with contextlib.suppress(Exception):
            self.app.tree.selection_set(self.profile.id)
        self.app.relink_selected()
        fresh = self.app.library.get(self.profile.id)
        if fresh is not None and fresh.vndb_id != self.profile.vndb_id:
            self.profile = fresh
            self.rebuild()


def _day_text(day, *, weekday: bool = False) -> str:
    text = f"{day.day} {day.strftime('%b %Y')}"
    return f"{day.strftime('%a')} {text}" if weekday else text


def _fit_text_height(widget) -> None:
    """A Text holding tag chips grows to fit them, no scrollbar needed."""
    with contextlib.suppress(Exception):
        lines = widget.count("1.0", "end", "displaylines")
        widget.configure(height=max((lines[0] if lines else 1), 1) + 1)


def _rewrap(frame, width: int) -> None:
    """Let every label in ``frame`` wrap at ``width`` pixels."""
    if width < 40:
        return
    for child in frame.winfo_children():
        if isinstance(child, ttk.Label) and not child.cget("image"):
            with contextlib.suppress(tk.TclError):
                child.configure(wraplength=width)


def _quietly(action) -> None:
    try:
        action()
    except tk.TclError:
        pass  # the page was closed while VNDB was answering
    except Exception:
        log.debug("details page update failed", exc_info=True)


def _photo(picture, master):
    if picture is None:
        return ""
    try:
        from PIL import ImageTk

        return ImageTk.PhotoImage(picture, master=master)
    except Exception:  # pragma: no cover - Pillow ships in the .exe
        log.warning("cannot draw an image on the details page", exc_info=True)
        return ""


def _open_file(path) -> None:
    from .gui import open_path

    open_path(path)


def _open_url(url: str) -> None:
    from .gui import open_url

    open_url(url)
