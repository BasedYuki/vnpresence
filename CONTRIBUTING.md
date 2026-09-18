# Contributing to VNPresence

Thanks for helping. There are three useful ways to contribute, and only one of
them involves writing code.

## 1. Add a game profile (no code)

Some visual novels need a quirk to be tracked properly - a launcher that exits
immediately, an unusual process name. If you worked one out, share it: add a
YAML file to `examples/games/` and open a PR.

```yaml
# examples/games/some-vn.yaml
title: Some VN
vndb_id: v12345
process_names: [somevn_main.exe]
launcher_grace: 20
# note: this game starts through Locale Emulator, which exits right away
```

Leave `path` out - it is personal to each machine. The CI validates every file
in that folder against the profile schema.

## 2. Write a plugin

Plugins live in their own repositories and are installed with `pip`. See
[docs/writing-plugins.md](docs/writing-plugins.md). Open an issue when yours is
published and it gets listed in the README.

## 3. Work on VNPresence itself

```bash
git clone https://github.com/BasedYuki/vnpresence.git
cd vnpresence
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check src tests
```

### House rules

- **Small PRs.** One change, one PR.
- **Add a test** for anything that changes behaviour. The suite runs offline -
  network calls are faked, never made.
- **Keep the core small.** If a feature only matters to some games, it belongs in
  a plugin or in the profile schema, not in `session.py`.
- **Do not break profiles.** Existing YAML files must keep loading. Add keys with
  defaults; never rename one without an alias.
- **No telemetry, ever.** VNPresence talks to Discord (locally) and VNDB. Nothing
  else.
- Formatting and linting: `ruff`, 100 columns. CI runs it.

### Project layout

```
src/vnpresence/
├── models.py       dataclasses: GameProfile, GameMetadata, PresenceState
├── config.py       paths + AppConfig
├── library.py      reading/writing game profiles
├── vndb.py         VNDB API client + cache
├── launcher.py     starting the game, following the real process
├── presence.py     Discord IPC wrapper (reconnect, rate limit)
├── formatter.py    building the activity payload + privacy resolution
├── session.py      the loop tying it all together
├── plugins.py      registry + entry-point discovery
├── providers/      built-in providers and the extension base classes
├── cli.py          command line
└── gui.py          Tkinter window
```

Rule of thumb for where code goes: if it decides **what Discord shows**, it is
`formatter.py`; if it decides **whether the game is running**, it is
`launcher.py`; if it is **about one game**, it is probably a profile key.

### The Discord application

`DEFAULT_CLIENT_ID` in `src/vnpresence/config.py` is the project's own
application, named **Visual Novel** - that name is what users see after the word
*Playing*. An application ID is public information: it is not a secret, and it is
committed on purpose. Only change it if the project's application is replaced.

### The icon

`assets/icon.png` is generated, not hand-drawn - edit `tools/make_icon.py` and
re-run it rather than editing the PNG:

```bash
python tools/make_icon.py
```

### Commit messages

Plain and descriptive: `launcher: follow grandchildren of the launcher process`.

## Reporting a bug

Include the output of `vnpresence doctor`, the game's profile YAML (minus your
paths if you prefer), and what you expected to see. If it is a detection
problem, the output of `vnpresence play <game> -v` is the useful part.

## Code of conduct

Be decent to each other. Harassment, bigotry, or hostility gets you removed from
the project, no discussion.
