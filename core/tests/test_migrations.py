import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from tri_al.storage import (
    Migration,
    MigrationError,
    SQLiteStorage,
    create_engine,
    migrate,
    open_app_db,
    run_script,
)
from tri_al.storage.core_migrations import APP_MIGRATIONS, TRIALS_MIGRATIONS
from tri_al.storage.migrations import current_version


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(tmp_path / "test.db")
    yield engine
    engine.dispose()


def schema(engine: Engine) -> list[tuple[str, str]]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, sql FROM sqlite_schema ORDER BY name"))
        return [(name, sql) for name, sql in rows]


def recorded(engine: Engine) -> list[tuple[str, int, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT component, version, description FROM _migrations ORDER BY 1, 2")
        )
        return [(component, version, description) for component, version, description in rows]


def tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_schema WHERE type = 'table'"))
        return {name for (name,) in rows}


CORE_RECORDED = [
    ("core", migration.version, migration.description) for migration in TRIALS_MIGRATIONS
]

PLUGIN = (
    Migration(1, "notes table", "CREATE TABLE p_notes (id INTEGER PRIMARY KEY, body TEXT);"),
    Migration(2, "tags table", "CREATE TABLE p_tags (note_id INTEGER, tag TEXT);"),
)


def test_migrating_twice_changes_nothing(engine: Engine) -> None:
    assert migrate(engine, {"core": TRIALS_MIGRATIONS}) == {"core": [1, 2, 3]}
    before = schema(engine)

    assert migrate(engine, {"core": TRIALS_MIGRATIONS}) == {"core": []}

    assert schema(engine) == before
    assert recorded(engine) == CORE_RECORDED


def test_storage_open_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "trials.db"
    with SQLiteStorage.open(path):
        pass
    with SQLiteStorage.open(path) as storage:
        assert recorded(storage.engine) == CORE_RECORDED
        with storage.engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM countries")).scalar() == 253


def test_components_are_tracked_separately(engine: Engine) -> None:
    migrate(engine, {"core": TRIALS_MIGRATIONS, "notes": PLUGIN[:1]})

    applied = migrate(engine, {"core": TRIALS_MIGRATIONS, "notes": PLUGIN})

    assert applied == {"core": [], "notes": [2]}
    assert recorded(engine) == [
        *CORE_RECORDED,
        ("notes", 1, "notes table"),
        ("notes", 2, "tags table"),
    ]


def test_migrations_can_be_functions(engine: Engine) -> None:
    def seed(conn: Connection) -> None:
        conn.execute(text("INSERT INTO p_notes (body) VALUES ('hello')"))

    migrate(engine, {"notes": (*PLUGIN, Migration(3, "seed", seed))})

    with engine.connect() as conn:
        assert conn.execute(text("SELECT body FROM p_notes")).scalar() == "hello"


def test_a_failed_migration_is_rolled_back(engine: Engine) -> None:
    broken = Migration(2, "broken", "CREATE TABLE p_half (x);\nSELECT * FROM no_such_table;")

    with pytest.raises(
        MigrationError, match=r"notes: migration 2 \(broken\) failed: .*no_such_table"
    ):
        migrate(engine, {"notes": (PLUGIN[0], broken)})

    assert "p_half" not in tables(engine)
    assert recorded(engine) == [("notes", 1, "notes table")]
    assert migrate(engine, {"notes": PLUGIN}) == {"notes": [2]}


def test_refuses_a_database_from_a_newer_version(engine: Engine) -> None:
    migrate(engine, {"notes": PLUGIN})

    with pytest.raises(MigrationError, match="at migration 2, but this code only has 1"):
        migrate(engine, {"notes": PLUGIN[:1]})


def test_refuses_gaps_in_recorded_migrations(engine: Engine) -> None:
    migrate(engine, {"notes": PLUGIN})
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM _migrations WHERE version = 1"))

    with pytest.raises(MigrationError, match="has gaps"):
        migrate(engine, {"notes": PLUGIN})


@pytest.mark.parametrize("versions", [[2], [1, 3], [2, 1], [1, 1]])
def test_versions_must_count_up_from_one(engine: Engine, versions: list[int]) -> None:
    migrations = [Migration(version, "m", "SELECT 1;") for version in versions]

    with pytest.raises(MigrationError, match=r"must be 1, 2, 3"):
        migrate(engine, {"notes": migrations})

    assert "_migrations" not in tables(engine)


def test_concurrent_migrations_apply_once(tmp_path: Path) -> None:
    calls = []

    def slow(conn: Connection) -> None:
        calls.append(threading.get_ident())
        time.sleep(0.2)
        conn.execute(text("CREATE TABLE p_once (x)"))

    engines = [create_engine(tmp_path / "test.db") for _ in range(2)]
    errors: list[BaseException] = []

    def run(engine: Engine) -> None:
        try:
            migrate(engine, {"once": [Migration(1, "slow", slow)]})
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(engine,)) for engine in engines]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for engine in engines:
        engine.dispose()

    assert errors == []
    assert len(calls) == 1


def test_run_script_runs_each_statement(engine: Engine) -> None:
    script = """
    -- a comment; with a semicolon
    CREATE TABLE p_a (x TEXT);
    INSERT INTO p_a VALUES ('one; two');
    INSERT INTO p_a VALUES ('three');
    """

    with engine.begin() as conn:
        run_script(conn, script)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT x FROM p_a ORDER BY x")).scalars().all() == [
            "one; two",
            "three",
        ]


def test_run_script_rejects_an_unfinished_statement(engine: Engine) -> None:
    with pytest.raises(MigrationError, match="incomplete"), engine.begin() as conn:
        run_script(conn, "CREATE TABLE p_a (x);\nCREATE TABLE p_b (x)")


def test_storage_runs_plugin_migrations_after_the_core(tmp_path: Path) -> None:
    def needs_core(conn: Connection) -> None:
        conn.execute(text("CREATE TABLE notes_by_trial (trial_id INTEGER REFERENCES trials (id))"))

    with SQLiteStorage.open(
        tmp_path / "trials.db", plugin_migrations={"notes": [Migration(1, "t", needs_core)]}
    ) as storage:
        assert recorded(storage.engine)[-1] == ("notes", 1, "t")


def test_plugins_cannot_use_the_core_component_name(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="core"):
        SQLiteStorage.open(tmp_path / "trials.db", plugin_migrations={"core": PLUGIN})


def test_app_db_has_jobs_and_enricher_state(tmp_path: Path) -> None:
    engine = open_app_db(tmp_path / "app.db")
    try:
        assert {"jobs", "enricher_state", "_migrations"} <= tables(engine)
        assert "plugin_state" not in tables(engine)
        assert recorded(engine) == [
            ("core", migration.version, migration.description) for migration in APP_MIGRATIONS
        ]
    finally:
        engine.dispose()


def test_app_db_allows_one_running_data_job(tmp_path: Path) -> None:
    engine = open_app_db(tmp_path / "app.db")
    insert = text(
        "INSERT INTO jobs (type, status, created_at) VALUES (:type, :status, '2026-10-17')"
    )
    try:
        with engine.begin() as conn:
            conn.execute(insert, {"type": "update", "status": "running"})
            conn.execute(insert, {"type": "update", "status": "queued"})
            conn.execute(insert, {"type": "enrich", "status": "running"})
            conn.execute(insert, {"type": "enrich", "status": "running"})
            assert conn.execute(text("SELECT progress FROM jobs LIMIT 1")).scalar() == 0
        with pytest.raises(IntegrityError, match="UNIQUE"), engine.begin() as conn:
            conn.execute(insert, {"type": "install", "status": "running"})
    finally:
        engine.dispose()


def test_current_version_reads_any_database(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    try:
        assert current_version(conn, "core") == 0
        engine = create_engine(path)
        migrate(engine, {"notes": PLUGIN})
        engine.dispose()
        assert current_version(conn, "notes") == 2
        assert current_version(conn, "core") == 0
    finally:
        conn.close()
