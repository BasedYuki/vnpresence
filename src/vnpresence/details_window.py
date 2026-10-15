"""One game, on its own page: the cover, the numbers, and its screenshots.

Opened from Details…, Ctrl+I, or a right-click on a row or a cover. It reads
the same data as the list, through the same functions in ``library_view``, so
the two can never disagree about how long a game has been played.
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from tkinter import ttk

from . import covers, screenshots
from .library_view import card_for, details_lines, vndb_page
from .notes import read_note
from .playtime import Playtime
from .vndb import VNDBClient

log = logging.getLogger(__name__)

#: The cover on this page: big enough to look at, not so big the page scrolls.
BIG_COVER = (260, 369)
#: Screenshot thumbnails: 16:9, the shape most novels run in.
THUMB = (240, 135)
#: How many to show before "Open folder" is the better way to browse.
MAX_THUMBS = 24


class DetailsWindow(tk.Toplevel):
    def __init__(self, app, profile) -> None:
        super().__init__(app)
        self.app = app
        self.profile = profile
        self.title(profile.title)
        self.configure(background=app.palette.background)
        self.geometry("980x640")
        self.minsize(720, 480)
        self.transient(app)
        self._images: list = []  # Tk forgets images nothing holds on to
        self.bind("<Escape>", lambda _e: self.destroy())
        self._build()
        self.refresh_gallery()
        self.focus_set()

    # -- layout -----------------------------------------------------------
    def _build(self) -> None:
        app, profile = self.app, self.profile
        client = VNDBClient(cache_days=app.config_data.cache_days)
        metadata = client.peek(profile.vndb_id) if profile.vndb_id else None
        card = card_for(profile, Playtime().get(profile.id), metadata, app.config_data)

        page = ttk.Frame(self, padding=18)
        page.pack(fill="both", expand=True)

        top = ttk.Frame(page)
        top.pack(fill="x")

        # The cover, or the same plain card the grid uses for a private game.
        path = None if card.hide_cover else covers.cached(card.cover_url)
        picture = covers.tile(path, BIG_COVER, title=card.title,
                              background=app.palette.surface, foreground=app.palette.muted)
        image = _photo(picture, self)
        ttk.Label(top, image=image).pack(side="left", anchor="n")

        info = ttk.Frame(top, padding=(20, 0, 0, 0))
        info.pack(side="left", fill="both", expand=True, anchor="n")
        ttk.Label(info, text=card.title, style="Title.TLabel",
                  wraplength=560, justify="left").pack(anchor="w")

        facts = ttk.Frame(info)
        facts.pack(anchor="w", pady=(14, 0))
        for row, (label, value) in enumerate(details_lines(card)):
            ttk.Label(facts, text=label, style="Fact.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 18), pady=2)
            ttk.Label(facts, text=value).grid(row=row, column=1, sticky="w", pady=2)

        note = read_note(profile.id)
        if note:
            ttk.Label(info, text=f"Route / chapter:  {note}", style="Muted.TLabel",
                      wraplength=560, justify="left").pack(anchor="w", pady=(12, 0))

        buttons = ttk.Frame(info)
        buttons.pack(anchor="w", pady=(18, 0))
        ttk.Button(buttons, text="▶  Play", style="Accent.TButton",
                   command=self._play).pack(side="left")
        ttk.Button(buttons, text="Screenshots folder",
                   command=self._open_folder).pack(side="left", padx=8)
        url, linked = vndb_page(profile)
        ttk.Button(buttons, text="Open on VNDB" if linked else "Search on VNDB",
                   command=lambda: _open_url(url)).pack(side="left")

        hotkey = (app.config_data.screenshot_hotkey or "").strip()
        if hotkey:
            ttk.Label(info, text=f"Press {hotkey} while playing to add a screenshot here.",
                      style="Muted.TLabel").pack(anchor="w", pady=(10, 0))

        ttk.Separator(page, orient="horizontal").pack(fill="x", pady=16)

        self.gallery_title = tk.StringVar()
        ttk.Label(page, textvariable=self.gallery_title,
                  style="Heading.TLabel").pack(anchor="w")

        # The gallery scrolls on its own, so a hundred screenshots never push
        # the cover and the Play button off the page.
        holder = ttk.Frame(page)
        holder.pack(fill="both", expand=True, pady=(8, 0))
        self.canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0,
                                background=app.palette.background)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.shelf = ttk.Frame(self.canvas)
        self._shelf_window = self.canvas.create_window((0, 0), window=self.shelf, anchor="nw")
        self.shelf.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda _e: self._layout())
        self._thumbs: list = []
        self._cols = 0
        self._images.append(image)

    # -- the gallery --------------------------------------------------------
    def refresh_gallery(self) -> None:
        for child in self.shelf.winfo_children():
            child.destroy()
        self._thumbs = []
        self._images = self._images[:1]  # keep the cover, drop old thumbnails
        found = screenshots.shots(self.profile.id)
        count = len(found)
        self.gallery_title.set(f"Screenshots ({count})" if count else "Screenshots")
        if not found:
            hotkey = (self.app.config_data.screenshot_hotkey or "").strip()
            hint = (f"None yet. Press {hotkey} while reading and they land here."
                    if hotkey else "None yet.")
            label = ttk.Label(self.shelf, text=hint, style="Muted.TLabel")
            label.grid(row=0, column=0, sticky="w")
            self._thumbs.append(label)
            return
        for path in found[:MAX_THUMBS]:
            picture = covers.tile(path, THUMB, title=path.stem,
                                  background=self.app.palette.surface,
                                  foreground=self.app.palette.muted)
            image = _photo(picture, self)
            self._images.append(image)
            cell = ttk.Frame(self.shelf)
            thumb = ttk.Label(cell, image=image, cursor="hand2")
            thumb.pack()
            ttk.Label(cell, text=path.stem, style="Muted.TLabel").pack(pady=(4, 0))
            for widget in (cell, thumb):
                widget.bind("<Button-1>", lambda _e, p=path: _open_file(p))
            self._thumbs.append(cell)
        if count > MAX_THUMBS:
            more = ttk.Button(self.shelf, text=f"+ {count - MAX_THUMBS} more…",
                              command=self._open_folder)
            self._thumbs.append(more)
        self._cols = 0
        self._layout()

    def _layout(self) -> None:
        width = max(self.canvas.winfo_width(), THUMB[0])
        self.canvas.itemconfigure(self._shelf_window, width=width)
        cols = max(width // (THUMB[0] + 16), 1)
        if cols == self._cols:
            return
        self._cols = cols
        for index, cell in enumerate(self._thumbs):
            cell.grid(row=index // cols, column=index % cols, padx=8, pady=8, sticky="n")

    # -- actions ------------------------------------------------------------
    def _play(self) -> None:
        with contextlib.suppress(Exception):
            self.app.tree.selection_set(self.profile.id)
        self.app.play_selected()

    def _open_folder(self) -> None:
        folder = screenshots.gallery_dir(self.profile.id)
        folder.mkdir(parents=True, exist_ok=True)
        _open_file(folder)


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
