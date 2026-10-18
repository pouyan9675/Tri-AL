import re
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from tri_al.schema import TrialRecord
from tri_al.storage import (
    SQLiteStorage,
    Storage,
    StorageError,
    create_engine,
    docs,
    migrate,
    sqlite,
)
from tri_al.storage.core_migrations import TRIALS_MIGRATIONS
from tri_al.storage.engine import raw_connection
from tri_al.storage.sqlite import BULK_LOAD_KEY
from tri_al.storage.tables import DEFERRED_INDEXES
from tri_al.testing import StorageContract
from tri_al.testing.fixtures import minimal_trial, phase3_trial, raw_json, sample_trials
from tri_al.testing.storage import source_ids

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class TestSQLiteStorageContract(StorageContract):
    @pytest.fixture
    def storage(self, tmp_path: Path) -> Iterator[Storage]:
        with SQLiteStorage.open(tmp_path / "trials.db") as storage:
            yield storage


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[SQLiteStorage]:
    with SQLiteStorage.open(tmp_path / "trials.db") as storage:
        yield storage


def check_fts(conn: Connection) -> None:
    """Fail unless both full-text indexes are sound and trials_fts has a row per trial."""
    conn.execute(text("INSERT INTO trials_fts (trials_fts) VALUES ('integrity-check')"))
    conn.execute(text("INSERT INTO names_fts (names_fts) VALUES ('integrity-check')"))
    indexed = conn.execute(text("SELECT rowid FROM trials_fts ORDER BY rowid")).scalars().all()
    assert indexed == conn.execute(text("SELECT id FROM trials ORDER BY id")).scalars().all()


def index_names(conn: Connection) -> set[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_schema WHERE type = 'index'"))
    return {name for (name,) in rows}


def test_creates_the_file_and_its_directory(tmp_path: Path) -> None:
    path = tmp_path / "data" / "trials.db"

    SQLiteStorage.open(path).close()

    assert path.exists()


def test_full_text_index_matches_the_data_after_updates(storage: SQLiteStorage) -> None:
    storage.upsert_batch(sample_trials())
    storage.upsert_batch([replace(phase3_trial(), conditions=["Aging"], brief_summary=None)])
    storage.upsert_batch([replace(minimal_trial(), title="Renamed")])

    with storage.engine.connect() as conn:
        check_fts(conn)


def test_the_full_text_index_keeps_no_text(storage: SQLiteStorage) -> None:
    storage.upsert_batch([phase3_trial()])

    with storage.engine.connect() as conn:
        assert conn.execute(text("SELECT title FROM trials_fts")).scalar() is None
        tables = conn.execute(text("SELECT name FROM sqlite_schema")).scalars().all()
    assert "trials_fts_content" not in tables
    assert "trial_outcomes" not in tables


def test_text_is_stored_compressed(storage: SQLiteStorage) -> None:
    records = varied_trials(docs.MIN_SAMPLES + 10)
    records = [
        replace(record, brief_summary=f"Summary {i} of a study of memory.")
        for i, record in enumerate(records)
    ]

    ids = storage.upsert_batch(records)

    with storage.engine.connect() as conn:
        rows = conn.execute(text("SELECT dict_id, text FROM trial_text ORDER BY trial_id")).all()
        kinds = conn.execute(text("SELECT id, kind FROM doc_dicts ORDER BY id")).all()
    assert all(blob.startswith(ZSTD_MAGIC) for _, blob in rows)
    assert sorted(kind for _, kind in kinds) == ["doc", "text"]
    text_dict = next(id_ for id_, kind in kinds if kind == "text")
    assert {dict_id for dict_id, _ in rows} == {text_dict}
    stored = storage.get_trial(ids[7])
    assert stored is not None
    assert stored.brief_summary == "Summary 7 of a study of memory."


def test_searches_rank_only_the_newest_candidates(
    storage: SQLiteStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlite, "SEARCH_CANDIDATES", 2)
    storage.upsert_batch(
        [replace(minimal_trial(), source_id=f"NCT{i}", title=f"Memory study {i}") for i in range(5)]
    )

    result = storage.search("memory", limit=10)

    assert result.candidates == 2
    assert result.capped
    assert sorted(hit.source_id for hit in result.hits) == ["NCT3", "NCT4"]
    assert not storage.search("memory 1", limit=10).capped


def test_reads_see_one_commit(storage: SQLiteStorage) -> None:
    storage.upsert_batch([phase3_trial()])

    with storage.read() as reader:
        before = reader.data_version()
        storage.upsert_batch([minimal_trial()])
        with storage.engine.begin() as conn:
            conn.execute(text("UPDATE meta SET value = '9' WHERE key = 'data_version'"))
        assert reader.data_version() == before
        assert reader.count_trials() == 1

    with storage.read() as reader:
        assert (reader.data_version(), reader.count_trials()) == (9, 2)


def test_attach_refuses_a_database_that_needs_migrations(tmp_path: Path) -> None:
    path = tmp_path / "trials.db"
    engine = create_engine(path)
    try:
        migrate(engine, {"core": TRIALS_MIGRATIONS[:2]})
    finally:
        engine.dispose()

    with pytest.raises(StorageError, match="needs migrations"):
        SQLiteStorage.attach(path)
    SQLiteStorage.open(path).close()
    SQLiteStorage.attach(path).close()
    with pytest.raises(StorageError, match="install"):
        SQLiteStorage.attach(tmp_path / "missing.db")


def test_bulk_load_drops_and_rebuilds_secondary_indexes(storage: SQLiteStorage) -> None:
    deferred = {str(index.name) for index in DEFERRED_INDEXES}
    with storage.engine.connect() as conn:
        assert deferred <= index_names(conn)

    with storage.bulk_load() as load:
        load.upsert_batch(sample_trials())
        with storage.engine.connect() as conn:
            assert not deferred & index_names(conn)
            assert conn.execute(text("PRAGMA synchronous")).scalar() == 1  # other connections

    with storage.engine.connect() as conn:
        assert deferred <= index_names(conn)
        check_fts(conn)
        assert conn.execute(text("SELECT count(*) FROM sqlite_stat1")).scalar_one() > 0
        assert (
            conn.execute(
                text("SELECT count(*) FROM meta WHERE key = :k"), {"k": BULK_LOAD_KEY}
            ).scalar()
            == 0
        )


def test_bulk_load_turns_synchronous_off_then_back_on(storage: SQLiteStorage) -> None:
    with storage.bulk_load() as load:
        load.upsert_batch([minimal_trial()])
        raw = raw_connection(load._conn)
        assert raw.execute("PRAGMA synchronous").fetchone() == (0,)

    # The connection goes back to the pool, so it must be back to NORMAL.
    assert raw.execute("PRAGMA synchronous").fetchone() == (1,)


def test_an_unfinished_bulk_load_is_recorded(storage: SQLiteStorage) -> None:
    with pytest.raises(RuntimeError), storage.bulk_load():
        raise RuntimeError

    with storage.engine.connect() as conn:
        started = conn.execute(
            text("SELECT value FROM meta WHERE key = :key"), {"key": BULK_LOAD_KEY}
        ).scalar()
    assert started is not None
    with pytest.raises(StorageError, match=re.escape(f"started at {started}")):
        storage.upsert_batch([minimal_trial()])


def test_transaction_connection_writes_in_the_same_transaction(storage: SQLiteStorage) -> None:
    def data_version() -> str:
        with storage.engine.connect() as conn:
            return str(
                conn.execute(text("SELECT value FROM meta WHERE key = 'data_version'")).scalar()
            )

    def write(*, fail: bool) -> None:
        with storage.transaction() as tx:
            tx.upsert_batch([minimal_trial()])
            tx.connection.execute(text("UPDATE meta SET value = '7' WHERE key = 'data_version'"))
            if fail:
                raise RuntimeError("stop")

    with pytest.raises(RuntimeError, match="stop"):
        write(fail=True)
    assert data_version() == "0"
    assert storage.count_trials() == 0

    write(fail=False)
    assert data_version() == "7"
    assert storage.count_trials() == 1


def test_write_transactions_take_the_lock_up_front(storage: SQLiteStorage, tmp_path: Path) -> None:
    other = sqlite3.connect(tmp_path / "trials.db", timeout=0)
    try:
        with storage.transaction():
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
            # Readers still see the last commit.
            assert other.execute("SELECT count(*) FROM trials").fetchone() == (0,)
    finally:
        other.close()


def test_raw_comes_back_byte_for_byte(storage: SQLiteStorage) -> None:
    raw = b'{ "a": [1, 2.50, "K\\u00f6ln"],\n "b": {} }'

    [trial_id] = storage.upsert_batch([replace(minimal_trial(), raw=raw)])

    stored = storage.get_trial(trial_id)
    assert stored is not None
    assert stored.raw == raw


def varied_trials(count: int) -> list[TrialRecord]:
    """Trials whose raw documents differ the way real ones do, enough to train a dictionary."""
    words = [
        "amyloid",
        "tau",
        "donepezil",
        "placebo",
        "cognition",
        "memory",
        "dementia",
        "infusion",
    ]
    return [
        replace(
            minimal_trial(),
            source_id=f"NCT{i:08d}",
            raw=raw_json(
                {
                    "nctId": f"NCT{i:08d}",
                    "title": " ".join(words[(i + j) % len(words)] for j in range(i % 7 + 3)),
                    "enrollment": i * 37 % 1000,
                    "sites": [{"city": f"City {k}", "zip": f"{i * k:05d}"} for k in range(i % 5)],
                }
            ),
        )
        for i in range(count)
    ]


def doc_dict_ids(storage: SQLiteStorage) -> list[int]:
    with storage.engine.connect() as conn:
        rows = conn.execute(text("SELECT id FROM doc_dicts WHERE kind = 'doc' ORDER BY id"))
        return list(rows.scalars())


def docs_rows(storage: SQLiteStorage) -> list[tuple[int | None, bytes]]:
    with storage.engine.connect() as conn:
        rows = conn.execute(text("SELECT dict_id, doc FROM trial_docs ORDER BY trial_id"))
        return [(dict_id, doc) for dict_id, doc in rows]


def test_raw_documents_are_compressed(storage: SQLiteStorage) -> None:
    records = varied_trials(10)

    storage.upsert_batch(records)

    rows = docs_rows(storage)
    assert [dict_id for dict_id, _ in rows] == [None] * 10  # too few to train a dictionary
    assert all(doc.startswith(ZSTD_MAGIC) for _, doc in rows)


def test_the_first_big_batch_trains_a_dictionary(storage: SQLiteStorage) -> None:
    records = varied_trials(docs.MIN_SAMPLES + 200)

    ids = storage.upsert_batch(records[:-100])
    ids += storage.upsert_batch(records[-100:])

    rows = docs_rows(storage)
    [dict_id] = doc_dict_ids(storage)
    assert {row_dict for row_dict, _ in rows} == {dict_id}
    raw_size = sum(len(record.raw or b"") for record in records)
    assert sum(len(doc) for _, doc in rows) < raw_size / 3
    for record, trial_id in zip(records[::97], ids[::97], strict=True):
        stored = storage.get_trial(trial_id)
        assert stored is not None
        assert stored.raw == record.raw


def test_a_bulk_load_trains_a_dictionary_too(storage: SQLiteStorage) -> None:
    records = varied_trials(docs.MIN_SAMPLES)

    with storage.bulk_load() as load:
        ids = load.upsert_batch(records)

    assert {dict_id for dict_id, _ in docs_rows(storage)} == set(doc_dict_ids(storage))
    stored = storage.get_trial(ids[-1])
    assert stored is not None
    assert stored.raw == records[-1].raw


def test_migration_2_recompresses_documents(tmp_path: Path) -> None:
    path = tmp_path / "trials.db"
    engine = create_engine(path)
    try:
        migrate(engine, {"core": TRIALS_MIGRATIONS[:1]})
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO trials (id, source, source_id, title, has_results, num_sites,"
                    " ingested_at) VALUES (1, 'ctgov', 'NCT1', 'T', 0, 0, '2026-01-01T00:00:00')"
                )
            )
            conn.execute(text("""INSERT INTO trial_docs VALUES (1, jsonb('{"a": [1, "b"]}'))"""))
    finally:
        engine.dispose()

    with SQLiteStorage.open(path) as storage:
        stored = storage.get_trial(1)
        assert stored is not None
        assert stored.raw == b'{"a":[1,"b"]}'
        with storage.engine.connect() as conn:
            codes = conn.execute(text("SELECT code FROM countries WHERE code IN ('XK', 'CS')"))
            assert sorted(code for (code,) in codes) == ["CS", "XK"]


def test_migration_3_makes_the_index_contentless_and_compresses_text(tmp_path: Path) -> None:
    path = tmp_path / "trials.db"
    engine = create_engine(path)
    try:
        migrate(engine, {"core": TRIALS_MIGRATIONS[:2]})
        with engine.begin() as conn:
            for trial_id, title in ((1, "Donepezil for memory"), (2, "Sleep and mood")):
                conn.execute(
                    text(
                        "INSERT INTO trials (id, source, source_id, title, has_results, num_sites,"
                        " ingested_at) VALUES (:id, 'ctgov', :sid, :title, 0, 0,"
                        " '2026-01-01T00:00:00+00:00')"
                    ),
                    {"id": trial_id, "sid": f"NCT{trial_id}", "title": title},
                )
            conn.execute(
                text("INSERT INTO trial_text VALUES (1, 'A summary of plaques.', NULL, 'Age 50+')")
            )
            conn.execute(
                text(
                    "INSERT INTO trial_outcomes VALUES (1, 0, 'primary', 'ADAS-Cog', 'Cognition',"
                    " '12 weeks'), (1, 1, 'secondary', 'Sleep diary', NULL, NULL)"
                )
            )
            conn.execute(text("INSERT INTO trials_fts (trials_fts) VALUES ('rebuild')"))
    finally:
        engine.dispose()

    with SQLiteStorage.open(path) as storage:
        stored = storage.get_trial(1)
        assert stored is not None
        assert (stored.brief_summary, stored.description, stored.eligibility_criteria) == (
            "A summary of plaques.",
            None,
            "Age 50+",
        )
        assert [(o.kind, o.measure, o.description, o.time_frame) for o in stored.outcomes] == [
            ("primary", "ADAS-Cog", "Cognition", "12 weeks"),
            ("secondary", "Sleep diary", None, None),
        ]
        other = storage.get_trial(2)
        assert other is not None
        assert (other.brief_summary, other.outcomes) == (None, [])
        assert source_ids(storage.search("plaque").hits) == ["NCT1"]
        assert source_ids(storage.search("cognition").hits) == ["NCT1"]
        assert source_ids(storage.search("mood").hits) == ["NCT2"]
        with storage.engine.connect() as conn:
            check_fts(conn)
            tables = conn.execute(text("SELECT name FROM sqlite_schema")).scalars().all()
        assert "trial_outcomes" not in tables
        assert "trial_text_3" not in tables
        storage.upsert_batch([replace(minimal_trial(), source_id="NCT2", title="Renamed")])
        assert storage.search("mood").hits == []
        storage.check()
