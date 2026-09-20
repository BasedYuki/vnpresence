# Showing the chapter or route you are on

VNPresence can show where you are in a novel:

```
Playing Muv-Luv Alternative
┌────────┐  Chapter 3 - Ayamine route
│ cover  │  Very long (> 50h) • 2011 • 12h 40m read
└─────(◍)┘  01:23 elapsed
```

There is no standard way to get that out of a visual novel, so there are four
ways to put it there, from "works everywhere, you type it" to "the game tells
us". Pick the first one on this list that applies to your game.

---

## 1. Type it (works with every game)

```bash
vnpresence note muv-luv "Chapter 3 - Ayamine route"
```

Or the **Route / chapter** box in the window. A running session picks the change
up within one update - about fifteen seconds - so you can set it as you go.

That box is also the integration point for everything below: **anything that
writes to the note file changes the presence.**

| | |
|---|---|
| Windows | `%APPDATA%\VNPresence\notes\<game id>.txt` |
| Linux | `~/.config/vnpresence/notes/<game id>.txt` |

One line of text, UTF-8. Write it from a script, a mod, a hotkey, anything -
VNPresence re-reads it on every update and never writes to it while a session is
running, so nothing is lost in a race.

---

## 2. The game's own title bar (no code)

A minority of visual novels put the chapter in their window title. For those,
one line in the game's profile is the whole feature:

```yaml
# %APPDATA%\VNPresence\games\some-vn.yaml
title: Some VN
path: D:\VN\SomeVN\game.exe
chapter_pattern: "Chapter \\d+"
```

Every update, the pattern is matched against the game's window title. The first
capture group becomes the status line, or the whole match when there are no
groups:

| Title bar | `chapter_pattern` | Shows |
|---|---|---|
| `Some VN - Chapter 3` | `Chapter \d+` | `Chapter 3` |
| `Some VN [Route: Ayamine]` | `Route: (.+?)\]` | `Ayamine` |
| `Some VN - 第三章` | `第.章` | `第三章` |

To find out what your game writes there, start it and run:

```bash
vnpresence emulators    # lists window titles it can see
```

A pattern that does not compile is ignored with a warning, not a crash. Windows
only - reading another program's title bar needs the Windows API.

---

## 3. A Ren'Py game (a dozen lines, works properly)

Ren'Py games can say exactly where they are, because Ren'Py knows. Drop this
into the game's `game/` folder as `vnpresence.rpy`:

```renpy
# vnpresence.rpy - tells VNPresence which label is playing.
# Put this in the game's game/ folder. Change GAME_ID to the id
# `vnpresence list` shows for this game.
init python:
    import os

    GAME_ID = "some-vn"

    def _vnpresence_note_path():
        base = os.environ.get("VNPRESENCE_HOME")
        if not base:
            if renpy.windows:
                base = os.path.join(os.environ.get("APPDATA", ""), "VNPresence")
            else:
                base = os.path.expanduser("~/.config/vnpresence")
        return os.path.join(base, "notes", GAME_ID + ".txt")

    def _vnpresence_write(text):
        try:
            path = _vnpresence_note_path()
            directory = os.path.dirname(path)
            if not os.path.isdir(directory):
                os.makedirs(directory)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text[:128])
        except Exception:
            pass  # never let this break the game

    def _vnpresence_label(name, abnormal):
        # Only labels meant to be seen: rename the ones you want shown, or
        # keep a dict of label -> pretty name here.
        pretty = {
            "chapter_01": "Chapter 1",
            "ayamine_route": "Ayamine route",
        }
        if name in pretty:
            _vnpresence_write(pretty[name])

    config.label_callback = _vnpresence_label
```

Set `GAME_ID` to what `vnpresence list` calls the game, fill in the `pretty`
dict with the labels you care about, and the presence follows the story on its
own. Nothing is written except that one text file, and every error is swallowed
- a mod that can crash the game is not worth having.

---

## 4. A text hooker (Textractor and friends)

If you already read with [Textractor](https://github.com/Artikash/Textractor),
it knows the current line of dialogue. An extension that writes a *derived*
value - a chapter name, a route, a scene number - to the note file above makes
that show up in the presence.

**Do not write the dialogue itself.** It is spoilers for everyone on your friend
list, and in a good many visual novels it is not something you want on your
profile at all. Derive something, or use one of the options above.

---

## What VNPresence will not do

**Read the game's memory.** Finding where a chapter number lives in RAM is
per-game, per-version reverse engineering, it breaks with every patch, and it
looks exactly like the things antivirus software exists to stop.

**Unpickle Ren'Py saves.** Ren'Py's save format is a Python pickle. Loading one
runs whatever is inside it, which is fine for the game that wrote it and not
fine for a program opening someone else's files.

**Guess from playtime.** VNPresence used to estimate a percentage from reading
time against VNDB's average. It was removed: reading speeds vary enormously,
routes get skipped, and a number that confident should not be a guess. The
reading time it shows now is measured, not estimated.

---

## Where the chapter comes from, in order

When more than one of these has something to say, the most informed wins:

0. **A pause.** While you are working in another window the line reads
   `Paused`, and while nobody has touched anything for a long time it reads
   `Idle` - or it keeps the chapter and marks it: `Chapter 3 - Ayamine route
   (paused)`. Everything below applies again the moment you come back.
1. **The note you typed** - you know better than anything automatic.
2. **`chapter_pattern`** - the game's own title bar.
3. **A state plugin** - see [writing-plugins.md](writing-plugins.md).
4. `status_text` in the profile, then `Reading`.
