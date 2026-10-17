import re
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DatabaseError

from trial_al.schema import TrialRecord
from trial_al.storage import SQLiteStorage, Storage, StorageError, create_engine, docs, migrate
from trial_al.storage.core_migrations import TRIALS_MIGRATIONS
from trial_al.storage.engine import raw_connection
from trial_al.storage.sqlite import BULK_LOAD_KEY
from trial_al.storage.tables import DEFERRED_INDEXES
from trial_al.testing import StorageContract
from trial_al.testing.fixtures import minimal_trial, phase3_trial, raw_json, sample_trials

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
    """Fail unless trials_fts holds exactly what trials_fts_content says it should."""
    conn.execute(text("INSERT INTO trials_fts (trials_fts, rank) VALUES ('integrity-check', 1)"))
    conn.execute(text("INSERT INTO names_fts (names_fts) VALUES ('integrity-check')"))


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


def test_check_fts_notices_drift(storage: SQLiteStorage) -> None:
    storage.upsert_batch([phase3_trial()])

    with storage.engine.begin() as conn:
        conn.execute(text("UPDATE trials SET title = 'Changed behind the index'"))
        with pytest.raises(DatabaseError, match="malformed"):
            check_fts(conn)


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
    assert {dict_id for dict_id, _ in rows} == {1}
    with storage.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM doc_dicts")).scalar() == 1
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

    assert {dict_id for dict_id, _ in docs_rows(storage)} == {1}
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
