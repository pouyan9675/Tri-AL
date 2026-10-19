"""The data pipeline: install and update (docs/design.md §5.3 and §8).

Both run the same stages; only the fetch differs:

    fetch ─▶ parse ─▶ normalize ─▶ hash check ─▶ write ─▶ enrich ─▶ stats ─▶ commit
          ─▶ bump data_version ─▶ events

An install builds ``trials.db.new`` in bulk-load mode, checks it, then renames it over
``trials.db``, checkpointing each stage in ``runs`` so a re-run carries on where a failed
one stopped. An update writes everything in one ``BEGIN IMMEDIATE`` transaction, so readers
see the old data until it commits. Milestone 4 runs both as background jobs; ``progress``
is how they report, and a progress callback may raise to stop a run.
"""

from __future__ import annotations

import itertools
import logging
import os
import queue
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.exc import DatabaseError

from tri_al import embeddings
from tri_al.embeddings import EmbeddingEngine
from tri_al.pipeline import changes as change_log
from tri_al.pipeline.events import (
    Event,
    InstallFinished,
    Subscription,
    TrialsChanged,
    UpdateFinished,
    UpdateStarted,
    fire,
)
from tri_al.pipeline.prepare import default_workers, prepare, prepared
from tri_al.pipeline.runs import (
    DATA_VERSION,
    Run,
    cursor_key,
    data_version,
    fail_run,
    finish_run,
    get_meta,
    latest_run,
    save_checkpoint,
    set_meta,
    start_run,
)
from tri_al.pipeline.source import (
    FetchContext,
    Progress,
    ProgressCallback,
    Source,
    ignore_progress,
)
from tri_al.pipeline.summary import (
    EmbeddingSummary,
    RenormalizeSummary,
    RunSummary,
    SourceCounts,
    StatsSummary,
)
from tri_al.schema import TrialRecord
from tri_al.stats import CORE_FACETS, Chart, Derived, Facet, precompute
from tri_al.storage import (
    BulkLoader,
    Migration,
    SqliteExtension,
    SQLiteStorage,
    StorageError,
    docs,
    open_app_db,
)
from tri_al.storage import tables as t

if TYPE_CHECKING:
    from tri_al.config import Config
    from tri_al.plugins import LoadedPlugins

BATCH_SIZE = 5_000
"""Trials written per batch; each bulk-load batch is its own transaction."""

UPDATE_OVERLAP = timedelta(days=1)
"""An update fetches from the day before its cursor. Dates have day precision, so this
catches studies posted later on the cursor's day; the hash check makes the overlap free."""


class PipelineError(Exception):
    """The pipeline can't run as asked, such as an update before any install."""


log = logging.getLogger(__name__)

EMBED_BATCH = 2_048
"""Trials an embedding backfill encodes and writes at a time."""


@dataclass(frozen=True, kw_only=True)
class Pipeline:
    """Install and update for the trials in ``data_dir``, from ``sources``."""

    data_dir: Path
    sources: Sequence[Source]
    extensions: Sequence[SqliteExtension] = ()
    trials_migrations: Mapping[str, Sequence[Migration]] = field(default_factory=dict)
    app_migrations: Mapping[str, Sequence[Migration]] = field(default_factory=dict)
    subscriptions: Mapping[str, Sequence[Subscription]] = field(default_factory=dict)
    charts: Sequence[Chart] = ()  # precomputed with every install and update
    derived: Sequence[Derived] = ()  # rebuilt just before the charts
    facets: Sequence[Facet] = CORE_FACETS
    workers: int = field(default_factory=default_workers)  # 0: normalize in this process
    batch_size: int = BATCH_SIZE
    check_full_text: bool = True  # an install checks its full-text indexes before the swap
    embedder: EmbeddingEngine | None = None

    @classmethod
    def from_plugins(
        cls,
        config: Config,
        plugins: LoadedPlugins,
        *,
        data_dir: Path | None = None,
        workers: int | None = None,
    ) -> Self:
        """A pipeline for the enabled plugins' sources, migrations, extensions and handlers."""
        contributions = plugins.contributions
        embedder = None
        if config.embeddings.enabled:
            embedder = embeddings.create_engine(
                config.embeddings.engine,
                config.embeddings.model,
                max_tokens=config.embeddings.max_tokens,
                batch_size=config.embeddings.batch_size,
                device=config.embeddings.device,
                float16=config.embeddings.float16,
            )
        return cls(
            data_dir=config.data.dir if data_dir is None else data_dir,
            sources=list(contributions.sources.values()),
            extensions=list(contributions.sqlite_extensions.values()),
            trials_migrations=contributions.migrations_for("trials"),
            app_migrations=contributions.migrations_for("app"),
            subscriptions={
                event: list(subs) for event, subs in contributions.subscriptions.items()
            },
            charts=list(contributions.charts.values()),
            derived=list(contributions.derived.values()),
            workers=default_workers() if workers is None else workers,
            embedder=embedder,
        )

    @property
    def trials_db(self) -> Path:
        return self.data_dir / "trials.db"

    @property
    def new_db(self) -> Path:
        """Where an install builds the database before it replaces ``trials.db``."""
        return self.data_dir / "trials.db.new"

    @property
    def app_db(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def downloads(self) -> Path:
        return self.data_dir / "downloads"

    # --- install ----------------------------------------------------------------------------

    def run_install(
        self,
        progress: ProgressCallback = ignore_progress,
        *,
        from_file: Path | None = None,
        force: bool = False,
    ) -> RunSummary:
        """Fetch every trial into a new database and swap it in for ``trials.db``.

        ``from_file`` is a local copy of the bulk download, for a single source. If a
        previous install failed or was interrupted, this carries on from its last finished
        stage, and reuses its complete download. Raises PipelineError if ``trials.db``
        already exists, unless ``force``; a forced install starts the change log over.
        """
        self._check_sources()
        if from_file is not None:
            if len(self.sources) != 1:
                raise PipelineError("a bulk file can only be used with exactly one source")
            if not from_file.is_file():
                raise PipelineError(f"{from_file} is not a file")
        if self.trials_db.exists() and not force:
            raise PipelineError(
                f"{self.trials_db} already exists; run `tri-al update` to bring it up to "
                "date, or install with --force to rebuild it (the change log starts over)"
            )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        open_app_db(
            self.app_db, extensions=self.extensions, plugin_migrations=self.app_migrations
        ).dispose()

        storage, run, resumed = self._open_install()
        with storage:
            summary = _Install(self, storage, run, progress, from_file, resumed).run()
        started = time.monotonic()
        progress(Progress("swap"))
        self._swap()
        summary.stages["swap"] = time.monotonic() - started
        self.notify(summary, InstallFinished(summary))
        return summary

    def _open_install(self) -> tuple[SQLiteStorage, Run, bool]:
        """The install database and its run: an unfinished one to resume, or a new one."""
        if self.new_db.exists():
            try:
                storage = self._open(self.new_db)
            except (StorageError, DatabaseError):
                _remove_database(self.new_db)
            else:
                with storage.engine.begin() as conn:
                    run = latest_run(conn, "install")
                if run is not None:
                    return storage, run, True
                storage.close()
                _remove_database(self.new_db)
        storage = self._open(self.new_db)
        with storage.engine.begin() as conn:
            run = start_run(conn, "install")
        return storage, run, False

    def _swap(self) -> None:
        """Rename the new database over ``trials.db``, which nothing may have open."""
        if self.trials_db.exists():
            # Fold the old database's WAL into it; closing the last connection deletes the
            # WAL, which would otherwise be read as part of the new file.
            conn = sqlite3.connect(self.trials_db)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()
        for path in (self.trials_db, self.new_db):
            for suffix in ("-wal", "-shm"):
                if Path(f"{path}{suffix}").exists():
                    raise PipelineError(
                        f"{path} is open in another process (its {suffix[1:].upper()} file is "
                        "still there); stop `tri-al serve` and run the install again"
                    )
        os.replace(self.new_db, self.trials_db)

    def current_data_version(self) -> int:
        """``trials.db``'s data version, or 0 if there isn't one."""
        if not self.trials_db.exists():
            return 0
        conn = sqlite3.connect(f"file:{self.trials_db}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (DATA_VERSION,)).fetchone()
        except sqlite3.Error:
            return 0
        finally:
            conn.close()
        return 0 if row is None else int(row[0])

    # --- update -----------------------------------------------------------------------------

    def run_update(self, progress: ProgressCallback = ignore_progress) -> RunSummary:
        """Fetch the trials changed since the last update and write them in one transaction."""
        self._check_sources()
        if not self.trials_db.exists():
            raise PipelineError(
                f"there's no database at {self.trials_db} yet; run `tri-al install` first"
            )
        with self._open(self.trials_db) as storage:
            return _Update(self, storage, progress).run()

    def run_embedding_backfill(
        self,
        progress: ProgressCallback = ignore_progress,
        *,
        force: bool = False,
        batch_size: int = EMBED_BATCH,
    ) -> EmbeddingSummary:
        """Embed every trial without a vector from the configured model (all with ``force``).

        Newest trials first, so the recent window that charts use fills first. A thread
        reads the next batch's text while the model encodes this one, and each batch is
        written in its own short transaction, never holding the write lock while the model
        runs; a trial an update changed in the meantime is left to that update. Stopping
        loses at most a batch: the next run carries on. When vectors were written, the data
        version goes up and the stats are recomputed, since charts read the vectors.
        """
        engine = self.embedder
        if engine is None:
            raise PipelineError("embeddings are off in tri-al.toml ([embeddings] enabled)")
        if not self.trials_db.exists():
            raise PipelineError(
                f"there's no database at {self.trials_db} yet; run `tri-al install` first"
            )
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        summary = EmbeddingSummary(engine=engine.name, model=engine.model)
        with self._open(self.trials_db) as storage:
            started = time.monotonic()
            progress(Progress("model", message=engine.model))
            dimensions = engine.encode(["warm up"]).shape[1]  # loads the model
            with storage.transaction() as tx:
                model = embeddings.model_for(tx.connection, engine, dimensions)
            with storage.engine.connect() as conn:
                ids = embeddings.stale_trials(conn, model, force=force)
            summary.stages["model"] = round(time.monotonic() - started, 3)

            started = time.monotonic()
            total = len(ids)
            progress(Progress("embed", 0, total, "trials"))
            done = 0
            batches = [list(b) for b in itertools.batched(ids, batch_size, strict=False)]
            with _Prefetch(storage, batches) as texts:
                for batch in texts:
                    vectors = engine.encode([text.text for text in batch])
                    with storage.transaction() as tx:
                        current = {
                            text.trial_id for text in embeddings.unchanged(tx.connection, batch)
                        }
                        keep = [i for i, text in enumerate(batch) if text.trial_id in current]
                        embeddings.store(
                            tx.connection, model, [batch[i].trial_id for i in keep], vectors[keep]
                        )
                    summary.trials += len(keep)
                    summary.skipped += len(batch) - len(keep)
                    done += len(batch)
                    progress(Progress("embed", done, total, "trials"))
            summary.stages["embed"] = round(time.monotonic() - started, 3)

            if summary.trials:
                started = time.monotonic()
                progress(Progress("stats"))
                summary.stats_errors = self._new_stats(storage)
                summary.stages["stats"] = round(time.monotonic() - started, 3)
            with storage.engine.connect() as conn:
                summary.data_version = data_version(conn)
        return summary

    def run_renormalize(self, progress: ProgressCallback = ignore_progress) -> RenormalizeSummary:
        """Normalize every stored trial again from its raw document, with today's sources.

        For when a source plugin learns to read more of its documents, such as arms and
        design, so trials stored before get the new fields without a new install. Each
        batch is its own short transaction (``StorageTransaction.refresh``): a trial whose
        record comes out the same is left alone; one whose lists and searchable text are
        the same gets its other fields and text rewritten in place, keeping its full-text
        row and vector; any other is written in full and embedded again. The change log
        gets nothing, since the registry didn't change the trials. Stopping keeps the
        batches done; running again carries on, past them quickly. When anything was
        written, the data version goes up and the stats are recomputed.
        """
        self._check_sources()
        if not self.trials_db.exists():
            raise PipelineError(
                f"there's no database at {self.trials_db} yet; run `tri-al install` first"
            )
        sources = {source.name: source for source in self.sources}
        summary = RenormalizeSummary()
        with self._open(self.trials_db) as storage:
            started = time.monotonic()
            with storage.engine.connect() as conn:
                ids = conn.execute(select(t.trials.c.id).order_by(t.trials.c.id)).scalars().all()
            total = len(ids)
            progress(Progress("normalize", 0, total, "trials"))
            derived: dict[int, TrialRecord] = {}

            def derive(stored: TrialRecord) -> TrialRecord | None:
                source = sources.get(stored.source)
                if source is None or stored.raw is None or stored.id is None:
                    summary.skipped += 1
                    return None
                prepared_ = prepare(source, stored.raw)
                record = prepared_.record
                if record is None or record.source_id != stored.source_id:
                    found = None if record is None else f"a record for {record.source_id}"
                    summary.add_failure(
                        f"{stored.source}/{stored.source_id}: {prepared_.error or found}"
                    )
                    return None
                derived[stored.id] = record
                return record

            for batch in itertools.batched(ids, self.batch_size, strict=False):
                derived.clear()
                with storage.transaction() as tx:
                    result = tx.refresh(batch, derive)
                    replaced = [(trial_id, derived[trial_id]) for trial_id in result.replaced]
                    if error := self.enrich(tx.connection, replaced):
                        summary.embedding_error = error
                summary.trials += len(batch)
                summary.unchanged += len(result.unchanged)
                summary.rewritten += len(result.rewritten)
                summary.replaced += len(result.replaced)
                progress(Progress("normalize", summary.trials, total, "trials"))
            summary.stages["normalize"] = round(time.monotonic() - started, 3)

            if summary.rewritten or summary.replaced:
                started = time.monotonic()
                progress(Progress("stats"))
                summary.stats_errors = self._new_stats(storage)
                summary.stages["stats"] = round(time.monotonic() - started, 3)
            with storage.engine.connect() as conn:
                summary.data_version = data_version(conn)
        return summary

    def run_stats(self, progress: ProgressCallback = ignore_progress) -> StatsSummary:
        """Rebuild the derived tables and precomputed stats now, under a new data version.

        For when what they're made from changed but the data didn't: a plugin's settings,
        such as the cluster map's, or a chart's code. The data version goes up, so API
        caches and browsers fetch the new results.
        """
        if not self.trials_db.exists():
            raise PipelineError(
                f"there's no database at {self.trials_db} yet; run `tri-al install` first"
            )
        summary = StatsSummary()
        with self._open(self.trials_db) as storage:
            started = time.monotonic()
            progress(Progress("stats"))
            summary.stats_errors = self._new_stats(storage)
            summary.stages["stats"] = round(time.monotonic() - started, 3)
            with storage.engine.connect() as conn:
                summary.data_version = data_version(conn)
        return summary

    def _new_stats(self, storage: SQLiteStorage) -> list[str]:
        """Bump the data version and recompute the stats for it, in one transaction."""
        with storage.transaction() as tx:
            version = data_version(tx.connection) + 1
            set_meta(tx.connection, DATA_VERSION, str(version))
            return self.compute_stats(tx.connection, version)

    # --- enrich and stats ----------------------------------------------------------------------

    def enrich(
        self, conn: Connection, trials: Sequence[tuple[int, TrialRecord]] | None
    ) -> str | None:
        """Embed new and changed trials, in the update's transaction; an error, or None.

        Installs pass ``None``: ``tri-al embeddings generate`` embeds them afterwards. The
        trial writer has already removed the old vectors of changed trials. A model that
        fails doesn't stop the update: its trials stay without vectors until the next
        backfill, and the error goes in the run summary.
        """
        if not trials or self.embedder is None:
            return None
        try:
            texts = [embeddings.trial_embedding_text(record) for _, record in trials]
            vectors = self.embedder.encode(texts)
            model = embeddings.model_for(conn, self.embedder, vectors.shape[1])
        except Exception as exc:
            log.warning("embedding %d trials failed: %s", len(trials), exc, exc_info=True)
            return f"{type(exc).__name__}: {exc}"
        embeddings.store(conn, model, [trial_id for trial_id, _ in trials], vectors)
        return None

    def compute_stats(self, conn: Connection, data_version: int) -> list[str]:
        """Store the precomputed charts and facets for ``data_version``; return errors.

        Runs in the caller's transaction, so readers get the new stats with the new data.
        Derived tables are rebuilt first, since charts may read them.
        """
        errors: list[str] = []
        for derived in self.derived:
            try:
                with conn.begin_nested():
                    derived.build(conn, data_version)
            except Exception as exc:
                log.exception("stats: derived tables %s failed", derived.name)
                errors.append(f"{derived.name}: {exc!r}")
        return errors + precompute(conn, self.charts, self.facets, data_version)

    def stats_are_current(self, conn: Connection, data_version: int) -> bool:
        """Whether ``stats`` holds every precomputed chart and facet for ``data_version``."""
        wanted = {chart.id for chart in self.charts if chart.precompute}
        wanted |= {f"facet:{facet.field}" for facet in self.facets}
        stored = set(
            conn.execute(
                select(t.stats.c.chart_id).where(t.stats.c.data_version == data_version)
            ).scalars()
        )
        return wanted <= stored

    # --- helpers ----------------------------------------------------------------------------

    def _check_sources(self) -> None:
        if not self.sources:
            raise PipelineError(
                "no source plugin is enabled, so there's nothing to fetch trials from; "
                "install tri-al-ctgov or run `tri-al plugins enable ctgov`"
            )

    def _open(self, path: Path) -> SQLiteStorage:
        return SQLiteStorage.open(
            path, extensions=self.extensions, plugin_migrations=self.trials_migrations
        )

    def notify(self, summary: RunSummary, event: Event) -> None:
        """Send ``event`` to its handlers, noting in ``summary`` any that raised."""
        summary.handler_errors += fire(self.subscriptions, event)


class _Install:
    def __init__(
        self,
        pipeline: Pipeline,
        storage: SQLiteStorage,
        run: Run,
        progress: ProgressCallback,
        from_file: Path | None,
        resumed: bool,
    ) -> None:
        self.pipeline = pipeline
        self.storage = storage
        self.run_ = run
        self.progress = progress
        self.from_file = from_file
        self.resumed = resumed
        self.summary = RunSummary(run_id=run.id, kind="install")
        if resumed:
            self.summary.notes["resumed"] = True

    def run(self) -> RunSummary:
        try:
            if self.run_.status == "finished":
                # Everything but the swap happened before.
                with self.storage.engine.connect() as conn:
                    self.summary.data_version = data_version(conn)
            else:
                self._build()
        except BaseException as exc:
            with suppress(Exception), self.storage.engine.begin() as conn:
                fail_run(conn, self.run_, exc, self.summary)
            raise
        self.summary.stages = dict(self.run_.stages_done) | self.summary.stages
        return self.summary

    def _build(self) -> None:
        done = self.run_.stages_done
        sources = self.pipeline.sources
        loads = {s.name: "load" if len(sources) == 1 else f"load:{s.name}" for s in sources}
        with self.storage.engine.begin() as conn:
            save_checkpoint(conn, self.run_)  # mark a resumed run as running again
        if "index" not in done:
            with self.storage.bulk_load() as loader:
                for source in sources:
                    if loads[source.name] not in done:
                        with self._stage(loads[source.name]):
                            self._load(source, loader, loads[source.name])
                started = time.monotonic()
                self.progress(Progress("index", message="building indexes and full-text search"))
            self._checkpoint("index", time.monotonic() - started)
        version = self.pipeline.current_data_version() + 1

        def stats(conn: Connection) -> None:
            self.summary.stats_errors = self.pipeline.compute_stats(conn, version)

        def enrich(conn: Connection) -> None:
            self.pipeline.enrich(conn, None)  # every trial is new: the backfill embeds them

        stages: dict[str, Callable[[Connection], None]] = {"enrich": enrich, "stats": stats}
        for stage, action in stages.items():
            if stage not in done:
                # The stage's writes and its checkpoint commit together.
                started = time.monotonic()
                self.progress(Progress(stage))
                with self.storage.engine.begin() as conn:
                    action(conn)
                    self.run_.stages_done[stage] = round(time.monotonic() - started, 3)
                    save_checkpoint(conn, self.run_)
        if "check" not in done:
            with self._stage("check"):
                self._check()
        self._finish()

    def _load(self, source: Source, loader: BulkLoader, stage: str) -> None:
        ctx = FetchContext(
            downloads=self.pipeline.downloads,
            progress=self.progress,
            from_file=self.from_file,
            reuse_download=self.resumed,
        )
        known = loader.content_hashes(source.name) if self.resumed else {}
        counts = self.summary.counts(source.name)
        batch: dict[str, TrialRecord] = {}

        def write() -> None:
            loader.upsert_batch(list(batch.values()))
            for source_id in batch:
                if source_id in known:
                    counts.updated += 1
                else:
                    counts.new += 1
            batch.clear()
            self.progress(Progress(stage, _processed(counts), ctx.total, "trials"))

        raws = _counted(source.fetch_all(ctx), counts)
        for item in prepared(source, raws, workers=self.pipeline.workers):
            if item.record is None:
                self.summary.add_failure(source.name, str(item.error))
                continue
            record = item.record
            if known.get(record.source_id) == record.content_hash:
                counts.unchanged += 1
                continue
            batch[record.source_id] = record
            if len(batch) >= self.pipeline.batch_size:
                write()
        if batch:
            write()
        self.summary.notes[source.name] = ctx.notes

    def _check(self) -> None:
        if self.storage.count_trials() == 0:
            raise PipelineError("the install loaded no trials, so it stopped before the swap")
        self.storage.check(full_text=self.pipeline.check_full_text)

    def _finish(self) -> None:
        version = self.pipeline.current_data_version() + 1
        with self.storage.engine.begin() as conn:
            set_meta(conn, DATA_VERSION, str(version))
            # The stats stage already counted this data; a resumed install may have run it
            # when the old database had another version.
            conn.execute(update(t.stats).values(data_version=version))
            for source in self.pipeline.sources:
                latest = _latest_update(conn, source.name)
                if latest is not None:
                    set_meta(conn, cursor_key(source.name), latest.isoformat())
            self.summary.data_version = version
            self.summary.stages = dict(self.run_.stages_done)
            finish_run(conn, self.run_, self.summary)

    @contextmanager
    def _stage(self, stage: str) -> Iterator[None]:
        started = time.monotonic()
        self.progress(Progress(stage))
        yield
        self._checkpoint(stage, time.monotonic() - started)

    def _checkpoint(self, stage: str, seconds: float) -> None:
        self.run_.stages_done[stage] = round(seconds, 3)
        with self.storage.engine.begin() as conn:
            save_checkpoint(conn, self.run_)


@dataclass
class _Fetched:
    source: Source
    changed: list[TrialRecord]  # new trials and trials whose hash differs
    known: dict[str, bytes | None]  # stored hashes of the fetched trials that exist
    cursor: date
    latest: date | None  # the latest last_update fetched


class _Update:
    def __init__(self, pipeline: Pipeline, storage: SQLiteStorage, progress: ProgressCallback):
        self.pipeline = pipeline
        self.storage = storage
        self.progress = progress
        with storage.engine.begin() as conn:
            self.run_ = start_run(conn, "update")
        self.summary = RunSummary(run_id=self.run_.id, kind="update")

    def run(self) -> RunSummary:
        summary = self.summary
        try:
            self.pipeline.notify(summary, UpdateStarted(self.run_.id))
            with self._timed("fetch", report=False):  # _fetch reports, per source
                fetched = [self._fetch(source) for source in self.pipeline.sources]
            new_ids, updated_ids = self._write(fetched)
        except BaseException as exc:
            with suppress(Exception), self.storage.engine.begin() as conn:
                fail_run(conn, self.run_, exc, summary)
            raise
        errors_before = len(summary.handler_errors)
        changed: tuple[tuple[list[int], Literal["new", "updated"]], ...] = (
            (new_ids, "new"),
            (updated_ids, "updated"),
        )
        for ids, kind in changed:
            if ids:
                self.pipeline.notify(summary, TrialsChanged(self.run_.id, tuple(ids), kind))
        self.pipeline.notify(summary, UpdateFinished(summary))
        if len(summary.handler_errors) > errors_before:
            with self.storage.engine.begin() as conn:
                finish_run(conn, self.run_, summary)
        return summary

    def _fetch(self, source: Source) -> _Fetched:
        with self.storage.engine.connect() as conn:
            cursor = get_meta(conn, cursor_key(source.name))
        if cursor is None:
            raise PipelineError(
                f"source {source.name!r} has no update cursor, so it was never installed; "
                "run `tri-al install --force`"
            )
        since = date.fromisoformat(cursor) - UPDATE_OVERLAP
        ctx = FetchContext(downloads=self.pipeline.downloads, progress=self.progress)
        counts = self.summary.counts(source.name)
        self.progress(Progress("fetch", message=f"{source.name}: changed since {since}"))
        records: dict[str, TrialRecord] = {}
        raws = _counted(source.fetch_changed(since, ctx), counts, self.progress, ctx)
        for item in prepared(source, raws, workers=0):
            if item.record is None:
                self.summary.add_failure(source.name, str(item.error))
            else:
                records[item.record.source_id] = item.record
        known = self.storage.content_hashes(source.name, records)
        changed = [r for r in records.values() if known.get(r.source_id) != r.content_hash]
        counts.unchanged = len(records) - len(changed)
        self.summary.notes[source.name] = {"since": since.isoformat(), **ctx.notes}
        latest = max((r.last_update for r in records.values() if r.last_update), default=None)
        return _Fetched(source, changed, known, date.fromisoformat(cursor), latest)

    def _write(self, fetched: Sequence[_Fetched]) -> tuple[list[int], list[int]]:
        new_ids: list[int] = []
        updated_ids: list[int] = []
        changed_records: list[tuple[int, TrialRecord]] = []
        total = sum(len(f.changed) for f in fetched)
        stages = self.summary.stages
        started = time.monotonic()
        self.progress(Progress("write", 0, total, "trials"))
        with self.storage.transaction() as tx:
            conn = tx.connection
            for f in fetched:
                counts = self.summary.counts(f.source.name)
                old = {
                    r.source_id: tx.find_trial(f.source.name, r.source_id)
                    for r in f.changed
                    if r.source_id in f.known
                }
                change_rows: list[dict[str, Any]] = []
                for chunk in itertools.batched(f.changed, self.pipeline.batch_size, strict=False):
                    ids = tx.upsert_batch(chunk)
                    for record, trial_id in zip(chunk, ids, strict=True):
                        changed_records.append((trial_id, record))
                        before = old.get(record.source_id)
                        if before is None:
                            new_ids.append(trial_id)
                            counts.new += 1
                            continue
                        updated_ids.append(trial_id)
                        counts.updated += 1
                        change_rows += (
                            {"trial_id": trial_id, "run_id": self.run_.id, "field": name}
                            | {"old": old_value, "new": new_value}
                            for name, old_value, new_value in change_log.changes(before, record)
                        )
                    done = len(new_ids) + len(updated_ids)
                    self.progress(Progress("write", done, total, "trials"))
                if change_rows:
                    conn.execute(insert(t.trial_changes), change_rows)
                if f.latest is not None and f.latest > f.cursor:
                    set_meta(conn, cursor_key(f.source.name), f.latest.isoformat())
            stages["write"] = round(time.monotonic() - started, 3)

            changed_ids = new_ids + updated_ids
            with self._timed("enrich"):
                error = self.pipeline.enrich(conn, changed_records)
            if error is not None:
                self.summary.notes["embeddings"] = {
                    "error": error,
                    "trials": len(changed_records),
                    "fix": "run `tri-al embeddings generate`",
                }

            version = data_version(conn)
            if changed_ids:
                version += 1
                set_meta(conn, DATA_VERSION, str(version))
            self.summary.data_version = version
            if changed_ids or not self.pipeline.stats_are_current(conn, version):
                with self._timed("stats"):
                    self.summary.stats_errors = self.pipeline.compute_stats(conn, version)
            started = time.monotonic()
            self.progress(Progress("commit"))
            finish_run(conn, self.run_, self.summary)
        stages["commit"] = round(time.monotonic() - started, 3)
        return new_ids, updated_ids

    @contextmanager
    def _timed(self, stage: str, *, report: bool = True) -> Iterator[None]:
        started = time.monotonic()
        if report:
            self.progress(Progress(stage))
        yield
        self.summary.stages[stage] = round(time.monotonic() - started, 3)


def _counted(
    raws: Iterable[bytes],
    counts: SourceCounts,
    progress: ProgressCallback | None = None,
    ctx: FetchContext | None = None,
    every: int = 1_000,
) -> Iterator[bytes]:
    """``raws``, counting each in ``counts.fetched`` (and reporting every ``every``)."""
    for raw in raws:
        counts.fetched += 1
        if progress is not None and counts.fetched % every == 0:
            progress(Progress("fetch", counts.fetched, ctx.total if ctx else None, "trials"))
        yield raw


def _processed(counts: SourceCounts) -> int:
    return counts.new + counts.updated + counts.unchanged + counts.failed


def _latest_update(conn: Connection, source: str) -> date | None:
    latest: date | None = conn.execute(
        select(func.max(t.trials.c.last_update)).where(t.trials.c.source == source)
    ).scalar_one()
    return latest


def _remove_database(path: Path) -> None:
    for name in (str(path), f"{path}-wal", f"{path}-shm"):
        Path(name).unlink(missing_ok=True)


class _Prefetch:
    """Reads each batch's embedding text in a thread, one batch ahead of the caller.

    Iterating yields the batches' ``TrialText`` lists in order; leaving the ``with`` block
    (finished, or because the caller raised) stops the thread.
    """

    def __init__(self, storage: SQLiteStorage, batches: Sequence[Sequence[int]], ahead: int = 2):
        self._storage = storage
        self._batches = batches
        self._queue: queue.Queue[list[embeddings.TrialText] | BaseException | None] = queue.Queue(
            ahead
        )
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read, name="embedding-texts", daemon=True)

    def __enter__(self) -> Iterator[list[embeddings.TrialText]]:
        self._thread.start()
        return self._iterate()

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        with suppress(queue.Empty):
            while True:  # make room, so a blocked put returns and sees the stop
                self._queue.get_nowait()
        self._thread.join()

    def _iterate(self) -> Iterator[list[embeddings.TrialText]]:
        while (item := self._queue.get()) is not None:
            if isinstance(item, BaseException):
                raise item
            yield item

    def _put(self, item: list[embeddings.TrialText] | BaseException | None) -> bool:
        while not self._stop.is_set():
            with suppress(queue.Full):
                self._queue.put(item, timeout=0.1)
                return True
        return False

    def _read(self) -> None:
        decoder = docs.Decoder()  # decoders aren't shared between threads
        try:
            for batch in self._batches:
                with self._storage.engine.connect() as conn:
                    texts = embeddings.load_texts(conn, batch, decoder)
                if not self._put(texts):
                    return
        except BaseException as exc:
            self._put(exc)
            return
        self._put(None)
