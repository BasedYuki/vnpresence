# VNPresence

Discord Rich Presence for visual novels. Launch a VN through VNPresence and your
Discord profile shows the title, the cover art, how long you have been reading,
and a link to its VNDB page - the way a normal game does.

```
Playing a Visual Novel
┌────────┐  Steins;Gate
│ cover  │  Reading
│  art   │  01:24:07 elapsed
└────────┘  [ View on VNDB ]
```

- Cover art and descriptions come from [VNDB](https://vndb.org) automatically
- Auto-detect mode picks up games you start from Steam or a shortcut
- Adding a game is one line of YAML - or two clicks in the window
- Per-game privacy, with 18+ titles hidden by default
- A plugin API for anything the defaults do not cover
- MIT licensed, no telemetry, nothing phoning home except VNDB

---

## Table of contents

1. [Requirements](#1-requirements)
2. [Install](#2-install)
3. [Usage](#3-usage)
4. [Adding visual novels](#4-adding-visual-novels)
5. [Discord application / client id](#5-discord-application--client-id)
6. [What the presence looks like](#6-what-the-presence-looks-like)
7. [Privacy](#7-privacy)
8. [Plugins](#8-plugins)
9. [Troubleshooting](#9-troubleshooting)
10. [Contributing](#10-contributing)

---

## 1. Requirements

| | |
|---|---|
| OS | Windows 10/11 (primary). Linux/macOS work for the CLI; Wine/Proton launching is untested. |
| Discord | The **desktop app**, running and logged in. The browser version has no local RPC socket. |
| Python | Only if you install from source - 3.9 or newer. The `.exe` release bundles it. |
| Internet | Only for VNDB lookups. Results are cached, so you can play offline afterwards. |

Discord setting: **Settings → Activity Privacy → "Share your detected activities
with others"** must be on, or nothing shows up.

## 2. Install

### Option A - the ready-made .exe (recommended)

1. Download `VNPresence.exe` from the [Releases page](https://github.com/BasedYuki/vnpresence/releases).
2. Put it anywhere and run it. No installer, no Python.

### Option B - from PyPI

```bash
pip install vnpresence
```

### Option C - from source

```bash
git clone https://github.com/BasedYuki/vnpresence.git
cd vnpresence
pip install -e ".[dev]"
```

## 3. Usage

Double-click the `.exe` to get the window: pick a game, press **Play**.

Everything is available from the command line too:

```bash
vnpresence add "D:\VN\Steins Gate\sg.exe"   # add a game (searches VNDB for you)
vnpresence list                             # what is in your library
vnpresence play steins-gate                 # launch it and publish the presence
vnpresence play steins-gate --attach        # attach to a game that is already open
vnpresence watch -b                         # auto-detect games, in the background
vnpresence status                           # is a background watcher running?
vnpresence stop                             # stop it
vnpresence search "muv luv"                 # look up VNDB ids
vnpresence doctor                           # check Discord, VNDB, config, paths
vnpresence plugins                          # list active plugins
vnpresence gui                              # open the window
```

VNPresence stays in the foreground while you read, updates the presence every 15
seconds, and clears it the moment the game closes. Press `Ctrl+C` (or **Stop** in
the window) to end the session early.

### Where your data lives

| | Windows | Linux |
|---|---|---|
| Config | `%APPDATA%\VNPresence\config.yaml` | `~/.config/vnpresence/config.yaml` |
| Games | `%APPDATA%\VNPresence\games\*.yaml` | `~/.config/vnpresence/games/*.yaml` |
| VNDB cache | `%APPDATA%\VNPresence\cache\` | `~/.cache/vnpresence/` |

Set `VNPRESENCE_HOME` to keep everything in one portable folder next to the `.exe`.

## 4. Adding visual novels

### The easy way

```bash
vnpresence add "D:\VN\Clannad\Clannad.exe"
```

VNPresence searches VNDB with the file name, shows you the matches, and writes a
profile. That is all most games need.

### The profile file

Each game is one small YAML file in the games folder. Adding support for a new
visual novel means writing this file - no code, no rebuild:

```yaml
# %APPDATA%\VNPresence\games\steins-gate.yaml
title: Steins;Gate
path: D:\VN\Steins Gate\sg.exe
vndb_id: v2002
privacy: auto
```

Every key it accepts:

| Key | Default | What it does |
|---|---|---|
| `title` | *(required)* | The line shown under "Playing a Visual Novel" |
| `path` | - | The executable to launch |
| `args` | `[]` | Arguments passed to it |
| `working_dir` | folder of `path` | Working directory (some engines need it) |
| `vndb_id` | - | `v2002`, `2002` or a VNDB URL - drives cover art and info |
| `image_url` | from VNDB | Your own cover image (any public https URL) |
| `description` | from VNDB | Overrides the VNDB description |
| `process_names` | `[]` | The **real** process name if a launcher starts the game |
| `launcher_grace` | `12` | Seconds to wait for that real process to appear |
| `privacy` | `auto` | `auto` / `full` / `private` / `off` - see [Privacy](#7-privacy) |
| `status_text` | `Reading` | The second presence line |
| `show_buttons` | global | Show the "View on VNDB" button |
| `client_id` | global | A Discord application just for this game (advanced) |
| `plugin` | - | Name of a state plugin (see [Plugins](#8-plugins)) |
| `plugin_options` | `{}` | Options passed to that plugin |

### Games that use a launcher (Locale Emulator, config tools, packers)

This is the single most common problem with visual novels: you start `Game.exe`,
it spawns `game_main.exe` and exits, and a naive tracker thinks you quit after
one second. VNPresence handles this automatically - it follows the child
processes and keeps going. If a game still loses its presence right after
starting, name the real process explicitly:

```yaml
title: Some VN
path: D:\VN\SomeVN\Launcher.exe
process_names: [somevn_main.exe]
launcher_grace: 20
```

Find the real name in Task Manager while the game runs.

Examples of complete profiles live in [`examples/games/`](examples/games/).

## 5. Discord application / client id

**You do not need to do anything.** VNPresence ships with its own Discord
application, named "a Visual Novel", and that is what makes the top line read
*Playing a Visual Novel*. This section is only for people who want their own.

Why the game title is not on the top line: Discord takes it from the
**application's own name**, not from the data an app sends. It cannot be changed
per game, which is why every tool of this kind puts the title on the second line.
VNPresence therefore names its application "a Visual Novel" and gives the title the
most prominent line it actually controls.

If you want the header to read something else - your own name, or one
application per game - make your own:

1. Open <https://discord.com/developers/applications> → **New Application**.
2. Name it `a Visual Novel` - or anything you want to read after the word
   *Playing*.
3. Copy the **Application ID** from *General Information*.
4. Put it in your config, globally or for one game:

```yaml
# %APPDATA%\VNPresence\config.yaml
client_id: "123456789012345678"
```

```yaml
# a single game overriding it
title: Steins;Gate
client_id: "987654321098765432"
```

You do **not** need to upload any images: VNPresence passes VNDB cover URLs
directly, which also sidesteps Discord's 300-asset limit per application.

Full walkthrough with screenshots: [`docs/discord-setup.md`](docs/discord-setup.md).

## 6. What the presence looks like

A normal game, privacy `full`:

```
Playing a Visual Novel
┌────────┐  Steins;Gate                    <- details: the title
│ VNDB   │  Reading                        <- state: status text or plugin state
│ cover  │  01:24:07 elapsed               <- timestamps.start
└────────┘  [ View on VNDB ]               <- button
```

Hovering the cover shows the Japanese title; hovering the small corner icon shows
`Long (30-50h) • 2009 • ★ 8.9`.

An 18+ title, privacy `auto`:

```
Playing a Visual Novel
Reading a visual novel
Reading
00:12:31 elapsed
```

With a state plugin that reads the current chapter:

```
Playing a Visual Novel
┌────────┐  Muv-Luv Alternative
│ cover  │  Chapter 3 - Ayamine route
└────────┘  02:40:09 elapsed
```

### Auto-detect mode

`vnpresence play` starts the game for you. If you would rather start games the
way you always have - from Steam, a shortcut, or the game's own launcher - run
the watcher instead and forget about it:

```bash
vnpresence watch -b
```

It scans the running processes every few seconds, and the moment one matches a
game in your library it attaches and publishes the presence, exactly as `play`
would. When the game closes it goes back to watching.

`-b` (`--background`) detaches it: your terminal comes straight back, and the
watcher keeps running after you close the window. Manage it with:

```bash
vnpresence status   # running or not, and its pid
vnpresence stop     # stop it
```

Without `-b` it stays in the foreground and prints what it is doing, which is
the better way to see why a game is not being picked up. `Ctrl+C` ends that one.

```
[watch] watching 6 game(s); Ctrl+C to stop
[detected] Steins;Gate (sg.exe)
[presence] activity published
[end] session ended after 2h 14m
```

Notes:

- A game is matched by its executable name, or by `process_names` if you set it.
- Games with `privacy: off` are ignored entirely - they are never even attached to.
- One process scan covers the whole library, so a large library costs no more
  than a small one. Change the pace with `watch_interval` in `config.yaml`.
- Only one watcher runs at a time; starting a second one tells you so instead
  of quietly doubling up.
- To have it there every time you log in, put a shortcut to
  `VNPresence.exe watch` in `shell:startup` (press Win+R, type `shell:startup`).
  The released .exe has no console window, so it just sits there quietly.

## 7. Privacy

Most visual novels carry adult content, and a Rich Presence is visible to every
friend on your list. Privacy is per game:

| Mode | What friends see |
|---|---|
| `auto` *(default)* | Full details, **unless** VNDB marks the title 18+ - then `private` |
| `full` | Title, cover art, VNDB button |
| `private` | "Reading a visual novel" - no title, no art, no link |
| `off` | Nothing at all; the game just runs |

Change it in the window's dropdown, or in the profile:

```yaml
privacy: private
```

Turn the automatic filter off globally with `nsfw_auto_private: false` in
`config.yaml`. VNPresence sends nothing anywhere except Discord (locally) and
VNDB (title lookups).

## 8. Plugins

Adding a **game** needs no code. Adding **behaviour** does, and that is what the
plugin API is for. A plugin is a normal Python package that registers one of
three things:

| Extension point | Purpose |
|---|---|
| `MetadataProvider` | Where a game's title/cover/description comes from (VNDB, Steam, a local file...) |
| `StateProvider` | Live session info - current chapter, route, reading progress |
| `PresenceFormatter` | A different presence layout altogether |

```python
# vnpresence_chapter/__init__.py
from vnpresence import PresenceState, StateProvider

class ChapterProvider(StateProvider):
    name = "chapter"

    def start(self, profile, pid):
        self.save_file = profile.plugin_options.get("save_file")

    def poll(self):
        return PresenceState(status_text=read_chapter(self.save_file))

def register(registry):
    registry.add_state_provider(ChapterProvider)
```

```toml
# the plugin's pyproject.toml
[project.entry-points."vnpresence.plugins"]
chapter = "vnpresence_chapter"
```

`pip install` it and point a game at it:

```yaml
plugin: chapter
plugin_options:
  save_file: D:\VN\MuvLuv\save\global.dat
```

The core never needs to change. Full guide with more examples:
[`docs/writing-plugins.md`](docs/writing-plugins.md).

## 9. Troubleshooting

Run `vnpresence doctor` first - it checks all of this and prints what is wrong.

| Symptom | Cause / fix |
|---|---|
| Nothing appears on your profile | Discord desktop app not running, or *Activity Privacy → Share your detected activities* is off |
| Presence disappears a second after launch | The game uses a launcher - set `process_names` (see [section 4](#4-adding-visual-novels)) |
| Title shows but no cover art | No `vndb_id` on the profile, or VNDB was unreachable when it was added - run `vnpresence add --vndb v2002 ...` again or set `image_url` |
| You see the presence but no buttons | Discord does not render buttons on **your own** profile - ask a friend, or check from another account |
| "requires elevation" / WinError 740 | The game demands administrator rights. VNPresence re-launches it through a UAC prompt - approve it. To stop being asked every time, right-click the .exe → Properties → Compatibility, or run VNPresence as administrator |
| "VNDB rate limit reached" | 200 requests / 5 minutes. Wait; cached games keep working |
| Elapsed time restarts | The tracked process restarted - usually a launcher; set `process_names` |
| Top line says "a Visual Novel", not the game | That is Discord's behaviour, not a bug - see [section 5](#5-discord-application--client-id) |

## 10. Contributing

Contributions are very welcome, especially:

- profiles for games that need a `process_names` quirk (`examples/games/`)
- plugins
- documentation and translations

```bash
git clone https://github.com/BasedYuki/vnpresence.git
cd vnpresence
pip install -e ".[dev]"
pytest && ruff check src tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Be kind, keep PRs small, and add a test
when you change behaviour.

## License

MIT - see [LICENSE](LICENSE). VNPresence is not affiliated with Discord or VNDB.
Game titles, cover art and descriptions belong to their respective owners; cover
images are linked from VNDB, never redistributed.
