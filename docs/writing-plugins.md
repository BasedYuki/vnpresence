# Writing a VNPresence plugin

A plugin is an ordinary Python package that registers extensions. VNPresence
finds it through the `vnpresence.plugins` entry-point group - install it and it
is active, uninstall it and it is gone. The core never changes.

Before writing one, check that you actually need it: adding a game, a cover
image, a custom status line or a per-game Discord application all work from the
game's YAML profile with no code.

## The three extension points

| Class | Called when | Use it for |
|---|---|---|
| `MetadataProvider` | Once, before launch | Where title/cover/description come from |
| `StateProvider` | Every update (15s) | Chapter, route, play time, anything live |
| `PresenceFormatter` | Every update | A different presence layout |

## Skeleton

```
vnpresence-chapter/
├── pyproject.toml
└── vnpresence_chapter/
    └── __init__.py
```

```toml
# pyproject.toml
[project]
name = "vnpresence-chapter"
version = "0.1.0"
dependencies = ["vnpresence>=0.1"]

[project.entry-points."vnpresence.plugins"]
chapter = "vnpresence_chapter"
```

```python
# vnpresence_chapter/__init__.py
from vnpresence import PresenceState, StateProvider


class ChapterProvider(StateProvider):
    name = "chapter"          # what users put in `plugin:` in their profile

    def __init__(self, save_file=None, prefix="Chapter"):
        self.save_file = save_file
        self.prefix = prefix

    def start(self, profile, pid):
        """Called once when the game is up. `pid` may be None."""
        self.pid = pid

    def poll(self):
        """Return a PresenceState, or None to keep the previous one."""
        chapter = read_chapter(self.save_file)
        if chapter is None:
            return None
        return PresenceState(status_text=f"{self.prefix} {chapter}")

    def stop(self):
        """Release files/handles here."""


def register(registry):
    registry.add_state_provider(ChapterProvider)
```

Users then write:

```yaml
title: Muv-Luv Alternative
path: D:\VN\MuvLuv\muvluv.exe
vndb_id: v92
plugin: chapter
plugin_options:
  save_file: D:\VN\MuvLuv\save\global.dat
  prefix: Ch.
```

`plugin_options` is passed to your `__init__` as keyword arguments.

## Rules that keep sessions stable

1. **`poll()` must return fast.** It runs on the session loop. Do I/O in a
   background thread and return the last known value.
2. **Never raise.** An exception disables your plugin for the rest of the
   session (logged, not crashed) - but returning `None` is the polite way to say
   "nothing new".
3. **Return `None`, don't guess.** `None` keeps the previous state instead of
   flickering an empty line.
4. **Respect privacy.** A `StateProvider` runs even in `private` mode, but
   nothing it returns is published there - not the status text, not the
   reading total. A route name identifies a novel as surely as its title does, which
   is the one thing private mode exists to withhold.
5. **Text limits.** Discord clips fields at 128 characters; VNPresence clamps for
   you, so long strings are truncated, not rejected.
6. **`playtime_seconds` overrules the recorded total.** VNPresence adds up the
   time it has watched a game being read. If your plugin can get the real
   figure out of the game, set `PresenceState.playtime_seconds` and yours is
   shown instead. Leave it `None` to keep the recorded one.

## A metadata provider

```python
from vnpresence import GameMetadata, MetadataProvider


class SteamProvider(MetadataProvider):
    name = "steam"
    priority = 5          # higher wins; the built-in VNDB provider is 10

    def can_handle(self, profile):
        return bool(profile.plugin_options.get("steam_appid"))

    def fetch(self, profile):
        appid = profile.plugin_options["steam_appid"]
        return GameMetadata(
            title=profile.title,
            image_url=f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
            url=f"https://store.steampowered.com/app/{appid}/",
            source="steam",
        )


def register(registry):
    registry.add_metadata_provider(SteamProvider())
```

A user forces a specific provider with `metadata_provider: steam` in the profile.

## A custom formatter

```python
from vnpresence import PresenceFormatter
from vnpresence.formatter import DefaultFormatter, clamp


class MinimalFormatter(PresenceFormatter):
    name = "minimal"
    priority = 100        # the highest-priority formatter is the one used

    def format(self, profile, metadata, state, context):
        payload = DefaultFormatter().format(profile, metadata, state, context)
        if payload:
            payload.pop("buttons", None)
            payload["state"] = clamp("Reading a visual novel")
        return payload


def register(registry):
    registry.add_formatter(MinimalFormatter())
```

Return `None` from `format()` to publish nothing.

## Testing your plugin

```python
from vnpresence import GameProfile
from vnpresence.plugins import PluginRegistry
from vnpresence_chapter import register


def test_chapter_state():
    registry = PluginRegistry()
    register(registry)
    profile = GameProfile(id="x", title="X", plugin="chapter",
                          plugin_options={"save_file": "tests/data/save.dat"})
    provider = registry.state_provider_for(profile)
    provider.start(profile, pid=None)
    assert provider.poll().status_text.startswith("Chapter")
```

## Publishing

Publish to PyPI as `vnpresence-<name>`, and open an issue on the VNPresence repo
so it can be listed in the README. Plugins are not vendored into the core.
