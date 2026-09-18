# VNPresence

Discord Rich Presence for visual novels. Launch a VN through VNPresence and your
Discord profile shows the title, the cover art, how long you have been reading,
and a link to its VNDB page - the way a normal game does.

```
Playing Steins;Gate
┌────────┐  Steins;Gate
│ cover  │  Reading
│  art   │  Long (30-50h) • 2009 • ★ 8.9
└────────┘  01:24:07 elapsed   [ View on VNDB ]
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

The release also carries `VNPresence-cli.exe`. It is the same program with a
console attached, for when you want to see the output of `doctor`, `watch` or
`list`. The windowed one prints nowhere, by design.

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
vnpresence autostart on                     # start watching at every login
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

VNPresence works out the game's name, searches VNDB with it, shows you the
matches, and writes a profile. That is all most games need.

It does **not** simply use the file name: visual novels are usually launched by
an executable named after the engine (`SiglusEngine_SteamEN.exe`,
`reallive.exe`, `game.exe`), so when the file name is an engine or a
placeholder, the folder name is used instead -
`K:\Games\Rewrite\SiglusEngine_SteamEN.exe` is added as **Rewrite**. If VNDB
still finds nothing, you are asked to type the name yourself rather than being
left with a junk title.

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
| `title` | *(required)* | The game's name - it becomes the "Playing …" line |
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
application and puts the game's name into the activity, so the header reads
*Playing Steins;Gate*.

A note on how that works, because most tools of this kind cannot do it: Discord
normally prints the *application's* name after "Playing", and that name is fixed
in the developer portal. Current Discord clients also accept a `name` field
inside the activity itself, and VNPresence sends it - so the header follows the
game instead of the application. If the field is ever refused, the activity is
still published without it and the title stays on the line below; nothing
breaks.

Check what your own client does:

```bash
python tools/probe_name_override.py
```

If your client is old enough to ignore the field, put the title back on the
second line:

```yaml
# config.yaml
use_activity_name: false
```

You only need your own application if you want the *fallback* name (what shows
when the field is ignored) to be something else:

1. Open <https://discord.com/developers/applications> → **New Application**.
2. Name it whatever should appear after *Playing*.
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

Full walkthrough: [`docs/discord-setup.md`](docs/discord-setup.md).

## 6. What the presence looks like

A normal game, privacy `full`:

```
Playing Steins;Gate                        <- name: the game itself
┌────────┐  Steins;Gate                    <- the activity card
│ VNDB   │  Reading                        <- details: status or plugin state
│ cover  │  Long (30-50h) • 2009 • ★ 8.9   <- state: what VNDB knows
└────────┘  01:24:07 elapsed
            [ View on VNDB ]
```

An 18+ title, privacy `auto` - no name, no art, nothing identifying:

```
Playing a Visual Novel
Reading a visual novel
Reading
00:12:31 elapsed
```

With a state plugin that reads the current chapter:

```
Playing Muv-Luv Alternative
┌────────┐  Muv-Luv Alternative
│ cover  │  Chapter 3 - Ayamine route
└────────┘  02:40:09 elapsed
```

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
| Title is the engine's name (`SiglusEngine`, `reallive`) | An old profile from before 0.5.0 - fix the title and `vndb_id` in its YAML, or remove and add the game again |
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
