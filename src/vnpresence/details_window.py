"""One game, on its own page: how long, how far, your VNDB list, and the
screenshots.

Opened from Details…, Ctrl+I, or a right-click on a row or a cover. Laid out
as cards: the game and its numbers across the top, your VNDB status and how
it launches beside a chart of when you played, and the gallery underneath.

Everything slow - VNDB's average length, your list entry, saving a status -
happens on a background thread and lands on the page when it is back, so
the page itself always opens at once, offline included.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import chart, covers, screenshots, shell, stats, vndb_list
from .launcher import LAUNCH_MODES, launch_mode
from .library_view import card_for, format_last_played, vndb_page
from .notes import read_note
from .playtime import Playtime
from .vndb import VNDBClient

log = logging.getLogger(__name__)

#: The cover on this page.
BIG_COVER = (150, 213)
#: Screenshot thumbnails: 16:9, the shape most novels run in.
THUMB = (200, 113)
#: How many to show before "Open folder" is the better way to browse.
MAX_THUMBS = 24
#: Ranges the chart offers.
RANGES = {"30 days": ("daily", 30), "12 weeks": ("weekly", 12)}


class DetailsWindow(tk.Toplevel):
    def __init__(self, app, profile) -> None:
        super().__init__(app)
        self.app = app
        self.profile = profile
        self.title(profile.title)
        self.geometry("1120x820")
        self.minsize(860, 560)
        self.transient(app)
        self._images: list = []  # Tk forgets images nothing holds on to
        self._thumb_images: list = []
        self._selected_shot = None
        self.metadata = None
        self.account = vndb_list.load_account()
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
        """Draw it again - after a theme change, or a new VNDB link."""
        for child in self.winfo_children():
            child.destroy()
        self._images, self._thumb_images = [], []
        self._build()
        self._load_in_background()

    def _build(self) -> None:
        app, profile = self.app, self.profile
        palette = app.palette
        self.configure(background=palette.background)
        client = VNDBClient(cache_days=app.config_data.cache_days)
        self.metadata = client.peek(profile.vndb_id) if profile.vndb_id else None
        self.entry = Playtime().get(profile.id)
        card = card_for(profile, self.entry, self.metadata, app.config_data)

        # The page scrolls as a whole: on a small screen nothing is cut off.
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        self.page_canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0,
                                     background=palette.background)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.page_canvas.yview)
        self.page_canvas.configure(yscrollcommand=scroll.set)
        self.page_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        page = self.page = ttk.Frame(self.page_canvas, padding=18)
        self._page_window = self.page_canvas.create_window((0, 0), window=page, anchor="nw")
        page.bind("<Configure>", lambda _e: self.page_canvas.configure(
            scrollregion=self.page_canvas.bbox("all")))
        self.page_canvas.bind("<Configure>", lambda e: self.page_canvas.itemconfigure(
            self._page_window, width=e.width))
        self.bind_all_wheel()

        page.columnconfigure(0, weight=5, uniform="cols")
        page.columnconfigure(1, weight=7, uniform="cols")

        self._hero(page, card).grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))
        right = ttk.Frame(page)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))
        self._stat_tiles(right, card)
        self._progress_card(right)

        left = ttk.Frame(page)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))
        self._vndb_card(left)
        self._launch_card(left)
        self._chart_card(page).grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))

        self._gallery_card(page).grid(row=2, column=0, columnspan=2, sticky="nsew")

        self.message = tk.StringVar()
        ttk.Label(page, textvariable=self.message, style="Muted.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.refresh_gallery()

    def bind_all_wheel(self) -> None:
        def wheel(event):
            if getattr(event, "num", None) == 4:
                step = -3
            elif getattr(event, "num", None) == 5:
                step = 3
            else:
                step = -int(event.delta / 40) or (-1 if event.delta > 0 else 1)
            with contextlib.suppress(Exception):
                self.page_canvas.yview_scroll(step, "units")

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind(sequence, wheel)
            self.page_canvas.bind(sequence, wheel)

    @staticmethod
    def _card(parent, padding=16) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Card.TFrame", padding=padding)
        return frame

    # -- the top row ------------------------------------------------------------
    def _hero(self, parent, card) -> ttk.Frame:
        box = self._card(parent)
        palette = self.app.palette
        path = None if card.hide_cover else covers.cached(card.cover_url)
        picture = covers.tile(path, BIG_COVER, title=card.title,
                              background=palette.background, foreground=palette.muted)
        image = _photo(picture, self)
        self._images.append(image)
        ttk.Label(box, image=image, style="Card.TLabel").pack(side="left", anchor="n")

        info = ttk.Frame(box, style="Inner.TFrame", padding=(16, 0, 0, 0))
        info.pack(side="left", fill="both", expand=True, anchor="n")
        # Long titles and paths wrap to whatever width the card has.
        info.bind("<Configure>", lambda e: _rewrap(info, e.width - 20))
        ttk.Label(info, text=card.title, style="CardTitle.TLabel", wraplength=300,
                  justify="left").pack(anchor="w")
        if self.profile.path:
            ttk.Label(info, text=self.profile.path, style="CardMuted.TLabel", wraplength=300,
                      justify="left").pack(anchor="w", pady=(2, 0))
        alt = getattr(self.metadata, "alt_title", None)
        if alt and alt != card.title:
            ttk.Label(info, text=alt, style="CardMuted.TLabel", wraplength=300,
                      justify="left").pack(anchor="w", pady=(2, 0))

        url, linked = vndb_page(self.profile)
        chips = ttk.Frame(info, style="Inner.TFrame")
        chips.pack(anchor="w", pady=(12, 0))
        ttk.Button(chips, text=f"VNDB {self.profile.vndb_id}" if linked else "Search on VNDB",
                   style="Card.TButton", command=lambda: _open_url(url)).pack(side="left")
        ttk.Button(chips, text="▶  Play", style="Accent.TButton",
                   command=self._play).pack(side="left", padx=(8, 0))

        note = read_note(self.profile.id)
        if note:
            ttk.Label(info, text=f"Route / chapter: {note}", style="CardMuted.TLabel",
                      wraplength=300, justify="left").pack(anchor="w", pady=(10, 0))
        if not linked:
            link = ttk.Label(info, text="Link to VNDB…", style="Link.TLabel",
                             cursor="hand2")
            link.pack(anchor="w", pady=(10, 0))
            link.bind("<Button-1>", lambda _e: self._relink())
        return box

    def _stat_tiles(self, parent, card) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x")
        values = (
            ("TOTAL PLAYED", stats.format_clock(self.entry.seconds) if self.entry.seconds
             else "Not yet"),
            ("LAST 7 DAYS", stats.format_clock(stats.last_days(self.entry, 7))),
            ("SESSIONS", str(self.entry.sessions)),
            ("LAST PLAYED", format_last_played(self.entry.last_played)),
        )
        for column, (name, value) in enumerate(values):
            row.columnconfigure(column, weight=1, uniform="tiles")
            tile = self._card(row, padding=(14, 10))
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
            ttk.Label(tile, text=name, style="StatName.TLabel").pack(anchor="w")
            ttk.Label(tile, text=value, style="StatValue.TLabel").pack(anchor="w", pady=(4, 0))
            tile.bind("<Configure>", lambda e, t=tile: _rewrap(t, e.width - 28))

    def _progress_card(self, parent) -> None:
        box = self._card(parent)
        box.pack(fill="x", pady=(12, 0))
        head = ttk.Frame(box, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Progress", style="CardHeading.TLabel").pack(side="left")
        self.progress_text = tk.StringVar()
        ttk.Label(head, textvariable=self.progress_text, style="CardMuted.TLabel").pack(
            side="right")
        self.progress_bar = tk.Canvas(box, height=8, highlightthickness=0, borderwidth=0,
                                      background=self.app.palette.surface)
        self.progress_bar.pack(fill="x", pady=(10, 6))
        self.progress_bar.bind("<Configure>", lambda _e: self._paint_progress())
        self.progress_note = tk.StringVar()
        ttk.Label(box, textvariable=self.progress_note, style="CardMuted.TLabel",
                  wraplength=560, justify="left").pack(anchor="w")
        self._show_progress()

    def _show_progress(self) -> None:
        minutes = getattr(self.metadata, "length_minutes", None)
        self._progress = stats.progress(self.entry.seconds, minutes)
        if self._progress is not None:
            self.progress_text.set(self._progress.describe())
            self.progress_note.set("Compared with the average length on VNDB. Your reading "
                                   "speed and routes change it.")
        elif not self.profile.vndb_id:
            self.progress_text.set("")
            self.progress_note.set("Link this game to VNDB to compare with how long "
                                   "other readers took.")
        else:
            self.progress_text.set("")
            self.progress_note.set("VNDB has no average length for this one yet.")
        self._paint_progress()

    def _paint_progress(self) -> None:
        bar, palette = self.progress_bar, self.app.palette
        bar.delete("all")
        width = bar.winfo_width() or 400
        bar.create_rectangle(0, 0, width, 8, fill=palette.border, outline="")
        progress = getattr(self, "_progress", None)
        if progress is not None and progress.bar > 0:
            bar.create_rectangle(0, 0, max(width * progress.bar, 3), 8,
                                 fill=palette.accent, outline="")

    # -- VNDB list ----------------------------------------------------------------
    def _vndb_card(self, parent) -> None:
        box = self._card(parent)
        box.pack(fill="x")
        self.vndb_box = box
        head = ttk.Frame(box, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Your VNDB list", style="CardHeading.TLabel").pack(side="left")
        if self.account is not None:
            who = ttk.Label(head, text=f"{self.account.username} · disconnect",
                            style="CardMuted.TLabel", cursor="hand2")
            who.pack(side="right")
            who.bind("<Button-1>", lambda _e: self._disconnect())

        self.status_var = tk.IntVar(value=0)
        self._last_status = 0
        row = ttk.Frame(box, style="Inner.TFrame")
        row.pack(fill="x", pady=(12, 0))
        ttk.Label(row, text="Status", style="Card.TLabel", width=8).pack(side="left")
        self.status_buttons = []
        for value, text in vndb_list.STATUSES.items():
            button = ttk.Radiobutton(row, text=text, value=value, variable=self.status_var,
                                     style="Chip.Toolbutton",
                                     command=lambda v=value: self._status_clicked(v))
            button.pack(side="left", padx=(0, 4))
            self.status_buttons.append(button)

        row = ttk.Frame(box, style="Inner.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="Rating", style="Card.TLabel", width=8).pack(side="left")
        self.rating_var = tk.StringVar(value="-")
        self.rating_box = ttk.Combobox(row, textvariable=self.rating_var, state="readonly",
                                       width=6, style="Card.TCombobox",
                                       values=["-", *[str(n) for n in range(10, 0, -1)]])
        self.rating_box.pack(side="left")
        self.rating_box.bind("<<ComboboxSelected>>", lambda _e: self._rating_chosen())

        self.vndb_note = tk.StringVar()
        ttk.Label(box, textvariable=self.vndb_note, style="CardMuted.TLabel",
                  wraplength=380, justify="left").pack(anchor="w", pady=(10, 0))

        if not self.profile.vndb_id:
            self._lock_list("Link this game to VNDB first - then its status and your "
                            "rating can go to your list.")
        elif self.account is None:
            self._lock_list("Connect your VNDB account and the status and rating you "
                            "pick here are saved to your VNDB list.")
            ttk.Button(box, text="Connect VNDB account…", style="Card.TButton",
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
            self.vndb_note.set("Status and rating are sent to your VNDB list.")

    def _show_entry(self, entry: vndb_list.ListEntry) -> None:
        self.status_var.set(entry.status or 0)
        self.rating_var.set(str(entry.rating) if entry.rating else "-")
        self._unlock_list()

    def _status_clicked(self, value: int) -> None:
        # Clicking the status that is already lit takes it off again.
        previous = getattr(self, "_last_status", 0)
        status = None if value == previous else value
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

    # -- launch with ----------------------------------------------------------------
    def _launch_card(self, parent) -> None:
        box = self._card(parent)
        box.pack(fill="x", pady=(16, 0))
        ttk.Label(box, text="Launch with", style="CardHeading.TLabel").pack(anchor="w")
        row = ttk.Frame(box, style="Inner.TFrame")
        row.pack(fill="x", pady=(12, 0))
        self.launch_var = tk.StringVar(value=launch_mode(self.profile))
        for value, text in LAUNCH_MODES.items():
            ttk.Radiobutton(row, text=text, value=value, variable=self.launch_var,
                            style="Chip.Toolbutton",
                            command=self._launch_chosen).pack(side="left", padx=(0, 4))
        self.launch_note = tk.StringVar()
        ttk.Label(box, textvariable=self.launch_note, style="CardMuted.TLabel",
                  wraplength=380, justify="left").pack(anchor="w", pady=(10, 0))
        self._describe_launch()

    def _describe_launch(self) -> None:
        mode = self.launch_var.get()
        config = self.app.config_data
        if mode == "locale-emulator":
            where = config.locale_emulator_path
            self.launch_note.set(f"Through Locale Emulator's Japanese profile.\n{where}")
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

    # -- the chart ------------------------------------------------------------------
    def _chart_card(self, parent) -> ttk.Frame:
        box = self._card(parent)
        head = ttk.Frame(box, style="Inner.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Time played", style="CardHeading.TLabel").pack(side="left")
        self.range_var = tk.StringVar(value="30 days")
        for text in reversed(list(RANGES)):
            ttk.Radiobutton(head, text=text, value=text, variable=self.range_var,
                            style="Chip.Toolbutton", command=self._draw_chart).pack(
                side="right", padx=(4, 0))
        self.chart = tk.Canvas(box, height=230, highlightthickness=0, borderwidth=0,
                               background=self.app.palette.surface)
        self.chart.pack(fill="both", expand=True, pady=(10, 4))
        self.chart.bind("<Configure>", lambda _e: self._draw_chart())
        since = stats.history_since(self.entry)
        if since is None:
            text = ("Every session from now on shows up here, day by day. Time from "
                    "before this version only counts in the total.")
        else:
            text = (f"History since {since.day} {since.strftime('%b %Y')}. Time read "
                    "before that only counts in the total.")
        ttk.Label(box, text=text, style="CardMuted.TLabel", wraplength=560,
                  justify="left").pack(anchor="w")
        return box

    def _draw_chart(self) -> None:
        kind, count = RANGES.get(self.range_var.get(), ("daily", 30))
        if kind == "weekly":
            points = stats.weekly(self.entry, count)
        else:
            points = stats.daily(self.entry, count)
        with contextlib.suppress(Exception):
            chart.draw(self.chart, points, self.app.palette, weekly=kind == "weekly")

    # -- the gallery ----------------------------------------------------------------
    def _gallery_card(self, parent) -> ttk.Frame:
        box = self._card(parent)
        head = ttk.Frame(box, style="Inner.TFrame")
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
        self.shelf = ttk.Frame(box, style="Inner.TFrame")
        self.shelf.pack(fill="x", pady=(12, 0))
        self.shelf.bind("<Configure>", lambda _e: self._layout_thumbs())
        self._thumbs: list = []
        self._cols = 0
        return box

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
        palette = self.app.palette
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
        width = max(self.shelf.winfo_width(), THUMB[0])
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
            # Second best, and nearly as quick: the picture, ready to paste.
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
        self.metadata = metadata
        self._show_progress()

    def _got_entry(self, entry) -> None:
        self._last_status = entry.status or 0
        self._show_entry(entry)

    # -- actions ----------------------------------------------------------------------
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
