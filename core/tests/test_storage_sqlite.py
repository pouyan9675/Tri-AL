import re
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DatabaseError

from trial_al.storage import SQLiteStorage, Storage, StorageError
from trial_al.storage.engine import raw_connection
from trial_al.storage.sqlite import BULK_LOAD_KEY
from trial_al.storage.tables import DEFERRED_INDEXES
from trial_al.testing import StorageContract
from trial_al.testing.fixtures import minimal_trial, phase3_trial, sample_trials


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


def test_raw_json_comes_back_compact(storage: SQLiteStorage) -> None:
    record = replace(minimal_trial(), raw=b'{ "a": [1, 2.50, "K\\u00f6ln"],\n "b": {} }')

    [trial_id] = storage.upsert_batch([record])

    stored = storage.get_trial(trial_id)
    assert stored is not None
    assert stored.raw == b'{"a":[1,2.50,"K\\u00f6ln"],"b":{}}'


def test_rejects_raw_that_is_not_json(storage: SQLiteStorage) -> None:
    with pytest.raises(DatabaseError, match="malformed JSON"):
        storage.upsert_batch([replace(minimal_trial(), raw=b"{nope")])

    assert storage.count_trials() == 0
