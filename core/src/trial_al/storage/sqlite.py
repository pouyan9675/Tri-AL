"""The SQLite storage backend (docs/design.md §5.2 and §6)."""

import json
import re
from collections import Counter
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    Select,
    Table,
    TextClause,
    bindparam,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.exc import DatabaseError
from sqlalchemy.sql.elements import KeyedColumnElement

from trial_al.schema import (
    Intervention,
    Location,
    MeshTerm,
    Outcome,
    Sponsor,
    TrialRecord,
    without_repeats,
)
from trial_al.storage import docs
from trial_al.storage import tables as t
from trial_al.storage.base import (
    ALL_TRIALS,
    NameHit,
    NameKind,
    SearchHit,
    StorageError,
    TrialQuery,
    TrialSummary,
)
from trial_al.storage.core_migrations import COMPONENT, TRIALS_MIGRATIONS
from trial_al.storage.engine import (
    BEGIN,
    SqliteExtension,
    create_engine,
    raw_connection,
)
from trial_al.storage.migrations import Migration, MigrationError, migrate

BULK_LOAD_KEY = "bulk_load_started"
"""``meta`` key set while a bulk load is running or after one that didn't finish."""

_FTS_COLUMNS = (
    "title, official_title, conditions, interventions, other_names, "
    "summary, description, eligibility, outcomes"
)
_WORD = re.compile(r"\w+")
_FTS_INTEGRITY_CHECKS = (
    "INSERT INTO trials_fts (trials_fts, rank) VALUES ('integrity-check', 1)",
    "INSERT INTO names_fts (names_fts) VALUES ('integrity-check')",
)


def components(
    core: Sequence[Migration], plugins: Mapping[str, Sequence[Migration]] | None
) -> dict[str, Sequence[Migration]]:
    """The core's migrations first, then each plugin's."""
    plugins = plugins or {}
    if COMPONENT in plugins:
        raise MigrationError(f"plugin migrations can't use the core's component name {COMPONENT!r}")
    return {COMPONENT: core, **plugins}


class SQLiteStorage:
    """Trials in a SQLite file. Thread-safe: each call takes a pooled connection."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._decoder = docs.Decoder()

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        extensions: Sequence[SqliteExtension] = (),
        plugin_migrations: Mapping[str, Sequence[Migration]] | None = None,
    ) -> Self:
        """Open (or create) ``trials.db`` at ``path`` and apply pending migrations.

        ``plugin_migrations`` maps each plugin's name to its ``trials`` migrations; they run
        after the core's, and after every extension has loaded.
        """
        engine = create_engine(path, extensions=extensions)
        try:
            migrate(engine, components(TRIALS_MIGRATIONS, plugin_migrations))
        except BaseException:
            engine.dispose()
            raise
        return cls(engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    def close(self) -> None:
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

    def get_trial(self, trial_id: int) -> TrialRecord | None:
        with self._engine.connect() as conn:
            return _read_trial(conn, trial_id, self._decoder)

    def find_trial(self, source: str, source_id: str) -> TrialRecord | None:
        with self._engine.connect() as conn:
            return _find_trial(conn, source, source_id, self._decoder)

    def content_hashes(
        self, source: str, source_ids: Iterable[str] | None = None
    ) -> dict[str, bytes | None]:
        with self._engine.connect() as conn:
            return _content_hashes(conn, source, source_ids)

    def query_trials(self, query: TrialQuery = ALL_TRIALS) -> list[TrialSummary]:
        stmt = _filtered(
            select(
                t.trials.c.id,
                t.trials.c.source,
                t.trials.c.source_id,
                t.trials.c.title,
                t.trials.c.status,
                t.trials.c.phase,
                t.trials.c.start_date,
                t.trials.c.last_update,
                t.trials.c.enrollment,
            ),
            query,
        )
        if query.after_id is not None:
            stmt = stmt.where(t.trials.c.id > query.after_id)
        stmt = stmt.order_by(t.trials.c.id).limit(query.limit)
        with self._engine.connect() as conn:
            return [TrialSummary(*row) for row in conn.execute(stmt)]

    def count_trials(self, query: TrialQuery = ALL_TRIALS) -> int:
        stmt = _filtered(select(func.count()).select_from(t.trials), query)
        with self._engine.connect() as conn:
            return conn.execute(stmt).scalar_one()

    def search(self, text: str, *, limit: int = 20) -> list[SearchHit]:
        words = _WORD.findall(text)
        if not words or limit <= 0:
            return []
        # Quoting each word makes FTS5 syntax (AND, NOT, *, column:) plain text.
        match = " ".join(f'"{word}"' for word in words)
        stmt = _sql(
            """
            SELECT t.id, t.source, t.source_id, t.title, -f.rank
            FROM (
                SELECT rowid, rank FROM trials_fts WHERE trials_fts MATCH :match
                ORDER BY rank LIMIT :limit
            ) AS f
            JOIN trials AS t ON t.id = f.rowid
            ORDER BY f.rank
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(stmt, {"match": match, "limit": limit})
            return [SearchHit(*row) for row in rows]

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
            SELECT kind, ref, name FROM names_fts
            WHERE {condition} AND (:kind IS NULL OR kind = :kind)
            ORDER BY length(name), name LIMIT :limit
            """
        )
        with self._engine.connect() as conn:
            return [NameHit(*row) for row in conn.execute(stmt, params)]

    def check(self, *, full_text: bool = True) -> None:
        """Raise StorageError unless the database is sound.

        Runs SQLite's ``quick_check``, makes sure no bulk load is unfinished and, with
        ``full_text``, checks both full-text indexes against the data they index.
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
                    raise StorageError(f"a full-text index doesn't match the data: {exc}") from exc
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
            column = self.table.c[self.key]
            stmt = select(column, self.table.c.id).where(_in(column, missing))
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


class _Docs:
    """Compresses raw documents for ``trial_docs``, training the dictionary when it can."""

    def __init__(self, conn: Connection) -> None:
        latest = conn.execute(
            select(t.doc_dicts.c.id, t.doc_dicts.c.dict).order_by(t.doc_dicts.c.id.desc()).limit(1)
        ).one_or_none()
        self._encoder = docs.Encoder() if latest is None else docs.Encoder(*latest)
        self._trained = latest is not None

    def rows(self, conn: Connection, raws: Sequence[tuple[int, bytes]]) -> list[dict[str, Any]]:
        if not self._trained and (content := docs.train([raw for _, raw in raws])):
            dict_id = _next_id(conn, t.doc_dicts)
            conn.execute(
                insert(t.doc_dicts),
                {"id": dict_id, "dict": content, "created_at": datetime.now(UTC)},
            )
            self._encoder = docs.Encoder(dict_id, content)
            self._trained = True
        encoder = self._encoder
        return [
            {"trial_id": trial_id, "doc": encoder.encode(raw), "dict_id": encoder.dict_id}
            for trial_id, raw in raws
        ]


class _Writer:
    """Upserts batches of trials on one connection, inside the caller's transaction.

    ``bulk`` skips the full-text upkeep that ``_finish_bulk_load`` redoes in one pass, and
    keeps every entity id in memory across batches.
    """

    def __init__(self, conn: Connection, *, bulk: bool) -> None:
        self._conn = conn
        self._bulk = bulk
        self._conditions = _Names(t.conditions, "name", "condition")
        self._interventions = _Names(t.interventions, "name", "intervention")
        self._sponsors = _Names(t.sponsors, "name", "sponsor")
        self._mesh = _MeshTerms()
        self._docs = _Docs(conn)
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
            if not self._bulk:
                # FTS5 reads the old text from trials_fts_content to delete it, so this must
                # run before anything that text comes from changes.
                conn.execute(
                    _sql("DELETE FROM trials_fts WHERE rowid IN " + _JSON_IDS), _ids(existing)
                )
            for table in t.LINK_TABLES:
                conn.execute(delete(table).where(_in(table.c.trial_id, existing)))

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

        if not self._bulk:
            conn.execute(
                _sql(
                    f"INSERT INTO trials_fts (rowid, {_FTS_COLUMNS}) "
                    f"SELECT id, {_FTS_COLUMNS} FROM trials_fts_content WHERE id IN {_JSON_IDS}"
                ),
                _ids(ids),
            )
            if new_names:
                conn.execute(_sql("INSERT INTO names_fts VALUES (:name, :kind, :ref)"), new_names)
        return ids

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
            "lead_sponsor_id": None if lead is None else self._sponsors.ids[lead.name],
            "lead_sponsor_class": None if lead is None else lead.sponsor_class,
            "min_age_days": record.min_age_days,
            "max_age_days": record.max_age_days,
            "sex": record.sex,
            "healthy_volunteers": record.healthy_volunteers,
            "location_scope": record.location_scope,
            "num_sites": record.num_sites,
            "content_hash": record.content_hash,
            "ingested_at": now,
        }

    def _insert_children(self, records: Sequence[TrialRecord], ids: Sequence[int]) -> None:
        rows: dict[Table, list[dict[str, Any]]] = {table: [] for table in t.LINK_TABLES}
        raws: list[tuple[int, bytes]] = []
        for record, trial_id in zip(records, ids, strict=True):
            rows[t.trial_text].append(
                {
                    "trial_id": trial_id,
                    "brief_summary": record.brief_summary,
                    "description": record.description,
                    "eligibility_criteria": record.eligibility_criteria,
                }
            )
            rows[t.trial_outcomes] += (
                {
                    "trial_id": trial_id,
                    "position": position,
                    "kind": outcome.kind,
                    "measure": outcome.measure,
                    "description": outcome.description,
                    "time_frame": outcome.time_frame,
                }
                for position, outcome in enumerate(record.outcomes)
            )
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
        rows[t.trial_docs] = self._docs.rows(self._conn, raws)
        for table, table_rows in rows.items():
            if table_rows:
                self._conn.execute(insert(table), table_rows)


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
    conn.execute(_sql("INSERT INTO trials_fts (trials_fts) VALUES ('delete-all')"))
    conn.execute(_sql("DELETE FROM names_fts"))


def _finish_bulk_load(conn: Connection) -> None:
    for index in t.DEFERRED_INDEXES:
        index.create(conn, checkfirst=True)
    conn.execute(_sql("INSERT INTO trials_fts (trials_fts) VALUES ('rebuild')"))
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
    conn: Connection, source: str, source_id: str, decoder: docs.Decoder
) -> TrialRecord | None:
    trial_id = conn.execute(
        select(t.trials.c.id).where(t.trials.c.source == source, t.trials.c.source_id == source_id)
    ).scalar_one_or_none()
    return None if trial_id is None else _read_trial(conn, trial_id, decoder)


def _read_trial(conn: Connection, trial_id: int, decoder: docs.Decoder) -> TrialRecord | None:
    trial = conn.execute(select(t.trials).where(t.trials.c.id == trial_id)).one_or_none()
    if trial is None:
        return None

    def rows(stmt: Select[Any], table: Table) -> Iterator[Any]:
        return iter(
            conn.execute(stmt.where(table.c.trial_id == trial_id).order_by(table.c.position))
        )

    text_row = conn.execute(
        select(t.trial_text).where(t.trial_text.c.trial_id == trial_id)
    ).one_or_none()
    doc = conn.execute(
        select(t.trial_docs.c.doc, t.trial_docs.c.dict_id).where(
            t.trial_docs.c.trial_id == trial_id
        )
    ).one_or_none()

    def load_dict(dict_id: int) -> bytes:
        stmt = select(t.doc_dicts.c.dict).where(t.doc_dicts.c.id == dict_id)
        return bytes(conn.execute(stmt).scalar_one())

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
        start_date=trial.start_date,
        primary_completion_date=trial.primary_completion_date,
        completion_date=trial.completion_date,
        first_posted=trial.first_posted,
        last_update=trial.last_update,
        enrollment=trial.enrollment,
        enrollment_type=trial.enrollment_type,
        arms_count=trial.arms_count,
        has_results=trial.has_results,
        min_age_days=trial.min_age_days,
        max_age_days=trial.max_age_days,
        sex=trial.sex,
        healthy_volunteers=trial.healthy_volunteers,
        brief_summary=None if text_row is None else text_row.brief_summary,
        description=None if text_row is None else text_row.description,
        eligibility_criteria=None if text_row is None else text_row.eligibility_criteria,
        outcomes=[
            Outcome(row.kind, row.measure, row.description, row.time_frame)
            for row in rows(select(t.trial_outcomes), t.trial_outcomes)
        ],
        conditions=[
            row.name
            for row in rows(
                select(t.conditions.c.name).join(t.trial_conditions), t.trial_conditions
            )
        ],
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
            Intervention(row.name, row.type, tuple(aliases.get(row.id, ())))
            for row in rows(
                select(
                    t.interventions.c.id, t.interventions.c.name, t.trial_interventions.c.type
                ).join(t.trial_interventions),
                t.trial_interventions,
            )
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
        raw=None if doc is None else decoder.decode(doc.doc, doc.dict_id, load_dict),
        content_hash=trial.content_hash,
        ingested_at=trial.ingested_at,
    )


def _filtered[S: Select[Any]](stmt: S, query: TrialQuery) -> S:
    if query.status is not None:
        stmt = stmt.where(t.trials.c.status.in_(query.status))
    if query.phase is not None:
        stmt = stmt.where(t.trials.c.phase.in_(query.phase))
    return stmt


# --- helpers ------------------------------------------------------------------------------

_JSON_IDS = "(SELECT value FROM json_each(:ids))"


def _ids(ids: Iterable[int]) -> dict[str, str]:
    return {"ids": json.dumps(list(ids))}


def _in(column: KeyedColumnElement[Any], values: Iterable[object]) -> ColumnElement[bool]:
    """``column IN values``, sent as one JSON parameter, so any number of values fits."""
    each = func.json_each(json.dumps(list(values))).table_valued("value")
    return column.in_(select(each.c.value))


def _next_id(conn: Connection, table: Table) -> int:
    return int(conn.execute(select(func.coalesce(func.max(table.c.id), 0) + 1)).scalar_one())


def _sql(statement: str) -> TextClause:
    # Not plain text(): search() and lookup_names() have a parameter called text.
    return text(statement)
