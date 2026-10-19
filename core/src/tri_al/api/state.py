"""What an API worker holds: the databases, the stats engine and the plugins' parts."""

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import Engine

from tri_al import __version__
from tri_al.access import AccessPolicy, AllowAll
from tri_al.ai import AiService
from tri_al.api.http import etag_for
from tri_al.config import Config
from tri_al.filters import FilterField
from tri_al.jobs import JobQueue
from tri_al.plugins import LoadedPlugins
from tri_al.search import FullTextProvider, SearchProvider
from tri_al.stats import CORE_FACETS, Chart, Facet, StatsEngine
from tri_al.storage import SQLiteReader, SQLiteStorage, open_app_db
from tri_al.terms import TermVectorCache


@dataclass
class ApiState:
    config: Config
    config_path: Path
    plugins: LoadedPlugins
    data_dir: Path
    app_db: Engine
    queue: JobQueue
    charts: list[Chart]
    facets: list[Facet]
    providers: dict[str, SearchProvider]
    filter_fields: dict[str, FilterField]
    access_policy: AccessPolicy
    ai: AiService
    use_index: bool = True
    build: str = ""
    term_vectors: TermVectorCache = field(default_factory=TermVectorCache)
    _storage: SQLiteStorage | None = None
    _stats: StatsEngine | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def create(
        cls,
        config: Config,
        plugins: LoadedPlugins,
        *,
        config_path: Path,
        data_dir: Path | None = None,
        use_index: bool = True,
    ) -> "ApiState":
        contributions = plugins.contributions
        data_dir = config.data.dir if data_dir is None else data_dir
        app_db = open_app_db(
            data_dir / "app.db",
            extensions=list(contributions.sqlite_extensions.values()),
            plugin_migrations=contributions.migrations_for("app"),
        )
        versions = ",".join(f"{p.name}={p.version}" for p in plugins.plugins)
        build = hashlib.blake2b(f"{__version__};{versions}".encode(), digest_size=4).hexdigest()
        policy = contributions.access_policy
        return cls(
            config=config,
            config_path=config_path,
            plugins=plugins,
            data_dir=data_dir,
            app_db=app_db,
            queue=JobQueue(app_db),
            charts=sorted(contributions.charts.values(), key=lambda c: (c.layout.order, c.id)),
            facets=list(CORE_FACETS),
            providers={"fts": FullTextProvider(), **contributions.search_providers},
            filter_fields=dict(contributions.filter_fields),
            access_policy=AllowAll() if policy is None else policy[1],
            ai=AiService(config.ai, config_path, contributions.model_backends),
            use_index=use_index,
            build=build,
        )

    @property
    def trials_db(self) -> Path:
        return self.data_dir / "trials.db"

    def storage(self) -> SQLiteStorage | None:
        """``trials.db``, opened the first time it's there (an install may create it later)."""
        with self._lock:
            if self._storage is None and self.trials_db.exists():
                contributions = self.plugins.contributions
                self._storage = SQLiteStorage.attach(
                    self.trials_db,
                    extensions=list(contributions.sqlite_extensions.values()),
                    plugin_migrations=contributions.migrations_for("trials"),
                )
                self._stats = StatsEngine(
                    self._storage, self.charts, self.facets, use_index=self.use_index
                )
            return self._storage

    def stats(self) -> StatsEngine:
        if self.storage() is None or self._stats is None:
            raise _not_installed()
        return self._stats

    @contextmanager
    def read(self) -> Iterator[SQLiteReader]:
        """A read transaction on ``trials.db``; 503 if there's no data yet."""
        storage = self.storage()
        if storage is None:
            raise _not_installed()
        with storage.read() as reader:
            yield reader

    def etag(self, data_version: int) -> str:
        return etag_for(data_version, self.build)

    def close(self) -> None:
        with self._lock:
            if self._stats is not None:
                self._stats.close()
            if self._storage is not None:
                self._storage.close()
                self._storage = None
                self._stats = None
        self.ai.close()
        self.app_db.dispose()


def _not_installed() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, "there's no data yet; run `tri-al install` first"
    )
