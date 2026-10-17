"""``trial-al plugins list|enable|disable``."""

from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from trial_al.config import Config, ConfigError, config_path, load_config, set_plugin_enabled
from trial_al.plugins import PluginStatus, inspect_plugins

app = typer.Typer(help="List, enable and disable plugins.", no_args_is_help=True)

PluginName = Annotated[str, typer.Argument(help="Plugin name, as shown by `plugins list`.")]


@app.command("list")
def list_plugins() -> None:
    """Show installed plugins, whether each is enabled, and any problems."""
    statuses = inspect_plugins(_load_config())
    if not statuses:
        typer.echo("No plugins installed.")
        return
    table = Table("Plugin", "Version", "Enabled", "Status", "Description")
    for status in statuses:
        table.add_row(
            escape(status.name),
            escape(status.version or ""),
            "yes" if status.enabled else "no",
            _describe(status),
            escape(status.description),
        )
    Console().print(table)


@app.command()
def enable(name: PluginName) -> None:
    """Enable an installed plugin."""
    _set_enabled(name, enabled=True)


@app.command()
def disable(name: PluginName) -> None:
    """Disable an installed plugin."""
    _set_enabled(name, enabled=False)


def _describe(status: PluginStatus) -> str:
    if not status.installed:
        return "[yellow]not installed[/]"
    if status.problems:
        return "\n".join(f"[red]{escape(problem)}[/]" for problem in status.problems)
    return "[green]ok[/]"


def _set_enabled(name: str, *, enabled: bool) -> None:
    action = "enabled" if enabled else "disabled"
    config = _load_config()
    installed = sorted(status.name for status in inspect_plugins(config) if status.installed)
    if name not in installed:
        known = ", ".join(installed) or "none"
        typer.echo(f"error: no installed plugin named {name!r}; installed: {known}", err=True)
        raise typer.Exit(1)
    if config.plugin_enabled(name) == enabled:
        typer.echo(f"Plugin {name!r} is already {action}.")
        return

    path = config_path()
    try:
        set_plugin_enabled(path, name, enabled)
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Plugin {name!r} {action} in {path}.")

    config = _load_config()
    if config.plugin_enabled(name) != enabled:
        typer.echo(
            f"warning: TRIAL_AL_PLUGINS__{name.upper()}__ENABLED overrides the file", err=True
        )
    for status in inspect_plugins(config):
        if status.enabled and status.installed:
            for problem in status.problems:
                typer.echo(f"warning: {status.name}: {problem}", err=True)


def _load_config() -> Config:
    try:
        return load_config()
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
