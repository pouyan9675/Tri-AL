"""Sample Tri-AL plugin: shows discovery, settings and CLI registration working end to end.

With it installed, ``tri-al plugins list`` shows ``sample`` and ``tri-al sample hello``
prints a greeting. Set the greeting in ``tri-al.toml``:

    [plugins.sample]
    greeting = "Hi"

or with ``TRI_AL_PLUGINS__SAMPLE__GREETING=Hi``.
"""

from importlib.metadata import version

import typer
from pydantic import BaseModel, ConfigDict

from tri_al.plugins import Plugin, Registry


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    greeting: str = "Hello"


def register(registry: Registry) -> None:
    settings = registry.settings
    assert isinstance(settings, Settings)
    cli = typer.Typer(help="Commands from the sample plugin.", no_args_is_help=True)

    @cli.command()
    def hello(name: str = "world") -> None:
        """Print the configured greeting."""
        typer.echo(f"{settings.greeting}, {name}!")

    registry.add_cli(cli)


plugin = Plugin(
    name="sample",
    version=version("tri-al-sample"),
    api_version=1,
    register=register,
    settings=Settings,
    description="Sample plugin that adds `tri-al sample hello`.",
)
