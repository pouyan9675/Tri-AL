"""The SQLite storage backend (docs/design.md §5.2 and §6)."""

import json
import re
import sqlite3
import threading
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    Float,
    Integer,
    Select,
    Table,
    TextClause,
    and_,
    bindparam,
    column,
    delete,
    func,
    insert,
    literal,
    or_,
    select,
    table,
    text,
    tuple_,
    update,
)
from sqlalchemy.exc import DatabaseError
from sqlalchemy.sql.elements import KeyedColumnElement

from tri_al.filters import EVERY_TRIAL, TrialFilter
from tri_al.schema import (
    Arm,
    Intervention,
    Location,
    MeshTerm,
    Outcome,
    OutcomeKind,
    Sponsor,
    TrialRecord,
    without_repeats,
)
from tri_al.storage import docs
from tri_al.storage import tables as t
from tri_al.storage.base import (
    NEWEST_FIRST,
    Cursor,
    IdMatch,
    NameHit,
    NameKind,
    Refreshed,
    SearchHit,
    SearchResult,
    SnippetPart,
    Sort,
    StorageError,
    TrialChange,
    TrialPage,
    TrialSummary,
)
from tri_al.storage.core_migrations import COMPONENT, TRIALS_MIGRATIONS
from tri_al.storage.engine import (
    BEGIN,
    SqliteExtension,
    create_engine,
    raw_connection,
)
from tri_al.storage.filtering import (
    match_expression,
    matching_ids,
    trial_id_prefixes,
    trial_id_terms,
    where,
)
from tri_al.storage.migrations import (
    Migration,
    MigrationCallback,
    MigrationError,
    migrate,
    pending,
)

BULK_LOAD_KEY = "bulk_load_started"
"""``meta`` key set while a bulk load is running or after one that didn't finish."""

DATA_VERSION_KEY = "data_version"

SEARCH_CANDIDATES = 20_000
"""Matches a search ranks at most: the most recently registered ones (design §15).

Ranking costs about 2 µs a match, so a word in nearly every trial would take over a
second to rank; ranking only the newest 20,000 keeps the worst case near 50 ms, and a
search with fewer matches is ranked exactly.
"""

NAME_CANDIDATES = 5_000
"""Names a lookup sorts by length at most. A three-letter word like "the" is inside about a
fifth of all names, and sorting them all takes 75 ms; past this many, the shortest of the
first matches are good enough."""

SUMMARY_CONDITIONS = 10
"""Conditions a list row carries, at most."""

FTS_COLUMNS = (
    "title",
    "official_title",
    "conditions",
    "interventions",
    "other_names",
    "summary",
    "description",
    "eligibility",
    "outcomes",
)
"""What ``trials_fts`` indexes, in its column order."""

_FTS_INSERT = (
    f"INSERT INTO trials_fts (rowid, {', '.join(FTS_COLUMNS)}) "
    f"VALUES (:rowid, {', '.join(':' + name for name in FTS_COLUMNS)})"
)
_FTS_INTEGRITY_CHECKS = (
    "INSERT INTO trials_fts (trials_fts) VALUES ('integrity-check')",
    "INSERT INTO names_fts (names_fts) VALUES ('integrity-check')",
)
_WORD = re.compile(r"\w+")


def components(
    core: Sequence[Migration], plugins: Mapping[str, Sequence[Migration]] | None
) -> dict[str, Sequence[Migration]]:
    """The core's migrations first, then each plugin's."""
    plugins = plugins or {}
    if COMPONENT in plugins:
        raise MigrationError(f"plugin migrations can't use the core's component name {COMPONENT!r}")
    return {COMPONENT: core, **plugins}


@dataclass(frozen=True, slots=True)
class StoredStats:
    """A precomputed chart or facet from the ``stats`` table."""

    data_version: int
    payload: bytes  # JSON


class SQLiteStorage:
    """Trials in a SQLite file. Thread-safe: each call takes a pooled connection."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._decoder = docs.Decoder()
        self._snippets = _Snippets()

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        extensions: Sequence[SqliteExtension] = (),
        plugin_migrations: Mapping[str, Sequence[Migration]] | None = None,
        starting: MigrationCallback | None = None,
    ) -> Self:
        """Open (or create) ``trials.db`` at ``path`` and apply pending migrations.

        ``plugin_migrations`` maps each plugin's name to its ``trials`` migrations; they run
        after the core's, and after every extension has loaded. ``starting`` hears about
        each migration before it runs.
        """
        engine = create_engine(path, extensions=extensions)
        try:
            migrate(engine, components(TRIALS_MIGRATIONS, plugin_migrations), starting=starting)
        except BaseException:
            engine.dispose()
            raise
        return cls(engine)

    @classmethod
    def attach(
        cls,
        path: Path,
        *,
        extensions: Sequence[SqliteExtension] = (),
        plugin_migrations: Mapping[str, Sequence[Migration]] | None = None,
    ) -> Self:
        """Open an existing ``trials.db`` without migrating it, as API workers do.

        Raises StorageError if the file is missing or has migrations still to run.
        """
        if not path.exists():
            raise StorageError(f"there's no database at {path}; run `tri-al install` first")
        engine = create_engine(path, extensions=extensions)
        try:
            todo = pending(engine, components(TRIALS_MIGRATIONS, plugin_migrations))
            if todo:
                raise StorageError(
                    f"{path} needs migrations ({', '.join(todo)}); start `tri-al serve` or run "
                    "`tri-al update` once to apply them"
                )
        except BaseException:
            engine.dispose()
            raise
        return cls(engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    def close(self) -> None:
        self._snippets.close()
        self._engine.dispose()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # --- reads ------------------------------------------------------------------------------

    @contextmanager
    def read(self) -> Iterator["SQLiteReader"]:
        """Reads that all see the same commit, even while an update commits."""
        with self._engine.connect() as conn, conn.begin():
            yield SQLiteReader(conn, self._decoder, self._snippets)

    def get_trial(self, trial_id: int) -> TrialRecord | None:
        with self.read() as reader:
            return reader.get_trial(trial_id)

    def find_trial(self, source: str, source_id: str) -> TrialRecord | None:
        with self.read() as reader:
            return reader.find_trial(source, source_id)

    def content_hashes(
        self, source: str, source_ids: Iterable[str] | None = None
    ) -> dict[str, bytes | None]:
        with self.read() as reader:
            return reader.content_hashes(source, source_ids)

    def query_trials(
        self,
        filter: TrialFilter = EVERY_TRIAL,
        *,
        sort: Sort = NEWEST_FIRST,
        after: Cursor | None = None,
        limit: int = 100,
    ) -> TrialPage:
        with self.read() as reader:
            return reader.query_trials(filter, sort=sort, after=after, limit=limit)

    def count_trials(self, filter: TrialFilter = EVERY_TRIAL) -> int:
        with self.read() as reader:
            return reader.count_trials(filter)

    def search(
        self, text: str, *, filter: TrialFilter = EVERY_TRIAL, limit: int = 20
    ) -> SearchResult:
        with self.read() as reader:
            return reader.search(text, filter=filter, limit=limit)

    def lookup_names(
        self, text: str, *, kind: NameKind | None = None, limit: int = 20
    ) -> list[NameHit]:
        with self.read() as reader:
            return reader.lookup_names(text, kind=kind, limit=limit)

    def check(self, *, full_text: bool = True) -> None:
        """Raise StorageError unless the database is sound.

        Runs SQLite's ``quick_check``, makes sure no bulk load is unfinished and, with
        ``full_text``, checks both full-text indexes' structure.
        """
        with self._engine.connect() as conn:
            problems = conn.exec_driver_sql("PRAGMA quick_check").scalars().all()
            if problems != ["ok"]:
                raise StorageError(f"the database is damaged: {'; '.join(problems[:5])}")
            started = conn.execute(
                select(t.meta.c.value).where(t.meta.c.key == BULK_LOAD_KEY)
            ).scalar_one_or_none()
            if started is not None:
                raise StorageError(f"a bulk load started at {started} didn't finish")
            if full_text:
                try:
                    for statement in _FTS_INTEGRITY_CHECKS:
                        conn.execute(_sql(statement))
                except DatabaseError as exc:
                    raise StorageError(f"a full-text index is damaged: {exc}") from exc
                finally:
                    conn.rollback()

    # --- writes -----------------------------------------------------------------------------

    def upsert_batch(self, records: Sequence[TrialRecord]) -> list[int]:
        with self.transaction() as tx:
            return tx.upsert_batch(records)

    @contextmanager
    def transaction(self) -> Iterator["SQLiteTransaction"]:
        with self._engine.connect() as conn:
            conn.execution_options(**{BEGIN: "IMMEDIATE"})
            with conn.begin():
                started = conn.execute(
                    select(t.meta.c.value).where(t.meta.c.key == BULK_LOAD_KEY)
                ).scalar_one_or_none()
                if started is not None:
                    raise StorageError(
                        f"a bulk load into this database started at {started} and didn't "
                        "finish, so its indexes are incomplete; run the bulk load again"
                    )
                yield SQLiteTransaction(conn, self._decoder)

    @contextmanager
    def bulk_load(self) -> Iterator["SQLiteBulkLoader"]:
        with self._engine.connect() as conn:
            conn.execution_options(**{BEGIN: "IMMEDIATE"})
            raw = raw_connection(conn)
            raw.execute("PRAGMA synchronous = OFF")
            try:
                with conn.begin():
                    _start_bulk_load(conn)
                yield SQLiteBulkLoader(conn)
                with conn.begin():
                    _finish_bulk_load(conn)
                raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                raw.execute("PRAGMA synchronous = NORMAL")


class SQLiteReader:
    """Reads inside one read transaction, so they all see the same commit."""

    def __init__(self, conn: Connection, decoder: docs.Decoder, snippets: "_Snippets") -> None:
        self._conn = conn
        self._decoder = decoder
        self._snippets = snippets

    @property
    def connection(self) -> Connection:
        return self._conn

    def data_version(self) -> int:
        """Bumped by every install and every update that changes something."""
        return int(self.meta(DATA_VERSION_KEY) or 0)

    def meta(self, key: str) -> str | None:
        stmt = select(t.meta.c.value).where(t.meta.c.key == key)
        value: str | None = self._conn.execute(stmt).scalar_one_or_none()
        return value

    def get_trial(self, trial_id: int, *, raw: bool = True) -> TrialRecord | None:
        """The trial, with its raw document unless ``raw`` is False (that saves unpacking it)."""
        return _read_trial(self._conn, trial_id, self._decoder, raw=raw)

    def find_trial(self, source: str, source_id: str, *, raw: bool = True) -> TrialRecord | None:
        return _find_trial(self._conn, source, source_id, self._decoder, raw=raw)

    def find_ids(self, source_id: str) -> list[tuple[str, int]]:
        """``(source, id)`` of every trial called ``source_id``, one per registry at most.

        An id that matches none is tried in capitals, so ``nct04437511`` finds NCT04437511.
        """
        wanted = source_id.strip()
        for candidate in dict.fromkeys((wanted, wanted.upper())):
            stmt = (
                select(t.trials.c.source, t.trials.c.id)
                .where(t.trials.c.source_id == candidate)
                .order_by(t.trials.c.source)
            )
            if found := [(source, id_) for source, id_ in self._conn.execute(stmt)]:
                return found
        return []

    def content_hashes(
        self, source: str, source_ids: Iterable[str] | None = None
    ) -> dict[str, bytes | None]:
        return _content_hashes(self._conn, source, source_ids)

    def query_trials(
        self,
        filter: TrialFilter = EVERY_TRIAL,
        *,
        sort: Sort = NEWEST_FIRST,
        after: Cursor | None = None,
        limit: int = 100,
    ) -> TrialPage:
        keys, more = _page(self._conn, filter, sort, after, limit)
        last = keys[-1] if more and keys else None
        return TrialPage(
            self.summaries([trial_id for _, trial_id in keys]),
            None if last is None else (_cursor_value(last[0]), last[1]),
        )

    def summaries(self, ids: Sequence[int]) -> list[TrialSummary]:
        """List rows for ``ids``, in that order; ids that aren't stored are left out."""
        return _summaries(self._conn, ids)

    def texts(self, ids: Sequence[int]) -> dict[int, docs.TrialText]:
        """The long text of each of ``ids`` that's stored: summary, ..., why it stopped."""
        return _texts(self._conn, ids, self._decoder)

    def count_trials(self, filter: TrialFilter = EVERY_TRIAL) -> int:
        stmt = select(func.count()).select_from(t.trials).where(*where(filter))
        count: int = self._conn.execute(stmt).scalar_one()
        return count

    def search(
        self,
        text: str,
        *,
        filter: TrialFilter = EVERY_TRIAL,
        limit: int = 20,
        snippets: bool = True,
    ) -> SearchResult:
        scored, candidates = self.rank(text, filter=filter, limit=limit)
        hits = self.describe_hits(scored, text if snippets else None)
        return SearchResult(hits, candidates, candidates >= SEARCH_CANDIDATES)

    def rank(
        self, text: str, *, filter: TrialFilter = EVERY_TRIAL, limit: int = 20
    ) -> tuple[list[tuple[int, float]], int]:
        """``rank_matches`` in this read transaction."""
        return rank_matches(self._conn, text, filter=filter, limit=limit)

    def find_by_id(
        self, text: str, *, filter: TrialFilter = EVERY_TRIAL, limit: int = 20
    ) -> list[tuple[int, IdMatch]]:
        """``id_matches`` in this read transaction."""
        return id_matches(self._conn, text, filter=filter, limit=limit)

    def describe_hits(
        self,
        scored: Sequence[tuple[int, float | None]],
        text: str | None,
        id_matches: Mapping[int, IdMatch] | None = None,
    ) -> list[SearchHit]:
        """Hits for ``(id, score)`` pairs, in that order, with snippets matching ``text``.

        ``id_matches`` says which trials were found by their ID, and how.
        """
        id_matches = id_matches or {}
        ids = [trial_id for trial_id, _ in scored]
        if not ids:
            return []
        c = t.trials.c
        rows = {
            row.id: row
            for row in self._conn.execute(
                select(c.id, c.source, c.source_id, c.title, c.status, c.phase).where(
                    _in(c.id, ids)
                )
            )
        }
        snippets = {} if text is None else self._snippets.build(self._snippet_text(ids), text)
        return [
            SearchHit(
                trial_id,
                rows[trial_id].source,
                rows[trial_id].source_id,
                rows[trial_id].title,
                rows[trial_id].status,
                rows[trial_id].phase,
                score,
                snippets.get(trial_id, ()),
                id_matches.get(trial_id),
            )
            for trial_id, score in scored
            if trial_id in rows
        ]

    def names(self, ids: Sequence[int]) -> dict[int, dict[str, list[str]]]:
        """Each trial's condition and intervention names and the interventions' other names,
        under ``conditions``, ``interventions`` and ``other_names``: what the full-text index
        reads besides the text."""
        joined: dict[int, dict[str, list[str]]] = {trial_id: {} for trial_id in ids}
        for trial_id, kind, name in self._conn.execute(
            _sql(
                "SELECT tc.trial_id, 'conditions', c.name FROM trial_conditions AS tc "
                "JOIN conditions AS c ON c.id = tc.condition_id WHERE tc.trial_id IN "
                + _JSON_IDS
                + " UNION ALL SELECT ti.trial_id, 'interventions', i.name "
                "FROM trial_interventions AS ti JOIN interventions AS i "
                "ON i.id = ti.intervention_id WHERE ti.trial_id IN "
                + _JSON_IDS
                + " UNION ALL SELECT trial_id, 'other_names', alias FROM intervention_aliases "
                "WHERE trial_id IN " + _JSON_IDS
            ),
            _ids(ids),
        ):
            joined[trial_id].setdefault(kind, []).append(name)
        return joined

    def _snippet_text(self, ids: Sequence[int]) -> dict[int, list[str | None]]:
        """The searchable text of each trial apart from its titles, in _Snippets.COLUMNS order."""
        joined = self.names(ids)
        texts = _texts(self._conn, ids, self._decoder)
        result: dict[int, list[str | None]] = {}
        for trial_id in ids:
            text_ = texts.get(trial_id, docs.TrialText())
            names = joined[trial_id]
            result[trial_id] = [
                text_.brief_summary,
                text_.description,
                text_.eligibility_criteria,
                _outcome_text(text_.outcomes),
                " ".join(names.get("conditions", ())) or None,
                " ".join(names.get("interventions", ())) or None,
                " ".join(names.get("other_names", ())) or None,
            ]
        return result

    def lookup_names(
        self, text: str, *, kind: NameKind | None = None, limit: int = 20
    ) -> list[NameHit]:
        words = [word for word in _WORD.findall(text) if len(word) >= 3]
        params: dict[str, object] = {"kind": kind, "limit": limit}
        if words:
            # The trigram tokenizer matches each quoted word anywhere in a name.
            condition = "names_fts MATCH :match"
            params["match"] = " ".join(f'"{word}"' for word in words)
        elif text.strip():
            condition = r"name LIKE :prefix ESCAPE '\'"
            params["prefix"] = re.sub(r"([\\%_])", r"\\\1", text.strip()) + "%"
        else:
            return []
        stmt = _sql(
            f"""
            SELECT kind, ref, name FROM (
                SELECT kind, ref, name FROM names_fts
                WHERE {condition} AND (:kind IS NULL OR kind = :kind)
                LIMIT :candidates
            )
            ORDER BY length(name), name LIMIT :limit
            """
        )
        params["candidates"] = NAME_CANDIDATES
        return [NameHit(*row) for row in self._conn.execute(stmt, params)]

    def changes(self, trial_id: int) -> list[TrialChange]:
        """What updates changed in the trial, newest first."""
        c, r = t.trial_changes.c, t.runs.c
        stmt = (
            select(c.run_id, r.finished_at, c.field, c.old, c.new)
            .join(t.runs, r.id == c.run_id)
            .where(c.trial_id == trial_id)
            .order_by(c.run_id.desc(), c.id)
        )
        return [
            TrialChange(
                run_id,
                finished_at,
                field,
                None if old is None else json.loads(old),
                None if new is None else json.loads(new),
            )
            for run_id, finished_at, field, old, new in self._conn.execute(stmt)
        ]

    def stored_stats(self, chart_id: str) -> StoredStats | None:
        """A chart or facet the pipeline precomputed, whatever data version it was made for."""
        row = self._conn.execute(
            select(t.stats.c.data_version, t.stats.c.payload).where(t.stats.c.chart_id == chart_id)
        ).one_or_none()
        return None if row is None else StoredStats(row.data_version, bytes(row.payload))


class SQLiteTransaction:
    def __init__(self, conn: Connection, decoder: docs.Decoder) -> None:
        self._conn = conn
        self._decoder = decoder
        self._writer = _Writer(conn, bulk=False)

    @property
    def connection(self) -> Connection:
        return self._conn

    def get_trial(self, trial_id: int) -> TrialRecord | None:
        return _read_trial(self._conn, trial_id, self._decoder)

    def find_trial(self, source: str, source_id: str) -> TrialRecord | None:
        return _find_trial(self._conn, source, source_id, self._decoder)

    def content_hashes(
        self, source: str, source_ids: Iterable[str] | None = None
    ) -> dict[str, bytes | None]:
        return _content_hashes(self._conn, source, source_ids)

    def upsert_batch(self, records: Sequence[TrialRecord]) -> list[int]:
        return self._writer.upsert(records)

    def refresh(
        self,
        trial_ids: Sequence[int],
        derive: Callable[[TrialRecord], TrialRecord | None],
    ) -> Refreshed:
        result = Refreshed()
        rewrite: list[tuple[int, TrialRecord]] = []
        replace_: list[TrialRecord] = []
        for trial_id in trial_ids:
            stored = _read_trial(self._conn, trial_id, self._decoder)
            derived = None if stored is None else derive(stored)
            if stored is None or derived is None:
                result.skipped.append(trial_id)
                continue
            if (derived.source, derived.source_id) != (stored.source, stored.source_id):
                raise ValueError(
                    f"derive made {derived.source}/{derived.source_id} of trial {trial_id}, "
                    f"which is {stored.source}/{stored.source_id}"
                )
            record = without_repeats(derived)
            if record.raw is None:
                record.raw = stored.raw
            if _comparable(record) == _comparable(stored):
                result.unchanged.append(trial_id)
            elif record.raw == stored.raw and _indexed(record) == _indexed(stored):
                rewrite.append((trial_id, record))
                result.rewritten.append(trial_id)
            else:
                replace_.append(record)
                result.replaced.append(trial_id)
        self._writer.rewrite(rewrite)
        self._writer.upsert(replace_)
        return result


def _comparable(record: TrialRecord) -> TrialRecord:
    """``record`` without what storage sets, to compare a stored record with a new one."""
    return replace(record, id=None, ingested_at=None)


def _indexed(record: TrialRecord) -> tuple[object, ...]:
    """What a trial's links, full-text row and vector are made of; the rest is columns and text.

    ``refresh`` rewrites a trial in place only when this hasn't changed. Embeddings read
    the title, conditions, interventions and summary, which the full-text row covers too.
    """
    return (
        _fts_row(record, 0),
        record.conditions,
        record.mesh_terms,
        [(i.name, i.type, i.other_names) for i in record.interventions],
        record.sponsors,
        record.countries,
        record.locations,
    )


class SQLiteBulkLoader:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._writer: _Writer | None = None

    def content_hashes(
        self, source: str, source_ids: Iterable[str] | None = None
    ) -> dict[str, bytes | None]:
        with self._conn.begin():
            return _content_hashes(self._conn, source, source_ids)

    def upsert_batch(self, records: Sequence[TrialRecord]) -> list[int]:
        try:
            with self._conn.begin():
                if self._writer is None:
                    self._writer = _Writer(self._conn, bulk=True)
                return self._writer.upsert(records)
        except BaseException:
            # The rollback undid rows the writer's caches may hold; start the caches again.
            self._writer = None
            raise


# --- writing ------------------------------------------------------------------------------


class _Names:
    """Get-or-create ids for one entity table, keyed by its unique text column."""

    def __init__(self, table: Table, key: str, kind: NameKind) -> None:
        self.table = table
        self.key = key
        self.kind = kind
        self.ids: dict[str, int] = {}
        self.complete = False  # ids holds every row, so misses are new

    def preload(self, conn: Connection) -> None:
        stmt = select(self.table.c[self.key], self.table.c.id)
        # Not dict(result): a Result has keys(), so dict() would take it for a mapping.
        self.ids = dict(conn.execute(stmt).all())
        self.complete = True

    def resolve(self, conn: Connection, keys: Collection[str]) -> list[dict[str, Any]]:
        """Make sure every key has a row; return the rows created."""
        missing = {key for key in keys if key not in self.ids}
        if missing and not self.complete:
            column_ = self.table.c[self.key]
            stmt = select(column_, self.table.c.id).where(_in(column_, missing))
            self.ids.update(conn.execute(stmt).all())
            missing -= self.ids.keys()
        if not missing:
            return []
        start = _next_id(conn, self.table)
        created = {key: start + i for i, key in enumerate(sorted(missing))}
        rows = [{"id": id_, self.key: key} for key, id_ in created.items()]
        conn.execute(insert(self.table), rows)
        self.ids.update(created)
        return rows


class _MeshTerms:
    """Get-or-create ids for MeSH codes. A code keeps one term: the latest seen."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[int, str]] = {}
        self.complete = False

    def preload(self, conn: Connection) -> None:
        stmt = select(t.mesh_terms.c.code, t.mesh_terms.c.id, t.mesh_terms.c.term)
        self.rows = {code: (id_, term) for code, id_, term in conn.execute(stmt)}
        self.complete = True

    def resolve(self, conn: Connection, terms: Mapping[str, str]) -> None:
        missing = terms.keys() - self.rows.keys()
        if missing and not self.complete:
            stmt = select(t.mesh_terms.c.code, t.mesh_terms.c.id, t.mesh_terms.c.term).where(
                _in(t.mesh_terms.c.code, missing)
            )
            self.rows.update((code, (id_, term)) for code, id_, term in conn.execute(stmt))
            missing -= self.rows.keys()
        renamed = {
            code: (self.rows[code][0], term)
            for code, term in terms.items()
            if code in self.rows and self.rows[code][1] != term
        }
        if renamed:
            conn.execute(
                update(t.mesh_terms).where(t.mesh_terms.c.id == bindparam("b_id")),
                [{"b_id": id_, "term": term} for id_, term in renamed.values()],
            )
            self.rows.update(renamed)
        if missing:
            start = _next_id(conn, t.mesh_terms)
            created = {code: (start + i, terms[code]) for i, code in enumerate(sorted(missing))}
            conn.execute(
                insert(t.mesh_terms),
                [{"id": id_, "code": code, "term": term} for code, (id_, term) in created.items()],
            )
            self.rows.update(created)

    def id(self, code: str) -> int:
        return self.rows[code][0]


class _Codec:
    """Compresses one kind of blob (``docs.DOC`` or ``docs.TEXT``), training its dictionary."""

    def __init__(self, conn: Connection, kind: str) -> None:
        self._kind = kind
        latest = conn.execute(
            select(t.doc_dicts.c.id, t.doc_dicts.c.dict)
            .where(t.doc_dicts.c.kind == kind)
            .order_by(t.doc_dicts.c.id.desc())
            .limit(1)
        ).one_or_none()
        self._encoder = docs.Encoder() if latest is None else docs.Encoder(*latest)
        self._trained = latest is not None

    def rows(
        self, conn: Connection, blobs: Sequence[tuple[int, bytes]], column_: str
    ) -> list[dict[str, Any]]:
        if not self._trained and (content := docs.train([blob for _, blob in blobs])):
            dict_id = _next_id(conn, t.doc_dicts)
            conn.execute(
                insert(t.doc_dicts),
                {
                    "id": dict_id,
                    "dict": content,
                    "created_at": datetime.now(UTC),
                    "kind": self._kind,
                },
            )
            self._encoder = docs.Encoder(dict_id, content)
            self._trained = True
        encoder = self._encoder
        return [
            {"trial_id": trial_id, column_: encoder.encode(blob), "dict_id": encoder.dict_id}
            for trial_id, blob in blobs
        ]


class _Writer:
    """Upserts batches of trials on one connection, inside the caller's transaction.

    The full-text index is contentless, so every write feeds it the trials' text. ``bulk``
    leaves ``names_fts`` to ``_finish_bulk_load``, which refills it in one pass, and keeps
    every entity id in memory across batches.
    """

    def __init__(self, conn: Connection, *, bulk: bool) -> None:
        self._conn = conn
        self._bulk = bulk
        self._conditions = _Names(t.conditions, "name", "condition")
        self._interventions = _Names(t.interventions, "name", "intervention")
        self._sponsors = _Names(t.sponsors, "name", "sponsor")
        self._mesh = _MeshTerms()
        self._docs = _Codec(conn, docs.DOC)
        self._texts = _Codec(conn, docs.TEXT)
        self._countries = frozenset(conn.execute(select(t.countries.c.code)).scalars())
        if bulk:
            for names in (self._conditions, self._interventions, self._sponsors, self._mesh):
                names.preload(conn)

    def upsert(self, records: Sequence[TrialRecord]) -> list[int]:
        if not records:
            return []
        records = [without_repeats(record) for record in records]
        self._check(records)
        ids, existing = self._assign_ids(records)
        conn = self._conn
        if existing:
            # Contentless with contentless_delete: a trial's row goes by rowid alone.
            conn.execute(_sql("DELETE FROM trials_fts WHERE rowid IN " + _JSON_IDS), _ids(existing))
            for table_ in t.LINK_TABLES:
                conn.execute(delete(table_).where(_in(table_.c.trial_id, existing)))

        new_names = self._resolve_names(records)
        now = datetime.now(UTC)
        rows = [self._trial_row(record, id_, now) for record, id_ in zip(records, ids, strict=True)]
        new_rows = [row for row in rows if row["id"] not in existing]
        if new_rows:
            conn.execute(insert(t.trials), new_rows)
        changed = [
            {"b_id": row["id"]} | {key: value for key, value in row.items() if key != "id"}
            for row in rows
            if row["id"] in existing
        ]
        if changed:
            conn.execute(update(t.trials).where(t.trials.c.id == bindparam("b_id")), changed)
        self._insert_children(records, ids)
        conn.execute(
            _sql(_FTS_INSERT),
            [_fts_row(record, id_) for record, id_ in zip(records, ids, strict=True)],
        )
        if not self._bulk and new_names:
            conn.execute(_sql("INSERT INTO names_fts VALUES (:name, :kind, :ref)"), new_names)
        return ids

    def rewrite(self, trials: Sequence[tuple[int, TrialRecord]]) -> None:
        """Rewrite stored trials' columns and text, leaving the rest as it is.

        Only for records whose links and indexed text are what's stored (``_indexed``), as
        ``SQLiteTransaction.refresh`` checks: their full-text rows, raw documents, vectors
        and ``ingested_at`` stay.
        """
        if not trials:
            return
        conn = self._conn
        ids = [trial_id for trial_id, _ in trials]
        conn.execute(
            update(t.trials).where(t.trials.c.id == bindparam("b_id")),
            [{"b_id": trial_id} | _trial_columns(record) for trial_id, record in trials],
        )
        conn.execute(delete(t.trial_text).where(_in(t.trial_text.c.trial_id, ids)))
        conn.execute(
            insert(t.trial_text),
            self._texts.rows(
                conn,
                [(trial_id, _trial_text(record).pack()) for trial_id, record in trials],
                "text",
            ),
        )

    def _check(self, records: Sequence[TrialRecord]) -> None:
        keys = Counter((record.source, record.source_id) for record in records)
        if repeated := sorted(key for key, count in keys.items() if count > 1):
            raise ValueError(f"the batch has more than one record for {repeated}")
        codes = {code for record in records for code in record.countries} | {
            location.country_code
            for record in records
            for location in record.locations
            if location.country_code is not None
        }
        if unknown := sorted(codes - self._countries):
            raise ValueError(
                f"unknown country codes {unknown}; use ISO 3166-1 alpha-2 codes, such as 'US'"
            )

    def _assign_ids(self, records: Sequence[TrialRecord]) -> tuple[list[int], set[int]]:
        by_source: dict[str, set[str]] = {}
        for record in records:
            by_source.setdefault(record.source, set()).add(record.source_id)
        found: dict[tuple[str, str], int] = {}
        for source, source_ids in by_source.items():
            stmt = select(t.trials.c.source_id, t.trials.c.id).where(
                t.trials.c.source == source, _in(t.trials.c.source_id, source_ids)
            )
            found.update(((source, source_id), id_) for source_id, id_ in self._conn.execute(stmt))
        next_id = _next_id(self._conn, t.trials)
        ids = []
        for record in records:
            id_ = found.get((record.source, record.source_id))
            if id_ is None:
                id_, next_id = next_id, next_id + 1
            ids.append(id_)
        return ids, set(found.values())

    def _resolve_names(self, records: Sequence[TrialRecord]) -> list[dict[str, Any]]:
        """Create the batch's new conditions, interventions, sponsors and MeSH terms.

        Returns names_fts rows for the names created.
        """
        new_names: list[dict[str, Any]] = []
        for names, keys in (
            (self._conditions, {name for record in records for name in record.conditions}),
            (self._interventions, {i.name for record in records for i in record.interventions}),
            (self._sponsors, {s.name for record in records for s in record.sponsors}),
        ):
            created = names.resolve(self._conn, keys)
            new_names += [
                {"name": row["name"], "kind": names.kind, "ref": row["id"]} for row in created
            ]
        self._mesh.resolve(
            self._conn, {term.code: term.term for record in records for term in record.mesh_terms}
        )
        return new_names

    def _trial_row(self, record: TrialRecord, trial_id: int, now: datetime) -> dict[str, Any]:
        lead = record.lead_sponsor
        return {
            "id": trial_id,
            "source": record.source,
            "source_id": record.source_id,
            **_trial_columns(record),
            "lead_sponsor_id": None if lead is None else self._sponsors.ids[lead.name],
            "ingested_at": now,
        }

    def _insert_children(self, records: Sequence[TrialRecord], ids: Sequence[int]) -> None:
        rows: dict[Table, list[dict[str, Any]]] = {table_: [] for table_ in t.LINK_TABLES}
        raws: list[tuple[int, bytes]] = []
        texts: list[tuple[int, bytes]] = []
        for record, trial_id in zip(records, ids, strict=True):
            texts.append((trial_id, _trial_text(record).pack()))
            if record.raw is not None:
                raws.append((trial_id, record.raw))
            rows[t.trial_conditions] += (
                {
                    "trial_id": trial_id,
                    "condition_id": self._conditions.ids[name],
                    "position": position,
                }
                for position, name in enumerate(record.conditions)
            )
            rows[t.trial_mesh] += (
                {
                    "trial_id": trial_id,
                    "mesh_term_id": self._mesh.id(term.code),
                    "kind": term.kind,
                    "ancestor": term.ancestor,
                    "position": position,
                }
                for position, term in enumerate(record.mesh_terms)
            )
            for position, intervention in enumerate(record.interventions):
                intervention_id = self._interventions.ids[intervention.name]
                rows[t.trial_interventions].append(
                    {
                        "trial_id": trial_id,
                        "intervention_id": intervention_id,
                        "type": intervention.type,
                        "position": position,
                    }
                )
                rows[t.intervention_aliases] += (
                    {
                        "trial_id": trial_id,
                        "intervention_id": intervention_id,
                        "alias": alias,
                        "position": alias_position,
                    }
                    for alias_position, alias in enumerate(intervention.other_names)
                )
            rows[t.trial_sponsors] += (
                {
                    "trial_id": trial_id,
                    "sponsor_id": self._sponsors.ids[sponsor.name],
                    "role": sponsor.role,
                    "sponsor_class": sponsor.sponsor_class,
                    "position": position,
                }
                for position, sponsor in enumerate(record.sponsors)
            )
            rows[t.trial_countries] += (
                {"trial_id": trial_id, "country_code": code, "position": position}
                for position, code in enumerate(record.countries)
            )
            rows[t.locations] += (
                {
                    "trial_id": trial_id,
                    "position": position,
                    "facility": location.facility,
                    "city": location.city,
                    "state": location.state,
                    "country_code": location.country_code,
                    "status": location.status,
                    "lat": location.lat,
                    "lon": location.lon,
                }
                for position, location in enumerate(record.locations)
            )
        rows[t.trial_text] = self._texts.rows(self._conn, texts, "text")
        rows[t.trial_docs] = self._docs.rows(self._conn, raws, "doc")
        for table_, table_rows in rows.items():
            if table_rows:
                self._conn.execute(insert(table_), table_rows)


def _trial_columns(record: TrialRecord) -> dict[str, Any]:
    """The trial's ``trials`` columns but its identity, lead sponsor id and ``ingested_at``."""
    lead = record.lead_sponsor
    return {
        "title": record.title,
        "official_title": record.official_title,
        "status": record.status,
        "phase": record.phase,
        "study_type": record.study_type,
        "primary_purpose": record.primary_purpose,
        "start_date": record.start_date,
        "primary_completion_date": record.primary_completion_date,
        "completion_date": record.completion_date,
        "first_posted": record.first_posted,
        "last_update": record.last_update,
        "enrollment": record.enrollment,
        "enrollment_type": record.enrollment_type,
        "arms_count": record.arms_count,
        "has_results": record.has_results,
        "lead_sponsor_class": None if lead is None else lead.sponsor_class,
        "min_age_days": record.min_age_days,
        "max_age_days": record.max_age_days,
        "sex": record.sex,
        "healthy_volunteers": record.healthy_volunteers,
        "location_scope": record.location_scope,
        "num_sites": record.num_sites,
        "content_hash": record.content_hash,
        "allocation": record.allocation,
        "intervention_model": record.intervention_model,
        "observational_model": record.observational_model,
        "time_perspective": record.time_perspective,
        "masking": record.masking,
        "start_date_type": record.start_date_type,
        "primary_completion_date_type": record.primary_completion_date_type,
        "completion_date_type": record.completion_date_type,
        "results_first_posted": record.results_first_posted,
        "status_verified": record.status_verified,
        "last_known_status": record.last_known_status,
    }


def _trial_text(record: TrialRecord) -> docs.TrialText:
    return docs.TrialText(
        record.brief_summary,
        record.description,
        record.eligibility_criteria,
        tuple(
            (outcome.kind, outcome.measure, outcome.description, outcome.time_frame)
            for outcome in record.outcomes
        ),
        tuple(record.keywords),
        tuple((arm.label, arm.type, arm.description, arm.interventions) for arm in record.arms),
        tuple((i.name, i.description) for i in record.interventions if i.description is not None),
        tuple(record.masked_roles),
        record.why_stopped,
    )


def _outcome_text(outcomes: Iterable[docs.PackedOutcome]) -> str | None:
    """Outcome measures and descriptions as one text, the way ``trials_fts`` indexes them."""
    return (
        " ".join(
            " ".join(part for part in (measure, description) if part)
            for _, measure, description, _ in outcomes
        )
        or None
    )


def _fts_row(record: TrialRecord, trial_id: int) -> dict[str, Any]:
    """What ``trials_fts`` indexes for a trial (after ``without_repeats``)."""
    return {
        "rowid": trial_id,
        "title": record.title,
        "official_title": record.official_title,
        "conditions": " ".join(record.conditions) or None,
        "interventions": " ".join(i.name for i in record.interventions) or None,
        "other_names": " ".join(a for i in record.interventions for a in i.other_names) or None,
        "summary": record.brief_summary,
        "description": record.description,
        "eligibility": record.eligibility_criteria,
        "outcomes": _outcome_text(
            (o.kind, o.measure, o.description, o.time_frame) for o in record.outcomes
        ),
    }


def _start_bulk_load(conn: Connection) -> None:
    conn.execute(
        _sql(
            "INSERT INTO meta (key, value) VALUES (:key, :value) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value"
        ),
        {"key": BULK_LOAD_KEY, "value": datetime.now(UTC).isoformat()},
    )
    for index in t.DEFERRED_INDEXES:
        index.drop(conn, checkfirst=True)
    conn.execute(_sql("DELETE FROM names_fts"))


def _finish_bulk_load(conn: Connection) -> None:
    for index in t.DEFERRED_INDEXES:
        index.create(conn, checkfirst=True)
    conn.execute(_sql("INSERT INTO trials_fts (trials_fts) VALUES ('optimize')"))
    conn.execute(
        _sql(
            "INSERT INTO names_fts (name, kind, ref) "
            "SELECT name, 'condition', id FROM conditions "
            "UNION ALL SELECT name, 'intervention', id FROM interventions "
            "UNION ALL SELECT name, 'sponsor', id FROM sponsors"
        )
    )
    conn.execute(_sql("INSERT INTO names_fts (names_fts) VALUES ('optimize')"))
    conn.execute(delete(t.meta).where(t.meta.c.key == BULK_LOAD_KEY))
    conn.execute(_sql("ANALYZE"))
    conn.execute(_sql("PRAGMA optimize"))


# --- reading ------------------------------------------------------------------------------


def _content_hashes(
    conn: Connection, source: str, source_ids: Iterable[str] | None
) -> dict[str, bytes | None]:
    stmt = select(t.trials.c.source_id, t.trials.c.content_hash).where(t.trials.c.source == source)
    if source_ids is not None:
        stmt = stmt.where(_in(t.trials.c.source_id, source_ids))
    return dict(conn.execute(stmt).all())


def _find_trial(
    conn: Connection, source: str, source_id: str, decoder: docs.Decoder, *, raw: bool = True
) -> TrialRecord | None:
    trial_id = conn.execute(
        select(t.trials.c.id).where(t.trials.c.source == source, t.trials.c.source_id == source_id)
    ).scalar_one_or_none()
    return None if trial_id is None else _read_trial(conn, trial_id, decoder, raw=raw)


def _dict_loader(conn: Connection) -> Any:
    def load(dict_id: int) -> bytes:
        stmt = select(t.doc_dicts.c.dict).where(t.doc_dicts.c.id == dict_id)
        return bytes(conn.execute(stmt).scalar_one())

    return load


def _texts(
    conn: Connection, ids: Sequence[int], decoder: docs.Decoder
) -> dict[int, docs.TrialText]:
    load = _dict_loader(conn)
    stmt = select(t.trial_text.c.trial_id, t.trial_text.c.text, t.trial_text.c.dict_id).where(
        _in(t.trial_text.c.trial_id, ids)
    )
    return {
        trial_id: docs.TrialText.unpack(decoder.decode(blob, dict_id, load))
        for trial_id, blob, dict_id in conn.execute(stmt)
    }


def _read_trial(
    conn: Connection, trial_id: int, decoder: docs.Decoder, *, raw: bool = True
) -> TrialRecord | None:
    trial = conn.execute(select(t.trials).where(t.trials.c.id == trial_id)).one_or_none()
    if trial is None:
        return None

    def rows(stmt: Select[Any], table_: Table) -> Iterator[Any]:
        return iter(
            conn.execute(stmt.where(table_.c.trial_id == trial_id).order_by(table_.c.position))
        )

    text_ = _texts(conn, [trial_id], decoder).get(trial_id, docs.TrialText())
    doc = None
    if raw:
        doc = conn.execute(
            select(t.trial_docs.c.doc, t.trial_docs.c.dict_id).where(
                t.trial_docs.c.trial_id == trial_id
            )
        ).one_or_none()

    described = dict(text_.intervention_descriptions)
    aliases: dict[int, list[str]] = {}
    for intervention_id, alias in rows(
        select(t.intervention_aliases.c.intervention_id, t.intervention_aliases.c.alias),
        t.intervention_aliases,
    ):
        aliases.setdefault(intervention_id, []).append(alias)

    return TrialRecord(
        id=trial.id,
        source=trial.source,
        source_id=trial.source_id,
        title=trial.title,
        official_title=trial.official_title,
        status=trial.status,
        phase=trial.phase,
        study_type=trial.study_type,
        primary_purpose=trial.primary_purpose,
        allocation=trial.allocation,
        intervention_model=trial.intervention_model,
        observational_model=trial.observational_model,
        time_perspective=trial.time_perspective,
        masking=trial.masking,
        masked_roles=list(text_.masked_roles),
        start_date=trial.start_date,
        primary_completion_date=trial.primary_completion_date,
        completion_date=trial.completion_date,
        first_posted=trial.first_posted,
        last_update=trial.last_update,
        start_date_type=trial.start_date_type,
        primary_completion_date_type=trial.primary_completion_date_type,
        completion_date_type=trial.completion_date_type,
        results_first_posted=trial.results_first_posted,
        status_verified=trial.status_verified,
        last_known_status=trial.last_known_status,
        why_stopped=text_.why_stopped,
        enrollment=trial.enrollment,
        enrollment_type=trial.enrollment_type,
        arms_count=trial.arms_count,
        has_results=trial.has_results,
        min_age_days=trial.min_age_days,
        max_age_days=trial.max_age_days,
        sex=trial.sex,
        healthy_volunteers=trial.healthy_volunteers,
        brief_summary=text_.brief_summary,
        description=text_.description,
        eligibility_criteria=text_.eligibility_criteria,
        outcomes=[
            Outcome(cast(OutcomeKind, kind), measure, description, time_frame)
            for kind, measure, description, time_frame in text_.outcomes
        ],
        conditions=[
            row.name
            for row in rows(
                select(t.conditions.c.name).join(t.trial_conditions), t.trial_conditions
            )
        ],
        keywords=list(text_.keywords),
        mesh_terms=[
            MeshTerm(row.code, row.term, row.kind, row.ancestor)
            for row in rows(
                select(
                    t.mesh_terms.c.code,
                    t.mesh_terms.c.term,
                    t.trial_mesh.c.kind,
                    t.trial_mesh.c.ancestor,
                ).join(t.trial_mesh),
                t.trial_mesh,
            )
        ],
        interventions=[
            Intervention(
                row.name, row.type, tuple(aliases.get(row.id, ())), described.get(row.name)
            )
            for row in rows(
                select(
                    t.interventions.c.id, t.interventions.c.name, t.trial_interventions.c.type
                ).join(t.trial_interventions),
                t.trial_interventions,
            )
        ],
        arms=[
            Arm(label, type_, description, names) for label, type_, description, names in text_.arms
        ],
        sponsors=[
            Sponsor(row.name, row.role, row.sponsor_class)
            for row in rows(
                select(
                    t.sponsors.c.name, t.trial_sponsors.c.role, t.trial_sponsors.c.sponsor_class
                ).join(t.trial_sponsors),
                t.trial_sponsors,
            )
        ],
        countries=[
            row.country_code
            for row in rows(select(t.trial_countries.c.country_code), t.trial_countries)
        ],
        locations=[
            Location(
                row.facility, row.city, row.state, row.country_code, row.status, row.lat, row.lon
            )
            for row in rows(select(t.locations), t.locations)
        ],
        raw=None if doc is None else decoder.decode(doc.doc, doc.dict_id, _dict_loader(conn)),
        content_hash=trial.content_hash,
        ingested_at=trial.ingested_at,
    )


def _summaries(conn: Connection, ids: Sequence[int]) -> list[TrialSummary]:
    if not ids:
        return []
    c = t.trials.c
    stmt = (
        select(
            c.id,
            c.source,
            c.source_id,
            c.title,
            c.status,
            c.phase,
            c.study_type,
            c.start_date,
            c.completion_date,
            c.last_update,
            c.enrollment,
            c.has_results,
            c.num_sites,
            t.sponsors.c.name,
        )
        .outerjoin(t.sponsors, t.sponsors.c.id == c.lead_sponsor_id)
        .where(_in(c.id, ids))
    )
    rows = {row.id: row for row in conn.execute(stmt)}
    conditions: dict[int, list[str]] = {}
    for trial_id, name in conn.execute(
        select(t.trial_conditions.c.trial_id, t.conditions.c.name)
        .join(t.conditions)
        .where(_in(t.trial_conditions.c.trial_id, ids))
        .order_by(t.trial_conditions.c.trial_id, t.trial_conditions.c.position)
    ):
        conditions.setdefault(trial_id, []).append(name)
    summaries = []
    for trial_id in ids:
        row = rows.get(trial_id)
        if row is not None:
            summaries.append(
                TrialSummary(
                    id=row.id,
                    source=row.source,
                    source_id=row.source_id,
                    title=row.title,
                    status=row.status,
                    phase=row.phase,
                    study_type=row.study_type,
                    start_date=row.start_date,
                    completion_date=row.completion_date,
                    last_update=row.last_update,
                    enrollment=row.enrollment,
                    has_results=row.has_results,
                    num_sites=row.num_sites,
                    lead_sponsor=row.name,
                    conditions=tuple(conditions.get(trial_id, ())[:SUMMARY_CONDITIONS]),
                )
            )
    return summaries


def _page(
    conn: Connection, filter: TrialFilter, sort: Sort, after: Cursor | None, limit: int
) -> tuple[list[tuple[Any, int]], bool]:
    """``(sort value, id)`` of up to ``limit`` trials after ``after``, and whether there are more.

    SQLite orders NULL before every value, so a descending list has the trials without a
    value at the end. Each part is its own query, so both can walk the sort column's index.
    """
    clauses = where(filter)
    id_ = t.trials.c.id
    desc = sort.descending
    if sort.key == "id":
        stmt = select(id_, id_).where(*clauses)
        if after is not None:
            stmt = stmt.where(id_ < after[1] if desc else id_ > after[1])
        rows = conn.execute(stmt.order_by(id_.desc() if desc else id_).limit(limit + 1)).all()
        return [(value, trial_id) for value, trial_id in rows[:limit]], len(rows) > limit
    col = t.trials.c[sort.key]
    parts = ["values", "nulls"] if desc else ["nulls", "values"]
    if after is not None:
        parts = parts[parts.index("nulls" if after[0] is None else "values") :]
    found: list[tuple[Any, int]] = []
    order: tuple[Any, ...]
    for part in parts:
        if part == "values":
            stmt = select(col, id_).where(*clauses, col.is_not(None))
            if after is not None and after[0] is not None:
                bound = tuple_(literal(_bind_value(sort, after[0]), col.type), literal(after[1]))
                stmt = stmt.where(tuple_(col, id_) < bound if desc else tuple_(col, id_) > bound)
            order = (col.desc(), id_.desc()) if desc else (col, id_)
        else:
            stmt = select(col, id_).where(*clauses, col.is_(None))
            if after is not None and after[0] is None:
                stmt = stmt.where(id_ < after[1] if desc else id_ > after[1])
            order = (id_.desc(),) if desc else (id_,)
        result = conn.execute(stmt.order_by(*order).limit(limit + 1 - len(found)))
        found += [(value, trial_id) for value, trial_id in result]
        if len(found) > limit:
            break
    return found[:limit], len(found) > limit


def _bind_value(sort: Sort, value: Any) -> Any:
    if sort.key == "enrollment":
        return int(value)
    return date.fromisoformat(value) if isinstance(value, str) else value


def _cursor_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def rank_matches(
    conn: Connection, text: str, *, filter: TrialFilter = EVERY_TRIAL, limit: int = 20
) -> tuple[list[tuple[int, float]], int]:
    """The best ``limit`` matches of ``text`` as ``(id, score)``, and how many were ranked.

    At most ``SEARCH_CANDIDATES`` matches are ranked: the most recently registered.
    """
    match = match_expression(text)
    if match is None or limit <= 0:
        return [], 0
    fts = table("trials_fts", column("rowid", Integer), column("rank", Float))
    inner = select(fts.c.rowid, fts.c.rank).where(
        _sql("trials_fts MATCH :fts_search").bindparams(fts_search=match)
    )
    if not filter.is_empty:
        inner = inner.where(fts.c.rowid.in_(matching_ids(filter)))
    ranked = inner.order_by(fts.c.rowid.desc()).limit(SEARCH_CANDIDATES).subquery()
    stmt = (
        select(ranked.c.rowid, ranked.c.rank, func.count().over())
        .order_by(ranked.c.rank, ranked.c.rowid.desc())
        .limit(limit)
    )
    rows = conn.execute(stmt).all()
    return [(rowid, -rank) for rowid, rank, _ in rows], rows[0][2] if rows else 0


def id_matches(
    conn: Connection, text: str, *, filter: TrialFilter = EVERY_TRIAL, limit: int = 20
) -> list[tuple[int, IdMatch]]:
    """Up to ``limit`` trials that ``text`` names by ID, as ``(id, how)``, in ``filter``.

    First the trials called by one of its ``trial_id_terms`` (``exact``), in the order they
    come in ``text``. Then, if ``text`` is one term (``trial_id_prefixes``), the trials whose
    ID starts with it (``prefix``), in ID order, so search finds trials as an ID is typed.
    """
    c = t.trials.c
    found: dict[int, IdMatch] = {}
    if terms := trial_id_terms(text):
        rows = conn.execute(
            select(c.id, c.source, c.source_id).where(_in(c.source_id, terms), *where(filter))
        ).all()
        order = {term: position for position, term in enumerate(terms)}
        for row in sorted(rows, key=lambda row: (order[row.source_id], row.source, row.id)):
            found.setdefault(row.id, "exact")
    prefixes = trial_id_prefixes(text)
    if prefixes and len(found) < limit:
        # In BINARY order, what starts with a prefix sorts before it with its last letter raised.
        starts = or_(
            *(
                and_(c.source_id > prefix, c.source_id < prefix[:-1] + chr(ord(prefix[-1]) + 1))
                for prefix in prefixes
            )
        )
        stmt = (
            select(c.id)
            .where(starts, *where(filter))
            .order_by(c.source_id, c.id)
            .limit(limit - len(found))
        )
        for (trial_id,) in conn.execute(stmt):
            found.setdefault(trial_id, "prefix")
    return list(found.items())[:limit]


# --- snippets -----------------------------------------------------------------------------

_OPEN, _CLOSE = "\x02", "\x03"
SNIPPET_MARKS = (_OPEN, _CLOSE)
"""What ``snippet()`` is asked to put around matches, for ``snippet_parts`` to split at."""
_MARKS = re.compile(f"({_OPEN}|{_CLOSE})")
_SPACES = re.compile(r"\s+")


class _Snippets:
    """Snippets for search hits, built in a small in-memory FTS5 table per thread.

    ``trials_fts`` is contentless, so it can't make snippets itself. The hits' text is
    unpacked into a temporary table with the same tokenizer, whose ``snippet()`` then marks
    the same words the search matched.
    """

    COLUMNS = (
        "summary",
        "description",
        "eligibility",
        "outcomes",
        "conditions",
        "interventions",
        "other_names",
    )
    TOKENS = 24

    def __init__(self) -> None:
        self._local = threading.local()
        self._lock = threading.Lock()
        self._conns: list[sqlite3.Connection] = []

    def _conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.execute(
                f"CREATE VIRTUAL TABLE snip USING fts5({', '.join(self.COLUMNS)}, "
                "tokenize = 'porter unicode61 remove_diacritics 2')"
            )
            with self._lock:
                self._conns.append(conn)
            self._local.conn = conn
        return conn

    def build(
        self, texts: Mapping[int, Sequence[str | None]], words: str
    ) -> dict[int, tuple[SnippetPart, ...]]:
        """A snippet per trial in ``texts`` (columns in ``COLUMNS`` order) for ``words``.

        Any of the words counts, since a search's words may be split between the title and
        the text. A trial whose text has none of them gets the start of its first text.
        """
        match = match_expression(words, any_word=True)
        if not texts or match is None:
            return {}
        conn = self._conn()
        placeholders = ", ".join("?" * len(self.COLUMNS))
        with conn:
            conn.execute("DELETE FROM snip")
            conn.executemany(
                f"INSERT INTO snip (rowid, {', '.join(self.COLUMNS)}) VALUES (?, {placeholders})",
                [(trial_id, *columns) for trial_id, columns in texts.items()],
            )
            found = {
                rowid: snippet_parts(snippet)
                for rowid, snippet in conn.execute(
                    "SELECT rowid, snippet(snip, -1, ?, ?, '…', ?) FROM snip WHERE snip MATCH ?",
                    (_OPEN, _CLOSE, self.TOKENS, match),
                )
            }
        for trial_id, columns in texts.items():
            if trial_id not in found:
                first = next((value for value in columns if value), None)
                if first is not None:
                    found[trial_id] = (SnippetPart(_leading_words(first, self.TOKENS), False),)
        return found

    def close(self) -> None:
        with self._lock:
            for conn in self._conns:
                conn.close()
            self._conns.clear()


def snippet_parts(snippet: str) -> tuple[SnippetPart, ...]:
    """A snippet made with ``SNIPPET_MARKS`` as parts that matched and parts that didn't."""
    parts: list[SnippetPart] = []
    inside = False
    for piece in _MARKS.split(_SPACES.sub(" ", snippet)):
        if piece in (_OPEN, _CLOSE):
            inside = piece == _OPEN
        elif piece:
            if parts and parts[-1].match == inside:
                parts[-1] = SnippetPart(parts[-1].text + piece, inside)
            else:
                parts.append(SnippetPart(piece, inside))
    return tuple(parts)


def _leading_words(text_: str, count: int) -> str:
    """The first ``count`` words of ``text_``, on one line."""
    words = text_.split()
    return " ".join(words[:count]) + ("…" if len(words) > count else "")


# --- helpers ------------------------------------------------------------------------------

_JSON_IDS = "(SELECT value FROM json_each(:ids))"


def _ids(ids: Iterable[int]) -> dict[str, str]:
    return {"ids": json.dumps(list(ids))}


def _in(column_: KeyedColumnElement[Any], values: Iterable[object]) -> ColumnElement[bool]:
    """``column IN values``, sent as one JSON parameter, so any number of values fits."""
    each = func.json_each(json.dumps(list(values))).table_valued("value")
    return column_.in_(select(each.c.value))


def _next_id(conn: Connection, table_: Table) -> int:
    return int(conn.execute(select(func.coalesce(func.max(table_.c.id), 0) + 1)).scalar_one())


def _sql(statement: str) -> TextClause:
    # Not plain text(): search() and lookup_names() have a parameter called text.
    return text(statement)
