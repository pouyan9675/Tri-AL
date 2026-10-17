"""What a plugin's ``register`` function receives (docs/design.md §5.6)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NoReturn

import typer
from pydantic import BaseModel

from trial_al.plugins.errors import PluginError


@dataclass
class Contributions:
    """Everything the enabled plugins registered, keyed by plugin name."""

    cli: dict[str, typer.Typer] = field(default_factory=dict)


class Registry:
    """The registry as seen by one plugin: contributions are recorded under its name."""

    def __init__(
        self, plugin: str, settings: BaseModel | None, contributions: Contributions
    ) -> None:
        self._plugin = plugin
        self._settings = settings
        self._contributions = contributions

    @property
    def plugin(self) -> str:
        return self._plugin

    @property
    def settings(self) -> BaseModel | None:
        """The validated ``[plugins.<name>]`` section, or None if the plugin has no settings."""
        return self._settings

    def add_cli(self, app: typer.Typer) -> None:
        """Mount ``app`` as the command group ``trial-al <plugin>``."""
        if self._plugin in self._contributions.cli:
            raise PluginError(f"plugin {self._plugin!r} already added a CLI")
        self._contributions.cli[self._plugin] = app

    # The rest of the base registry API arrives with later milestones (design §14).

    def add_source(self, source: object) -> None:
        _not_yet("add_source")

    def add_enricher(self, enricher: object) -> None:
        _not_yet("add_enricher")

    def add_chart(self, chart: object) -> None:
        _not_yet("add_chart")

    def add_filter_field(self, filter_field: object) -> None:
        _not_yet("add_filter_field")

    def add_search_provider(self, provider: object) -> None:
        _not_yet("add_search_provider")

    def add_routes(self, router: object) -> None:
        _not_yet("add_routes")

    def add_migrations(self, migrations: object) -> None:
        _not_yet("add_migrations")

    def add_sqlite_extension(self, name: str, load: Callable[[object], None]) -> None:
        _not_yet("add_sqlite_extension")

    def add_job(self, job: object) -> None:
        _not_yet("add_job")

    def on(self, event: str, handler: Callable[..., object]) -> None:
        _not_yet("on")

    def set_access_policy(self, policy: object) -> None:
        _not_yet("set_access_policy")


def _not_yet(method: str) -> NoReturn:
    raise NotImplementedError(f"Registry.{method} is not implemented yet")
