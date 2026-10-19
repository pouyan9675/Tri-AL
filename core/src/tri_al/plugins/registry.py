"""What a plugin's ``register`` function receives (docs/design.md §5.6)."""

import dataclasses
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, NoReturn

import typer
from pydantic import BaseModel

from tri_al.access import AccessPolicy
from tri_al.filters import FilterField, TrialFilter
from tri_al.jobs.worker import JobType
from tri_al.pipeline.events import EVENTS, Handler, Subscription
from tri_al.pipeline.source import Source
from tri_al.plugins.errors import PluginError
from tri_al.search import SearchProvider
from tri_al.stats.charts import Chart, Derived
from tri_al.storage import Migration, MigrationError, SqliteExtension
from tri_al.storage.migrations import check_migrations

if TYPE_CHECKING:
    from fastapi import APIRouter

CORE_JOBS = frozenset({"install", "update", "rebuild"})
CORE_FILTER_FIELDS = frozenset(f.name for f in dataclasses.fields(TrialFilter))

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
    # by chart id, in plugin load order
    charts: dict[str, Chart] = field(default_factory=dict)
    # by name, in plugin load order
    derived: dict[str, Derived] = field(default_factory=dict)
    # by field name
    filter_fields: dict[str, FilterField] = field(default_factory=dict)
    # by provider name
    search_providers: dict[str, SearchProvider] = field(default_factory=dict)
    # by plugin
    routes: dict[str, "APIRouter"] = field(default_factory=dict)
    # by job type
    jobs: dict[str, JobType] = field(default_factory=dict)
    # (plugin, policy), if a plugin set one
    access_policy: tuple[str, AccessPolicy] | None = None

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
        """Mount ``app`` as the command group ``tri-al <plugin>``."""
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
                "fetch_changed, normalize and hashable (see tri_al.pipeline.Source)"
            )
        if source.name in self._contributions.sources:
            raise PluginError(f"a source named {source.name!r} was already added")
        self._contributions.sources[source.name] = source

    def on(self, event: str, handler: Handler) -> None:
        """Call ``handler(event)`` when the pipeline fires ``event`` (docs/design.md §5.6).

        Events: ``update.started``, ``trials.changed``, ``update.finished`` and
        ``install.finished``; see ``tri_al.pipeline.events`` for what each carries.
        """
        if event not in EVENTS:
            raise PluginError(f"unknown event {event!r}; events are {', '.join(EVENTS)}")
        subscription = Subscription(self._plugin, handler)
        self._contributions.subscriptions.setdefault(event, []).append(subscription)

    def add_chart(self, chart: Chart) -> None:
        """A chart for the dashboard (docs/design.md §5.5); its id must be unique."""
        if not isinstance(chart, Chart):
            raise PluginError(f"{type(chart).__name__} isn't a tri_al.stats.Chart")
        existing = self._contributions.charts.get(chart.id)
        if existing is not None:
            raise PluginError(f"chart {chart.id!r} was already added by plugin {existing.plugin!r}")
        self._contributions.charts[chart.id] = dataclasses.replace(chart, plugin=self._plugin)

    def add_derived(self, derived: Derived) -> None:
        """Tables to rebuild before each precompute of the charts (``tri_al.stats.Derived``)."""
        if not isinstance(derived, Derived):
            raise PluginError(f"{type(derived).__name__} isn't a tri_al.stats.Derived")
        existing = self._contributions.derived.get(derived.name)
        if existing is not None:
            raise PluginError(
                f"derived tables {derived.name!r} were already added by plugin {existing.plugin!r}"
            )
        self._contributions.derived[derived.name] = dataclasses.replace(
            derived, plugin=self._plugin
        )

    def add_filter_field(self, filter_field: FilterField) -> None:
        """A filter field over the plugin's own tables, for the trial list, charts and facets.

        Its ``name`` becomes a query parameter of ``/api/trials`` and friends, so it can't
        be a core field's.
        """
        if not isinstance(filter_field, FilterField):
            raise PluginError(f"{type(filter_field).__name__} isn't a tri_al.filters.FilterField")
        name = filter_field.name
        if name in CORE_FILTER_FIELDS or name in ("sort", "cursor", "limit", "fields"):
            raise PluginError(f"filter field {name!r} is a core name; prefix it with the plugin's")
        if name in self._contributions.filter_fields:
            raise PluginError(f"filter field {name!r} was already added")
        self._contributions.filter_fields[name] = dataclasses.replace(
            filter_field, plugin=self._plugin
        )

    def add_search_provider(self, provider: SearchProvider) -> None:
        """Another search behind ``/api/search``; results merge with full-text search."""
        if not isinstance(provider, SearchProvider):
            raise PluginError(
                f"{type(provider).__name__} isn't a search provider: it needs name and "
                "search (see tri_al.search.SearchProvider)"
            )
        if provider.name == "fts" or provider.name in self._contributions.search_providers:
            raise PluginError(f"a search provider named {provider.name!r} was already added")
        self._contributions.search_providers[provider.name] = provider

    def add_routes(self, router: "APIRouter") -> None:
        """API routes, mounted at ``/api/x/<plugin>/``; guard each with ``access.require``."""
        from fastapi import APIRouter

        if not isinstance(router, APIRouter):
            raise PluginError(f"{type(router).__name__} isn't a fastapi.APIRouter")
        if self._plugin in self._contributions.routes:
            raise PluginError(f"plugin {self._plugin!r} already added routes")
        self._contributions.routes[self._plugin] = router

    def add_job(self, job: JobType) -> None:
        """A kind of background job the worker runs (``tri_al.jobs.JobType``)."""
        if not isinstance(job, JobType):
            raise PluginError(f"{type(job).__name__} isn't a tri_al.jobs.JobType")
        if job.name in CORE_JOBS or job.name in self._contributions.jobs:
            raise PluginError(f"a job type named {job.name!r} already exists")
        self._contributions.jobs[job.name] = dataclasses.replace(job, plugin=self._plugin)

    def set_access_policy(self, policy: AccessPolicy) -> None:
        """Replace the core's allow-everything policy, as an ``auth`` plugin would (§5.8)."""
        if not isinstance(policy, AccessPolicy):
            raise PluginError(f"{type(policy).__name__} isn't an access policy: it needs allows()")
        if self._contributions.access_policy is not None:
            owner = self._contributions.access_policy[0]
            raise PluginError(f"plugin {owner!r} already set the access policy")
        self._contributions.access_policy = (self._plugin, policy)

    # The rest of the base registry API arrives with later milestones (design §14).

    def add_enricher(self, enricher: object) -> None:
        _not_yet("add_enricher")


def _not_yet(method: str) -> NoReturn:
    raise NotImplementedError(f"Registry.{method} is not implemented yet")
