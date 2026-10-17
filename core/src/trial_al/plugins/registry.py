"""What a plugin's ``register`` function receives (docs/design.md §5.6)."""

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, NoReturn

import typer
from pydantic import BaseModel

from trial_al.pipeline.events import EVENTS, Handler, Subscription
from trial_al.pipeline.source import Source
from trial_al.plugins.errors import PluginError
from trial_al.storage import Migration, MigrationError, SqliteExtension
from trial_al.storage.migrations import check_migrations

type Database = Literal["trials", "app"]
DATABASES: tuple[Database, ...] = ("trials", "app")


@dataclass
class Contributions:
    """Everything the enabled plugins registered."""

    # by plugin
    cli: dict[str, typer.Typer] = field(default_factory=dict)
    # by extension name
    sqlite_extensions: dict[str, SqliteExtension] = field(default_factory=dict)
    # by database, then plugin
    migrations: dict[Database, dict[str, tuple[Migration, ...]]] = field(default_factory=dict)
    # by source name
    sources: dict[str, Source] = field(default_factory=dict)
    # by event name, in plugin load order
    subscriptions: dict[str, list[Subscription]] = field(default_factory=dict)

    def migrations_for(self, database: Database) -> dict[str, tuple[Migration, ...]]:
        """Each plugin's migrations for ``database``, in plugin load order."""
        return dict(self.migrations.get(database, {}))


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

    def add_sqlite_extension(self, name: str, load: Callable[[sqlite3.Connection], None]) -> None:
        """Load a SQLite extension into every database connection (docs/design.md §5.2).

        ``load(conn)`` gets each new ``sqlite3.Connection`` with extension loading switched
        on just for the call; ``sqlite_vec.load`` is an example. If it fails, startup stops
        with an error naming this plugin.
        """
        existing = self._contributions.sqlite_extensions.get(name)
        if existing is not None:
            raise PluginError(
                f"SQLite extension {name!r} was already added by plugin {existing.plugin!r}"
            )
        self._contributions.sqlite_extensions[name] = SqliteExtension(name, load, self._plugin)

    def add_migrations(self, database: Database, migrations: Sequence[Migration]) -> None:
        """Migrations for this plugin's own tables in ``trials.db`` or ``app.db``.

        They're tracked under the plugin's name, numbered 1, 2, 3, ..., and run after the
        core's migrations and after every SQLite extension has loaded. Prefix table names
        with the plugin's name.
        """
        if database not in DATABASES:
            raise PluginError(f"unknown database {database!r}; use 'trials' or 'app'")
        per_plugin = self._contributions.migrations.setdefault(database, {})
        if self._plugin in per_plugin:
            raise PluginError(f"plugin {self._plugin!r} already added {database} migrations")
        try:
            check_migrations(self._plugin, migrations)
        except MigrationError as exc:
            raise PluginError(str(exc)) from None
        per_plugin[self._plugin] = tuple(migrations)

    def add_source(self, source: Source) -> None:
        """A registry that ``install`` and ``update`` fetch trials from (docs/design.md §7)."""
        if not isinstance(source, Source):
            raise PluginError(
                f"{type(source).__name__} isn't a source: it needs name, fetch_all, "
                "fetch_changed, normalize and hashable (see trial_al.pipeline.Source)"
            )
        if source.name in self._contributions.sources:
            raise PluginError(f"a source named {source.name!r} was already added")
        self._contributions.sources[source.name] = source

    def on(self, event: str, handler: Handler) -> None:
        """Call ``handler(event)`` when the pipeline fires ``event`` (docs/design.md §5.6).

        Events: ``update.started``, ``trials.changed``, ``update.finished`` and
        ``install.finished``; see ``trial_al.pipeline.events`` for what each carries.
        """
        if event not in EVENTS:
            raise PluginError(f"unknown event {event!r}; events are {', '.join(EVENTS)}")
        subscription = Subscription(self._plugin, handler)
        self._contributions.subscriptions.setdefault(event, []).append(subscription)

    # The rest of the base registry API arrives with later milestones (design §14).

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

    def add_job(self, job: object) -> None:
        _not_yet("add_job")

    def set_access_policy(self, policy: object) -> None:
        _not_yet("set_access_policy")


def _not_yet(method: str) -> NoReturn:
    raise NotImplementedError(f"Registry.{method} is not implemented yet")
