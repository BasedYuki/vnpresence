"""Command line interface. Everything the GUI does is available here."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from . import __version__
from .config import AppConfig, config_dir, config_file, games_dir
from .launcher import LaunchError
from .library import Library
from .models import GameProfile, PrivacyMode, normalise_vndb_id
from .plugins import build_registry
from .session import GameSession, format_duration
from .vndb import VNDBClient, VNDBError


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s" if verbose else "%(message)s",
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="vnpresence")
@click.option("-v", "--verbose", is_flag=True, help="Show debug logging.")
def main(verbose: bool) -> None:
    """VNPresence - Discord Rich Presence for visual novels."""
    _setup_logging(verbose)


@main.command("add")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--title", help="Game title (defaults to the VNDB title or the file name).")
@click.option("--vndb", "vndb_id", help="VNDB id or URL, e.g. v17 or https://vndb.org/v17")
@click.option("--search", "search_term", help="Search VNDB by name and pick the best match.")
@click.option(
    "--privacy",
    type=click.Choice([m.value for m in PrivacyMode]),
    default=None,
    help="Privacy mode for this game (default: auto).",
)
@click.option("--process", "process_names", multiple=True, help="Real process name(s), repeatable.")
@click.option("--arg", "args", multiple=True, help="Argument passed to the executable, repeatable.")
def add_game(
    path: Path,
    title: str | None,
    vndb_id: str | None,
    search_term: str | None,
    privacy: str | None,
    process_names: tuple[str, ...],
    args: tuple[str, ...],
) -> None:
    """Add a game by pointing at its executable."""
    config = AppConfig.load()
    library = Library()
    metadata = None

    if vndb_id:
        vndb_id = normalise_vndb_id(vndb_id)
        metadata = _lookup(vndb_id, config)
    elif search_term or not title:
        term = search_term or path.stem
        metadata, vndb_id = _search_interactive(term, config)

    resolved_title = title or (metadata.title if metadata else path.stem)
    profile = GameProfile(
        id=library.unique_id(resolved_title),
        title=resolved_title,
        path=str(path.resolve()),
        args=list(args),
        vndb_id=vndb_id,
        process_names=list(process_names),
        privacy=PrivacyMode(privacy or config.default_privacy),
    )
    saved = library.save(profile)
    click.secho(f"\u2713 added {profile.title}", fg="green")
    click.echo(f"  id      : {profile.id}")
    click.echo(f"  vndb    : {profile.vndb_id or '-'}")
    click.echo(f"  privacy : {profile.privacy.value}")
    click.echo(f"  profile : {saved}")
    click.echo(f"\nStart it with:  vnpresence play {profile.id}")


@main.command("list")
def list_games() -> None:
    """List the games in your library."""
    profiles = Library().load_all()
    if not profiles:
        click.echo("No games yet. Add one with:  vnpresence add \"C:\\path\\to\\game.exe\"")
        return
    width = max(len(p.id) for p in profiles)
    for profile in profiles:
        click.echo(
            f"{profile.id.ljust(width)}  {profile.title}  "
            f"[{profile.privacy.value}{', ' + profile.vndb_id if profile.vndb_id else ''}]"
        )


@main.command("play")
@click.argument("game")
@click.option("--attach", is_flag=True, help="Attach to an already running game.")
def play(game: str, attach: bool) -> None:
    """Launch a game and publish the Rich Presence."""
    profile = Library().find(game)
    if profile is None:
        raise click.ClickException(f"no game matches {game!r} (try: vnpresence list)")

    def report(kind: str, message: str) -> None:
        colors = {"warning": "yellow", "privacy": "yellow", "end": "cyan"}
        click.secho(f"[{kind}] {message}", fg=colors.get(kind))

    try:
        result = GameSession(profile).run(attach=attach, on_event=report)
    except LaunchError as exc:
        raise click.ClickException(str(exc)) from exc
    click.secho(f"\u2713 {result.title}: {format_duration(result.seconds)}", fg="green")


@main.command("watch")
@click.option("--interval", type=float, default=None, help="Seconds between scans.")
@click.option("--once", is_flag=True, help="Handle one game and exit (useful for testing).")
@click.option(
    "-b",
    "--background",
    is_flag=True,
    help="Detach and keep watching after you close this window.",
)
def watch(interval: float | None, once: bool, background: bool) -> None:
    """Watch for library games started outside VNPresence and attach to them."""
    from .daemon import running_pid, spawn_background
    from .watcher import LibraryWatcher

    watcher = LibraryWatcher(interval=interval)
    if not watcher.watchable():
        raise click.ClickException("no games to watch - add one with: vnpresence add")

    already = running_pid()
    if already is not None:
        raise click.ClickException(
            f"a watcher is already running (pid {already}). Stop it with: vnpresence stop"
        )

    if background:
        extra = ["--interval", str(interval)] if interval else []
        pid = spawn_background(extra)
        click.secho(f"✓ watching in the background (pid {pid})", fg="green")
        click.echo("It keeps running after you close this window.")
        click.echo("Stop it with:  vnpresence stop")
        return

    def report(kind: str, message: str) -> None:
        colors = {"warning": "yellow", "privacy": "yellow", "error": "red", "detected": "green"}
        click.secho(f"[{kind}] {message}", fg=colors.get(kind))

    watcher.run(on_event=report, once=once, record_pid=True)


@main.command("stop")
def stop() -> None:
    """Stop a watcher running in the background."""
    from .daemon import stop_background

    pid = stop_background()
    if pid is None:
        click.echo("No background watcher is running.")
        return
    click.secho(f"✓ stopped the watcher (pid {pid})", fg="green")


@main.command("status")
def status() -> None:
    """Say whether a background watcher is running."""
    from .daemon import running_pid

    pid = running_pid()
    if pid is None:
        click.echo("Not running.  Start it with:  vnpresence watch --background")
    else:
        click.secho(f"Watching in the background (pid {pid}).", fg="green")


@main.command("remove")
@click.argument("game")
def remove(game: str) -> None:
    """Remove a game from the library."""
    library = Library()
    profile = library.find(game)
    if profile is None:
        raise click.ClickException(f"no game matches {game!r}")
    library.remove(profile.id)
    click.secho(f"\u2713 removed {profile.title}", fg="green")


@main.command("search")
@click.argument("term")
def search(term: str) -> None:
    """Search VNDB."""
    config = AppConfig.load()
    client = VNDBClient(cache_days=config.cache_days)
    try:
        results = client.search(term)
    except VNDBError as exc:
        raise click.ClickException(str(exc)) from exc
    if not results:
        click.echo("No results.")
        return
    for item in results:
        vid = (item.url or "").rsplit("/", 1)[-1]
        flag = " [18+]" if item.nsfw else ""
        click.echo(f"{vid:>8}  {item.title}{flag}")


@main.command("gui")
def gui_command() -> None:
    """Open the small desktop window."""
    from .gui import run_gui

    run_gui()


@main.command("plugins")
def plugins_command() -> None:
    """Show which plugins and providers are active."""
    info = build_registry(AppConfig.load().enabled_plugins or None).describe()
    for key, values in info.items():
        click.echo(f"{key}: {', '.join(values) or '-'}")


@main.command("doctor")
def doctor() -> None:
    """Check the setup and print what is wrong, if anything."""
    config = AppConfig.load()
    ok = True

    click.echo(f"config dir : {config_dir()}")
    click.echo(f"config file: {config_file()} {'(defaults)' if not config_file().exists() else ''}")
    click.echo(f"games dir  : {games_dir()}")

    games = Library().load_all()
    click.echo(f"games      : {len(games)}")
    for profile in games:
        if profile.path and not Path(profile.path).exists():
            click.secho(f"  ! missing executable for {profile.id}: {profile.path}", fg="yellow")
            ok = False

    if config.client_id in ("", "0"):
        click.secho(
            "  ! no Discord application id configured - add\n"
            f"      client_id: \"123456789012345678\"\n"
            f"    to {config_file()} (see docs/discord-setup.md)",
            fg="yellow",
        )
        click.secho("discord    : skipped (no application id)", fg="yellow")
        _vndb_check(config)
        sys.exit(1)

    click.echo(f"client id  : {config.client_id}")

    try:
        from pypresence import Presence

        rpc = Presence(config.client_id)
        rpc.connect()
        rpc.close()
        click.secho("discord    : connected", fg="green")
    except Exception as exc:
        click.secho(f"discord    : not reachable ({exc})", fg="yellow")
        ok = False

    _vndb_check(config)
    sys.exit(0 if ok else 1)


# -- helpers --------------------------------------------------------------
def _vndb_check(config: AppConfig) -> None:
    try:
        VNDBClient(cache_days=config.cache_days).search("steins gate", limit=1)
        click.secho("vndb       : reachable", fg="green")
    except Exception as exc:
        click.secho(f"vndb       : not reachable ({exc})", fg="yellow")



def _lookup(vndb_id: str, config: AppConfig):
    try:
        return VNDBClient(cache_days=config.cache_days).get(vndb_id)
    except VNDBError as exc:
        click.secho(f"! VNDB lookup failed: {exc}", fg="yellow")
        return None


def _search_interactive(term: str, config: AppConfig):
    try:
        results = VNDBClient(cache_days=config.cache_days).search(term, limit=8)
    except VNDBError as exc:
        click.secho(f"! VNDB search failed: {exc}", fg="yellow")
        return None, None
    if not results:
        click.secho(f"! nothing on VNDB matches {term!r}", fg="yellow")
        return None, None
    click.echo(f"VNDB matches for {term!r}:")
    for index, item in enumerate(results, start=1):
        flag = " [18+]" if item.nsfw else ""
        click.echo(f"  {index}. {item.title}{flag}")
    click.echo("  0. none of these")
    choice = click.prompt("Pick one", type=click.IntRange(0, len(results)), default=1)
    if choice == 0:
        return None, None
    chosen = results[choice - 1]
    return chosen, (chosen.url or "").rsplit("/", 1)[-1] or None


if __name__ == "__main__":  # pragma: no cover
    main()
