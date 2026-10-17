"""The ``trial-al`` command (docs/design.md §5.10)."""

from collections.abc import Callable
from typing import Annotated

import typer

from trial_al import __version__
from trial_al.cli import plugins
from trial_al.cli.doctor import doctor
from trial_al.config import ConfigError, load_config
from trial_al.plugins import PluginError, load_plugins

STUBS = {
    "install": "Download every trial and build the database.",
    "update": "Fetch the trials changed since the last update.",
    "rebuild": "Rebuild the database from the downloaded data.",
    "serve": "Start the API and the job worker.",
    "worker": "Run the job worker on its own.",
    "backup": "Copy the databases while the app is running.",
    "bench": "Run the benchmark suite.",
}
CORE_COMMANDS = {*STUBS, "doctor", "plugins"}


def create_app() -> typer.Typer:
    """Build the CLI, with a command group for each enabled plugin that adds one."""
    app = typer.Typer(
        name="trial-al",
        help="Tri-AL: ClinicalTrials.gov in a fast local dashboard.",
        no_args_is_help=True,
        add_completion=False,
    )
    app.callback()(_root)
    for name, help_text in STUBS.items():
        app.command(name, help=f"{help_text} (Not implemented yet.)")(_stub(name))
    app.command("doctor")(doctor)
    app.add_typer(plugins.app, name="plugins")
    _mount_plugins(app)
    return app


def main() -> None:
    create_app()()


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"trial-al {__version__}")
        raise typer.Exit()


def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    pass


def _stub(name: str) -> Callable[[], None]:
    def command() -> None:
        typer.echo(f"trial-al {name}: not implemented yet", err=True)
        raise typer.Exit(1)

    return command


def _mount_plugins(app: typer.Typer) -> None:
    # Core commands must keep working when plugins can't load, so `plugins list` and
    # `plugins disable` can be used to find and fix the problem.
    try:
        loaded = load_plugins(load_config())
    except (ConfigError, PluginError):
        typer.echo(
            "warning: plugin commands are unavailable; run `trial-al plugins list` to see why",
            err=True,
        )
        return
    for name, cli in loaded.contributions.cli.items():
        if name in CORE_COMMANDS:
            typer.echo(f"warning: plugin {name!r} can't add commands: the name is taken", err=True)
        else:
            app.add_typer(cli, name=name, rich_help_panel="Plugins")
