"""The stats engine (docs/design.md §5.5): precomputed charts, and filtered ones on request.

``precompute`` is the pipeline's stats stage: it computes every chart marked ``precompute``
and every facet with no filter, in the update's transaction, and stores them in ``stats``
with the data version they belong to.

``StatsEngine`` serves them in an API worker. A request with no filter reads the stored
payload as it is. A filtered request is computed from the worker's in-memory
``TrialIndex`` (or SQLite while the index is being built) and kept in an LRU cache keyed by
``(what, filter, data_version)``, so a new data version never sees an old result.
"""

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any, Literal

import numpy as np
import orjson
from sqlalchemy import Connection, delete, insert

from tri_al.filters import EVERY_TRIAL, TrialFilter
from tri_al.stats.charts import Chart, ChartContext, Facet
from tri_al.stats.counts import Count, Counts, SqlCounts
from tri_al.stats.index import Mask, TrialIndex
from tri_al.storage import Cursor, Sort, SQLiteReader, SQLiteStorage, TrialPage
from tri_al.storage import tables as t

log = logging.getLogger(__name__)

FACET_PREFIX = "facet:"
"""``stats.chart_id`` of a precomputed facet: ``facet:status``."""

PRECOMPUTED_FACET_LIMIT = 100
"""Options a precomputed facet keeps; a request for more is computed."""

CACHE_BYTES = 64 * 1024 * 1024
"""What a worker's result cache may hold: payloads and filter masks."""


def precompute(
    conn: Connection, charts: Iterable[Chart], facets: Iterable[Facet], data_version: int
) -> list[str]:
    """Store every precomputed chart and facet for ``data_version``; return errors.

    Runs in the caller's transaction. A chart whose query raises is left out (it will be
    computed on request) and its error returned, so one broken plugin chart doesn't stop
    an update.
    """
    ctx = ChartContext(conn, lambda filter: SqlCounts(conn, filter))
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    work: list[tuple[str, Callable[[], Any]]] = [
        (chart.id, partial(chart.query, ctx, EVERY_TRIAL)) for chart in charts if chart.precompute
    ]
    work += [
        (
            FACET_PREFIX + facet.field,
            partial(_facet_rows, facet, ctx, EVERY_TRIAL, PRECOMPUTED_FACET_LIMIT),
        )
        for facet in facets
    ]
    for chart_id, compute in work:
        try:
            payload = orjson.dumps(compute())
        except Exception as exc:
            log.exception("stats: %s failed", chart_id)
            errors.append(f"{chart_id}: {exc!r}")
            continue
        rows.append(
            {
                "chart_id": chart_id,
                "data_version": data_version,
                "payload": payload,
                "computed_at": now,
            }
        )
    conn.execute(delete(t.stats))
    if rows:
        conn.execute(insert(t.stats), rows)
    return errors


def _facet_rows(
    facet: Facet, ctx: ChartContext, filter: TrialFilter, limit: int
) -> list[dict[str, Any]]:
    return encode_counts(facet.query(ctx, filter, limit))


def encode_counts(counts: Iterable[Count]) -> list[dict[str, Any]]:
    return [{"value": c.value, "label": c.label, "count": c.count} for c in counts]


class ResultCache:
    """A thread-safe LRU cache bounded by the bytes it holds."""

    def __init__(self, max_bytes: int = CACHE_BYTES) -> None:
        self._max = max_bytes
        self._items: OrderedDict[Hashable, tuple[Any, int]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_make(self, key: Hashable, make: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                self.hits += 1
                return self._items[key][0]
            self.misses += 1
        value = make()
        size = _size(value)
        with self._lock:
            if key not in self._items and size <= self._max:
                self._items[key] = (value, size)
                self._bytes += size
                while self._bytes > self._max:
                    _, (_, dropped) = self._items.popitem(last=False)
                    self._bytes -= dropped
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0

    def __len__(self) -> int:
        return len(self._items)


def _size(value: Any) -> int:
    if isinstance(value, bytes):
        return len(value) + 64
    if isinstance(value, np.ndarray):
        return int(value.nbytes) + 128
    if isinstance(nbytes := getattr(value, "nbytes", None), int):
        return nbytes + 1024
    return 1024


@dataclass(frozen=True, slots=True)
class ChartData:
    chart_id: str
    data_version: int
    filtered: bool
    rows: bytes  # the rows as JSON
    source: Literal["precomputed", "computed", "cached"]


class UnknownChart(LookupError):
    pass


class IndexUnavailable(RuntimeError):
    """The trial index for a data version isn't ready (or the data moved on meanwhile)."""


class StatsEngine:
    """Charts, facets, counts and trial pages for one API worker.

    The worker's ``TrialIndex`` is built in a background thread the first time a data
    version is asked for; until it is ready, answers come from SQLite.
    """

    def __init__(
        self,
        storage: SQLiteStorage,
        charts: Sequence[Chart] = (),
        facets: Sequence[Facet] = (),
        *,
        use_index: bool = True,
        cache_bytes: int = CACHE_BYTES,
    ) -> None:
        self.storage = storage
        self.charts = {chart.id: chart for chart in charts}
        self.facets = {facet.field: facet for facet in facets}
        self.use_index = use_index
        self.cache = ResultCache(cache_bytes)
        self._index: TrialIndex | None = None
        self._building: int | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._built = threading.Condition(self._lock)
        self._cache_version: int | None = None

    # --- the index --------------------------------------------------------------------------

    def index_for(self, data_version: int) -> TrialIndex | None:
        """The index for ``data_version`` if it's ready; otherwise start building it."""
        if not self.use_index:
            return None
        with self._lock:
            index = self._index
            if index is not None and index.data_version == data_version:
                return index
            if self._building is None:
                self._building = data_version
                self._thread = threading.Thread(target=self._build, name="trial-index", daemon=True)
                self._thread.start()
        return None

    def close(self) -> None:
        """Wait for an index being built, so its connection is back before storage closes."""
        thread = self._thread
        if thread is not None:
            thread.join()

    def build_index(self) -> TrialIndex:
        """Build the index for the latest data now, in this thread."""
        with self.storage.read() as reader:
            index = TrialIndex.build(reader.connection, reader.data_version())
        with self._lock:
            if self._index is None or self._index.data_version <= index.data_version:
                self._index = index
            self._built.notify_all()
        return index

    def wait_for_index(self, data_version: int, timeout: float = 60.0) -> TrialIndex | None:
        """Start building the index for ``data_version`` if needed, and wait for it."""
        if self.index_for(data_version) is not None:
            return self._index
        with self._built:
            self._built.wait_for(
                lambda: self._index is not None and self._index.data_version >= data_version,
                timeout,
            )
            return self._index

    def full_index(self, reader: SQLiteReader, timeout: float = 60.0) -> TrialIndex:
        """The index for the reader's data version, waiting for it if it's being built.

        For analyses only the index answers (``tri_al.terms``). Without an index kept
        (``use_index=False``, in tests and benchmarks) it builds one for the data version.
        Raises ``IndexUnavailable`` if the index isn't ready in time, or the data changed.
        """
        version = reader.data_version()
        if not self.use_index:
            built: TrialIndex = self.cached(
                reader, ("index",), lambda: TrialIndex.build(reader.connection, version)
            )
            return built
        index = self.wait_for_index(version, timeout)
        if index is None or index.data_version != version:
            raise IndexUnavailable(version)
        return index

    def _build(self) -> None:
        try:
            started = datetime.now(UTC)
            index = self.build_index()
            seconds = (datetime.now(UTC) - started).total_seconds()
            log.info(
                "built the trial index for data version %d: %d trials, %.0f MB, %.1fs",
                index.data_version,
                index.trials,
                index.nbytes / 1e6,
                seconds,
            )
        except Exception:
            log.exception("building the trial index failed; filtered stats use SQLite")
        finally:
            with self._lock:
                self._building = None

    # --- requests ---------------------------------------------------------------------------

    def cached(self, reader: SQLiteReader, key: tuple[Any, ...], make: Callable[[], Any]) -> Any:
        """``make()``, kept in this worker's cache under ``key`` for the reader's data version.

        The first request after a new data version empties the cache.
        """
        version = reader.data_version()
        if version != self._cache_version:
            self.cache.clear()
            self._cache_version = version
        return self.cache.get_or_make((*key, version), make)

    def mask(self, reader: SQLiteReader, index: TrialIndex, filter: TrialFilter) -> Mask:
        def part(key: tuple[Any, ...], make: Callable[[], Mask]) -> Mask:
            result: Mask = self.cached(reader, ("part", *key), make)
            return result

        mask: Mask = self.cached(
            reader, ("mask", filter), lambda: index.mask(reader.connection, filter, part)
        )
        return mask

    def counts(self, reader: SQLiteReader, filter: TrialFilter) -> Counts:
        index = self.index_for(reader.data_version())
        if index is None:
            return SqlCounts(reader.connection, filter)
        return index.counts(reader.connection, self.mask(reader, index, filter))

    def context(self, reader: SQLiteReader) -> ChartContext:
        return ChartContext(reader.connection, lambda filter: self.counts(reader, filter))

    def chart(self, reader: SQLiteReader, chart_id: str, filter: TrialFilter) -> ChartData:
        chart = self.charts.get(chart_id)
        if chart is None:
            raise UnknownChart(chart_id)
        version = reader.data_version()
        if filter.is_empty and chart.precompute:
            stored = reader.stored_stats(chart_id)
            if stored is not None and stored.data_version == version:
                return ChartData(chart_id, version, False, stored.payload, "precomputed")
        made = False

        def compute() -> bytes:
            nonlocal made
            made = True
            return orjson.dumps(chart.query(self.context(reader), filter))

        rows: bytes = self.cached(reader, ("chart", chart_id, filter), compute)
        return ChartData(
            chart_id, version, not filter.is_empty, rows, "computed" if made else "cached"
        )

    def facet_counts(
        self, reader: SQLiteReader, fields: Sequence[str], filter: TrialFilter, limit: int
    ) -> dict[str, list[dict[str, Any]]]:
        """Each facet's options with counts under ``filter`` minus the facet's own field."""
        version = reader.data_version()
        result: dict[str, list[dict[str, Any]]] = {}
        for field in fields:
            facet = self.facets[field]
            others = filter.without(field)
            if others.is_empty and limit <= PRECOMPUTED_FACET_LIMIT:
                stored = reader.stored_stats(FACET_PREFIX + field)
                if stored is not None and stored.data_version == version:
                    result[field] = orjson.loads(stored.payload)[:limit]
                    continue
            result[field] = self.cached(
                reader,
                ("facet", field, others, limit),
                partial(_facet_rows, facet, self.context(reader), others, limit),
            )
        return result

    def count(self, reader: SQLiteReader, filter: TrialFilter) -> int:
        total: int = self.cached(
            reader, ("count", filter), lambda: self.counts(reader, filter).total()
        )
        return total

    def trial_page(
        self,
        reader: SQLiteReader,
        filter: TrialFilter,
        *,
        sort: Sort,
        after: Cursor | None,
        limit: int,
    ) -> TrialPage:
        """A page of the trial list, from the index when it's ready."""
        index = self.index_for(reader.data_version())
        if index is None:
            return reader.query_trials(filter, sort=sort, after=after, limit=limit)
        ids, next_cursor = index.page(self.mask(reader, index, filter), sort, after, limit)
        return TrialPage(reader.summaries(ids), next_cursor)
