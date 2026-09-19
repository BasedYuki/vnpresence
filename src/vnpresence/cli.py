"""Command line interface. Everything the GUI does is available here."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from . import __version__
from .config import AppConfig, config_dir, config_file, games_dir
from .launcher import LaunchError, _split_path
from .library import Library
from .models import GameProfile, PrivacyMode, looks_like_vndb_ref, normalise_vndb_id
from .notes import clear_note, read_note, write_note
from .playtime import Playtime, parse_duration
from .plugins import build_registry
from .session import GameSession, format_duration
from .titles import guess_title
from .update import UpdateError, check, install, skip_version
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

    # The executable is often named after the engine (SiglusEngine, reallive,
    # game.exe), so the folder is usually the better guess for both the search
    # and the fallback title.
    guessed = guess_title(path)

    if vndb_id:
        vndb_id = normalise_vndb_id(vndb_id)
        metadata = _lookup(vndb_id, config)
    elif search_term and looks_like_vndb_ref(search_term):
        # A link pasted into --search is not a search term, it is the answer.
        vndb_id = normalise_vndb_id(search_term)
        metadata = _lookup(vndb_id, config)
    elif search_term or not title:
        term = search_term or guessed
        metadata, vndb_id = _search_interactive(term, config)

    resolved_title = title or (metadata.title if metadata else guessed)
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
    _warn_about_shared_launcher(library, profile)
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
    summary = f"\u2713 {result.title}: {format_duration(result.seconds)}"
    if result.total_seconds > result.seconds:
        summary += f" ({format_duration(result.total_seconds)} in total)"
    click.secho(summary, fg="green")


@main.command("link")
@click.argument("game")
@click.argument("reference")
@click.option("--keep-title", is_flag=True, help="Keep the current title instead of VNDB's.")
def link(game: str, reference: str, keep_title: bool) -> None:
    """Point a game at a VNDB entry, by link or id.

    Use this when the name search picked the wrong entry - a novel and its
    sequel often share a name, and only the link tells them apart:

        vnpresence link rewrite https://vndb.org/v2400
    """
    library = Library()
    profile = library.find(game)
    if profile is None:
        raise click.ClickException(f"no game matches {game!r} (try: vnpresence list)")
    try:
        vndb_id = normalise_vndb_id(reference)
    except ValueError as exc:
        raise click.ClickException(
            f"{reference!r} is not a VNDB link or id (expected something like "
            "v2400 or https://vndb.org/v2400)"
        ) from exc

    config = AppConfig.load()
    metadata = _lookup(vndb_id, config)
    if metadata is None:
        raise click.ClickException(f"VNDB has nothing at {vndb_id}")

    profile.vndb_id = vndb_id
    if not keep_title:
        profile.title = metadata.title
    library.save(profile)
    click.secho(f"✓ {profile.title} -> {metadata.url}", fg="green")
    if metadata.nsfw and profile.privacy is PrivacyMode.AUTO:
        click.secho("  VNDB marks this 18+, so 'auto' privacy will hide it.", fg="yellow")


@main.command("rematch")
@click.argument("game", required=False)
@click.option("--all", "do_all", is_flag=True, help="Every game that has no VNDB match.")
def rematch(game: str | None, do_all: bool) -> None:
    """Search VNDB again for games that ended up without a match.

    A game added while VNDB was unreachable - or whose first guess was turned
    down - keeps working, but has no cover art. This goes back over them
    without touching anything else about the game:

        vnpresence rematch --all
    """
    library = Library()
    config = AppConfig.load()
    if game:
        found = library.find(game)
        if found is None:
            raise click.ClickException(f"no game matches {game!r}")
        targets = [found]
    elif do_all:
        targets = [p for p in library.load_all() if not p.vndb_id]
    else:
        raise click.ClickException("name a game, or pass --all")

    if not targets:
        click.echo("Every game already has a VNDB match.")
        return

    fixed = 0
    for profile in targets:
        click.echo(f"\n{profile.title}")
        metadata, vndb_id = _search_interactive(profile.title, config)
        if metadata is None or vndb_id is None:
            click.secho("  left as it is", fg="yellow")
            continue
        profile.vndb_id = vndb_id
        library.save(profile)  # the title is left alone: it may be deliberate
        fixed += 1
        click.secho(f"  \u2713 {metadata.title} ({metadata.url})", fg="green")
    click.secho(f"\n{fixed} of {len(targets)} matched.", fg="green" if fixed else None)


@main.command("rename")
@click.argument("game")
@click.argument("title", nargs=-1, required=True)
def rename(game: str, title: tuple[str, ...]) -> None:
    """Change the name shown on the presence, keeping everything else.

    Some releases are not on VNDB at all - fan translations, remakes, cuts
    like STEINS;GATE Re:Boot, which VNDB folds into its parent entry. Link the
    game to the parent so it still gets a cover, then call it what it is:

        vnpresence link sg v2002
        vnpresence rename sg "STEINS;GATE Re:Boot"
    """
    library = Library()
    profile = library.find(game)
    if profile is None:
        raise click.ClickException(f"no game matches {game!r} (try: vnpresence list)")
    profile.title = " ".join(title).strip()
    library.save(profile)
    click.secho(f"\u2713 now called {profile.title}", fg="green")


@main.command("note")
@click.argument("game")
@click.argument("text", nargs=-1)
@click.option("--clear", "clear", is_flag=True, help="Remove the note.")
def note(game: str, text: tuple[str, ...], clear: bool) -> None:
    """Set the route or chapter shown for a game.

    A running session picks the change up within one update, so this works
    mid-read:

        vnpresence note muv-luv "Chapter 3 - Ayamine route"
    """
    profile = Library().find(game)
    if profile is None:
        raise click.ClickException(f"no game matches {game!r} (try: vnpresence list)")
    if clear:
        removed = clear_note(profile.id)
        click.secho(
            f"✓ cleared the note for {profile.title}" if removed else "There was no note.",
            fg="green" if removed else None,
        )
        return
    if not text:
        current = read_note(profile.id)
        click.echo(current if current else f"No note for {profile.title}.")
        return
    written = " ".join(text)
    write_note(profile.id, written)
    click.secho(f"✓ {profile.title}: {written}", fg="green")


@main.command("stats")
@click.argument("game", required=False)
@click.option(
    "--set",
    "set_to",
    metavar="TIME",
    help="Set this game's total, for hours read before VNPresence (50h, 50h 30m, 50:30).",
)
@click.option("--add", "add_time", metavar="TIME", help="Add time to this game's total.")
def stats(game: str | None, set_to: str | None, add_time: str | None) -> None:
    """Show how long each game has been read.

    A game you have been reading for years starts at zero, because VNPresence
    was not there for those hours. Tell it once:

        vnpresence stats rewrite --set 50h
    """
    library = Library()
    if set_to or add_time:
        if not game:
            raise click.ClickException("say which game: vnpresence stats <game> --set 50h")
        profile = library.find(game)
        if profile is None:
            raise click.ClickException(f"no game matches {game!r}")
        try:
            seconds = parse_duration(set_to or add_time or "")
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        history = Playtime()
        entry = (
            history.set(profile.id, seconds)
            if set_to
            else history.add(profile.id, seconds)
        )
        click.secho(
            f"\u2713 {profile.title}: {format_duration(entry.seconds)} read in total",
            fg="green",
        )
        return

    profiles = library.load_all()
    if game:
        found = library.find(game)
        if found is None:
            raise click.ClickException(f"no game matches {game!r}")
        profiles = [found]
    if not profiles:
        click.echo("No games yet.")
        return

    history = Playtime().load()
    width = max(len(p.title) for p in profiles)
    shown = 0
    for profile in profiles:
        entry = history.get(profile.id)
        if entry is None:
            continue
        shown += 1
        line = (
            f"{profile.title.ljust(width)}  {format_duration(entry.seconds).rjust(8)}"
            f"  {entry.sessions} session{'s' if entry.sessions != 1 else ''}"
        )
        if entry.last_played:
            line += f"  last {entry.last_played[:10]}"
        click.echo(line)
    if not shown:
        click.echo("Nothing read yet - play something first.")


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


@main.command("autostart")
@click.argument("action", type=click.Choice(["on", "off", "status"]), default="status")
def autostart(action: str) -> None:
    """Start watching automatically when you log in to Windows."""
    from . import startup

    try:
        if action == "on":
            command = startup.enable()
            click.secho("✓ VNPresence will start with Windows", fg="green")
            click.echo(f"  {command}")
        elif action == "off":
            startup.disable()
            click.secho("✓ removed from Windows startup", fg="green")
        else:
            enabled = startup.is_enabled()
            click.echo("Enabled." if enabled else "Not enabled.")
    except startup.StartupUnsupported as exc:
        raise click.ClickException(str(exc)) from exc


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


@main.command("update")
@click.option("--check", "check_only", is_flag=True, help="Only say whether one exists.")
@click.option("--yes", "assume_yes", is_flag=True, help="Install without asking.")
def update_command(check_only: bool, assume_yes: bool) -> None:
    """See whether a newer VNPresence has been released, and install it."""
    if not AppConfig.load().check_updates:
        click.secho("Update checks are turned off (check_updates: false).", fg="yellow")
        return
    release = check(force=True)
    if release is None:
        click.secho(f"\u2713 VNPresence {__version__} is the newest build.", fg="green")
        return

    click.secho(f"VNPresence {release.version} is out (you have {__version__}).", fg="cyan")
    if release.published:
        click.echo(f"  released {release.published}")
    if release.notes:
        click.echo("\n" + "\n".join(f"  {line}" for line in release.notes.splitlines()[:12]))
    click.echo(f"\n  {release.url}")
    if check_only:
        return
    if not (assume_yes or click.confirm("\nDownload and install it?", default=True)):
        if click.confirm("Stop mentioning this version?", default=False):
            skip_version(release.version)
        return
    try:
        click.echo("Downloading...")
        click.secho("\u2713 " + install(release), fg="green")
    except UpdateError as exc:
        raise click.ClickException(f"{exc}\n\nDownload it yourself from {release.url}") from exc


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
    _report_unmatched(games)
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
def _report_unmatched(profiles: list[GameProfile]) -> None:
    """Games with no VNDB link have no cover, and nothing else says so."""
    unmatched = [p for p in profiles if not p.vndb_id]
    if not unmatched:
        return
    click.secho(
        f"no vndb   : {len(unmatched)} game(s) have no VNDB match, so no cover art",
        fg="yellow",
    )
    for profile in unmatched[:5]:
        click.echo(f"            {profile.id}  ->  vnpresence link {profile.id} <name or link>")
    if len(unmatched) > 5:
        click.echo(f"            ... and {len(unmatched) - 5} more")


def _vndb_check(config: AppConfig) -> None:
    try:
        VNDBClient(cache_days=config.cache_days).search("steins gate", limit=1)
        click.secho("vndb       : reachable", fg="green")
    except Exception as exc:
        click.secho(f"vndb       : not reachable ({exc})", fg="yellow")



def _warn_about_shared_launcher(library: Library, profile: GameProfile) -> None:
    """Tell the user when this executable is already another game's."""
    clashes = library.sharing_exe_name(profile)
    if not clashes:
        return
    names = ", ".join(p.title for p in clashes[:3])
    _, exe_name = _split_path(profile.path or "")
    click.secho(
        f"\n! {exe_name} is also how you start {names}. That is normal for a series "
        "- they share one launcher.",
        fg="yellow",
    )
    click.echo(
        "  VNPresence tells them apart by full path, so this works. It is still "
        "steadier to point at\n  the game's own executable instead of the launcher, "
        "or to set 'process_names' in the profile."
    )


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
        retry = click.prompt(
            "Type another name, paste a VNDB link (or press Enter to skip)",
            default="",
            show_default=False,
        ).strip()
        if retry:
            return _resolve_term(retry, config)
        return None, None
    click.echo(f"VNDB matches for {term!r}:")
    for index, item in enumerate(results, start=1):
        flag = " [18+]" if item.nsfw else ""
        click.echo(f"  {index}. {item.title}{flag}")
    click.echo("  0. none of these - type a name or paste a VNDB link instead")
    choice = click.prompt("Pick one", type=click.IntRange(0, len(results)), default=1)
    if choice == 0:
        # Sequels share their parent's name, so no amount of re-searching
        # separates them; the link is the way out.
        typed = click.prompt(
            "Name or VNDB link (Enter to skip)", default="", show_default=False
        ).strip()
        return _resolve_term(typed, config) if typed else (None, None)
    chosen = results[choice - 1]
    return chosen, (chosen.url or "").rsplit("/", 1)[-1] or None


def _resolve_term(term: str, config: AppConfig):
    """Treat the text as a VNDB link if it is one, and as a name otherwise."""
    if not looks_like_vndb_ref(term):
        return _search_interactive(term, config)
    try:
        vndb_id = normalise_vndb_id(term)
    except ValueError:
        return _search_interactive(term, config)
    metadata = _lookup(vndb_id, config)
    if metadata is None:
        click.secho(f"! VNDB has nothing at {vndb_id}", fg="yellow")
        return None, None
    return metadata, vndb_id


if __name__ == "__main__":  # pragma: no cover
    main()
