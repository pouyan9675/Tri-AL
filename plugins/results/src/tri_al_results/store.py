"""The plugin's tables in ``trials.db``, rebuilt from the trials' raw documents.

``build_results`` runs before the charts are precomputed (``registry.add_derived``). It reads
the results of trials whose content changed since it last ran (``content_hash``), so an
update reads a few dozen documents and an install all 80,000; a new ``VERSION`` of the
parser reads them all again.

- ``results_trials``: a trial's numbers: participants, how it reported race and ethnicity,
  sex, mean age, the participant flow, and its adverse events over all arms
- ``results_demographics``: participants by race and by ethnicity, when reported in the
  standard NIH/OMB categories (keys of ``parse.RACE`` and ``parse.ETHNICITY``)
- ``results_dropouts``: participants who left, by kind of reason (``parse.DROPOUTS``)
- ``results_events`` and ``results_terms``: each adverse event a trial lists, summed over its
  arms, with the placebo arms apart when it has both kinds
- ``results_analyses``: each statistical analysis of an outcome: its p-value, effect estimate
  with interval, and hypothesis (migration 2)
"""

from collections.abc import Iterable, Iterator, Sequence
from typing import Any

import orjson
from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    delete,
    select,
)

from tri_al.storage import Migration, docs
from tri_al.storage import tables as t
from tri_al_results.parse import (
    ORGAN_CODES,
    AnalysisSum,
    Summary,
    analyses,
    parse,
    summary,
    term_key,
)

VERSION = 2
"""Bump when ``parse`` or ``summary`` read results differently: every trial is read again."""

SOURCE = "ctgov"  # the results format is ClinicalTrials.gov's
BATCH = 2_000

MIGRATIONS = (
    Migration(
        1,
        "results posted to ClinicalTrials.gov",
        """\
CREATE TABLE results_info (
    id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
CREATE TABLE results_trials (
    trial_id INTEGER NOT NULL PRIMARY KEY REFERENCES trials (id) ON DELETE CASCADE,
    content_hash BLOB,
    participants INTEGER,
    race TEXT NOT NULL,
    ethnicity TEXT NOT NULL,
    female INTEGER,
    male INTEGER,
    age REAL,
    started INTEGER,
    completed INTEGER,
    ae_groups INTEGER NOT NULL,
    placebo_groups INTEGER NOT NULL,
    at_risk INTEGER,
    serious INTEGER,
    deaths_at_risk INTEGER,
    deaths INTEGER,
    other_at_risk INTEGER,
    other INTEGER,
    threshold REAL
);
CREATE TABLE results_demographics (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    category TEXT NOT NULL,
    participants INTEGER NOT NULL,
    PRIMARY KEY (trial_id, kind, category)
) WITHOUT ROWID;
CREATE TABLE results_dropouts (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    participants INTEGER NOT NULL,
    PRIMARY KEY (trial_id, kind)
) WITHOUT ROWID;
CREATE TABLE results_terms (
    id INTEGER NOT NULL PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    term TEXT NOT NULL
);
CREATE TABLE results_events (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    serious INTEGER NOT NULL,
    term_id INTEGER NOT NULL REFERENCES results_terms (id),
    organ INTEGER,
    affected INTEGER NOT NULL,
    at_risk INTEGER NOT NULL,
    placebo_affected INTEGER,
    placebo_at_risk INTEGER,
    PRIMARY KEY (trial_id, serious, term_id)
) WITHOUT ROWID;
""",
    ),
    Migration(
        2,
        "outcome analyses",
        """\
CREATE TABLE results_analyses (
    trial_id INTEGER NOT NULL REFERENCES trials (id) ON DELETE CASCADE,
    outcome INTEGER NOT NULL,
    analysis INTEGER NOT NULL,
    kind TEXT NOT NULL,
    p REAL,
    p_bound TEXT,
    estimate_type TEXT,
    estimate REAL,
    ci_lower REAL,
    ci_upper REAL,
    hypothesis TEXT,
    PRIMARY KEY (trial_id, outcome, analysis)
) WITHOUT ROWID;
""",
    ),
)

metadata = MetaData()
info = Table(
    "results_info",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("version", Integer, nullable=False),
)
trials = Table(
    "results_trials",
    metadata,
    Column("trial_id", Integer, primary_key=True),
    Column("content_hash", LargeBinary),
    Column("participants", Integer),
    Column("race", String, nullable=False),
    Column("ethnicity", String, nullable=False),
    Column("female", Integer),
    Column("male", Integer),
    Column("age", Float),
    Column("started", Integer),
    Column("completed", Integer),
    Column("ae_groups", Integer, nullable=False),
    Column("placebo_groups", Integer, nullable=False),
    Column("at_risk", Integer),
    Column("serious", Integer),
    Column("deaths_at_risk", Integer),
    Column("deaths", Integer),
    Column("other_at_risk", Integer),
    Column("other", Integer),
    Column("threshold", Float),
)
demographics = Table(
    "results_demographics",
    metadata,
    Column("trial_id", Integer, primary_key=True),
    Column("kind", String, primary_key=True),
    Column("category", String, primary_key=True),
    Column("participants", Integer, nullable=False),
)
dropouts = Table(
    "results_dropouts",
    metadata,
    Column("trial_id", Integer, primary_key=True),
    Column("kind", String, primary_key=True),
    Column("participants", Integer, nullable=False),
)
terms = Table(
    "results_terms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("key", String, nullable=False, unique=True),
    Column("term", String, nullable=False),
)
events = Table(
    "results_events",
    metadata,
    Column("trial_id", Integer, primary_key=True),
    Column("serious", Boolean, primary_key=True),
    Column("term_id", Integer, primary_key=True),
    Column("organ", Integer),
    Column("affected", Integer, nullable=False),
    Column("at_risk", Integer, nullable=False),
    Column("placebo_affected", Integer),
    Column("placebo_at_risk", Integer),
)
analyses_table = Table(
    "results_analyses",
    metadata,
    Column("trial_id", Integer, primary_key=True),
    Column("outcome", Integer, primary_key=True),
    Column("analysis", Integer, primary_key=True),
    Column("kind", String, nullable=False),
    Column("p", Float),
    Column("p_bound", String),
    Column("estimate_type", String),
    Column("estimate", Float),
    Column("ci_lower", Float),
    Column("ci_upper", Float),
    Column("hypothesis", String),
)
PER_TRIAL = (analyses_table, events, dropouts, demographics, trials)


def build_results(conn: Connection, data_version: int) -> None:
    """Bring the tables up to date with every trial that has results."""
    stored_version = conn.execute(select(info.c.version)).scalar_one_or_none()
    if stored_version != VERSION:
        for table in (*PER_TRIAL, terms):
            conn.execute(delete(table))
        conn.execute(delete(info))
        conn.execute(info.insert().values(id=1, version=VERSION))
    current = dict(
        conn.execute(
            select(t.trials.c.id, t.trials.c.content_hash).where(
                t.trials.c.has_results.is_(True), t.trials.c.source == SOURCE
            )
        ).all()
    )
    stored = dict(conn.execute(select(trials.c.trial_id, trials.c.content_hash)).all())
    stale = [
        trial_id
        for trial_id, digest in stored.items()
        if trial_id not in current or digest is None or current[trial_id] != digest
    ]
    todo = sorted(
        trial_id
        for trial_id, digest in current.items()
        if digest is None or stored.get(trial_id) != digest
    )
    for chunk in _chunks(stale, 500):
        for table in PER_TRIAL:
            conn.execute(delete(table).where(table.c.trial_id.in_(chunk)))
    if not todo:
        return
    writer = _Writer(conn)
    for chunk in _chunks(todo, BATCH):
        for trial_id, study in read_studies(conn, chunk):
            results = parse(study, outcomes=False)
            writer.add(
                trial_id,
                current[trial_id],
                summary(results) if results else Summary(),
                analyses(study),
            )
        writer.flush()


def read_studies(conn: Connection, trial_ids: Sequence[int]) -> Iterator[tuple[int, Any]]:
    """Each trial's raw document, parsed from JSON."""
    decoder = docs.Decoder()

    def load(dict_id: int) -> bytes:
        stmt = select(t.doc_dicts.c.dict).where(t.doc_dicts.c.id == dict_id)
        return bytes(conn.execute(stmt).scalar_one())

    stmt = select(t.trial_docs.c.trial_id, t.trial_docs.c.doc, t.trial_docs.c.dict_id).where(
        t.trial_docs.c.trial_id.in_(trial_ids)
    )
    for trial_id, blob, dict_id in conn.execute(stmt):
        yield trial_id, orjson.loads(decoder.decode(blob, dict_id, load))


class _Writer:
    """Rows for a batch of trials, written together; new event terms get the next id."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.term_ids: dict[str, int] = dict(conn.execute(select(terms.c.key, terms.c.id)).all())
        self.next_term = max(self.term_ids.values(), default=0) + 1
        self.rows: dict[Table, list[tuple[Any, ...]]] = {table: [] for table in PER_TRIAL}
        self.new_terms: list[tuple[int, str, str]] = []

    def add(
        self,
        trial_id: int,
        content_hash: bytes | None,
        s: Summary,
        found: Sequence[AnalysisSum] = (),
    ) -> None:
        self.rows[trials].append(
            (
                trial_id,
                content_hash,
                s.participants,
                s.race,
                s.ethnicity,
                s.female,
                s.male,
                s.age,
                s.started,
                s.completed,
                s.ae_groups,
                s.placebo_groups,
                s.at_risk,
                s.serious,
                s.deaths_at_risk,
                s.deaths,
                s.other_at_risk,
                s.other,
                s.threshold,
            )
        )
        for kind, counts in (("race", s.races), ("ethnicity", s.ethnicities)):
            self.rows[demographics] += [
                (trial_id, kind, category, n) for category, n in counts.items()
            ]
        self.rows[dropouts] += [(trial_id, kind, n) for kind, n in s.dropouts.items()]
        self.rows[analyses_table] += [
            (
                trial_id,
                a.outcome,
                a.analysis,
                a.kind,
                a.p,
                a.p_bound,
                a.estimate_type,
                a.estimate,
                a.ci_lower,
                a.ci_upper,
                a.hypothesis,
            )
            for a in found
        ]
        seen: dict[tuple[bool, int], int] = {}  # the same term twice in one list: summed
        for event in s.events:
            key = term_key(event.term)
            term_id = self.term_ids.get(key)
            if term_id is None:
                term_id = self.term_ids[key] = self.next_term
                self.next_term += 1
                self.new_terms.append((term_id, key, event.term))
            row = (
                trial_id,
                event.serious,
                term_id,
                ORGAN_CODES.get(event.organ or ""),
                event.affected,
                event.at_risk,
                event.placebo_affected,
                event.placebo_at_risk,
            )
            index = seen.get((event.serious, term_id))
            if index is None:
                seen[(event.serious, term_id)] = len(self.rows[events])
                self.rows[events].append(row)
            else:
                self.rows[events][index] = _summed(self.rows[events][index], row)

    def flush(self) -> None:
        if self.new_terms:
            self.conn.exec_driver_sql(
                "INSERT INTO results_terms (id, key, term) VALUES (?, ?, ?)", self.new_terms
            )
            self.new_terms = []
        for table in reversed(PER_TRIAL):  # trials first
            rows = self.rows[table]
            if rows:
                columns = ", ".join(column.name for column in table.columns)
                marks = ", ".join("?" for _ in table.columns)
                self.conn.exec_driver_sql(
                    f"INSERT INTO {table.name} ({columns}) VALUES ({marks})", rows
                )
            self.rows[table] = []


def _summed(a: tuple[Any, ...], b: tuple[Any, ...]) -> tuple[Any, ...]:
    def add(x: int | None, y: int | None) -> int | None:
        return None if x is None and y is None else (x or 0) + (y or 0)

    return (
        *a[:4],
        a[4] + b[4],
        max(a[5], b[5]),
        add(a[6], b[6]),
        None if a[7] is None and b[7] is None else max(a[7] or 0, b[7] or 0),
    )


def _chunks(values: Sequence[int], size: int) -> Iterable[Sequence[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


__all__ = [
    "MIGRATIONS",
    "VERSION",
    "analyses_table",
    "build_results",
    "demographics",
    "dropouts",
    "events",
    "info",
    "read_studies",
    "terms",
    "trials",
]
