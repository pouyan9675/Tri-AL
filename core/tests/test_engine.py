import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, OperationalError

from tri_al.storage import (
    ExtensionLoadError,
    Migration,
    SqliteExtension,
    SQLiteStorage,
    StorageError,
    can_load_extensions,
    check_sqlite_version,
    create_engine,
    load_extension,
)

EXPECTED_PRAGMAS = {
    "journal_mode": "wal",
    "synchronous": 1,  # NORMAL
    "foreign_keys": 1,
    "busy_timeout": 5000,
    "temp_store": 2,  # MEMORY
    "cache_size": -65536,
    "mmap_size": 1073741824,
}


class NoExtensions(sqlite3.Connection):
    """A connection like macOS's system Python gives: it can't load extensions."""

    def enable_load_extension(self, enabled: bool, /) -> None:
        raise AttributeError("enable_load_extension")


def hello_extension(calls: list[str] | None = None) -> Callable[[sqlite3.Connection], None]:
    """An extension stand-in that adds a SQL function, hello()."""

    def load(conn: sqlite3.Connection) -> None:
        if calls is not None:
            calls.append("load")
        conn.create_function("hello", 0, lambda: "hi")

    return load


def test_every_connection_gets_the_pragmas(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "test.db")
    try:
        conns = [engine.connect() for _ in range(3)]
        for conn in conns:
            for pragma, value in EXPECTED_PRAGMAS.items():
                assert conn.execute(text(f"PRAGMA {pragma}")).scalar() == value, pragma
        for conn in conns:
            conn.close()
    finally:
        engine.dispose()


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    with (
        SQLiteStorage.open(tmp_path / "trials.db") as storage,
        pytest.raises(IntegrityError, match="FOREIGN KEY"),
        storage.engine.begin() as conn,
    ):
        conn.execute(text("INSERT INTO trial_text (trial_id, text) VALUES (42, x'00')"))


@pytest.mark.parametrize("version", [(3, 44, 2), (3, 8, 0)])
def test_rejects_old_sqlite(version: tuple[int, int, int]) -> None:
    found = ".".join(map(str, version))
    with pytest.raises(
        StorageError, match=rf"SQLite {found}, but .* needs 3\.45\.0.*uv python install"
    ):
        check_sqlite_version(version)


def test_engines_refuse_old_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 40, 0))

    with pytest.raises(StorageError, match=r"needs 3\.45\.0"):
        create_engine(tmp_path / "test.db")


def test_accepts_new_enough_sqlite() -> None:
    check_sqlite_version((3, 45, 0))
    check_sqlite_version()


def test_detects_whether_extensions_can_load() -> None:
    assert can_load_extensions()
    assert not can_load_extensions(lambda path: sqlite3.connect(path, factory=NoExtensions))


def test_extensions_load_on_every_connection(tmp_path: Path) -> None:
    calls: list[str] = []
    extension = SqliteExtension("hello", hello_extension(calls), "greeter")
    engine = create_engine(tmp_path / "test.db", extensions=[extension])
    try:
        conns = [engine.connect() for _ in range(3)]
        assert [conn.execute(text("SELECT hello()")).scalar() for conn in conns] == ["hi"] * 3
        assert calls == ["load"] * 3
        for conn in conns:
            conn.close()
    finally:
        engine.dispose()


def test_extension_loading_is_only_on_during_load(tmp_path: Path) -> None:
    errors: list[str] = []

    def load(conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.OperationalError) as exc_info:
            conn.load_extension(str(tmp_path / "no-such-extension"))
        errors.append(str(exc_info.value))

    engine = create_engine(tmp_path / "test.db", extensions=[SqliteExtension("x", load, "p")])
    try:
        # During load() the file was looked for, so loading was allowed...
        assert "not authorized" not in errors[0]
        # ...but SQL can't load extensions afterwards.
        with pytest.raises(OperationalError, match="not authorized"), engine.connect() as conn:
            conn.execute(text("SELECT load_extension(:path)"), {"path": str(tmp_path / "x")})
    finally:
        engine.dispose()


def test_a_failing_extension_stops_startup(tmp_path: Path) -> None:
    def load(conn: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("dlopen(vec0.dylib): image not found")

    with pytest.raises(ExtensionLoadError) as exc_info:
        SQLiteStorage.open(
            tmp_path / "trials.db", extensions=[SqliteExtension("vec0", load, "vectors")]
        )

    assert str(exc_info.value) == (
        "SQLite extension 'vec0' from plugin 'vectors' failed to load: dlopen(vec0.dylib): "
        "image not found; fix or reinstall the plugin, or disable it with "
        "`tri-al plugins disable vectors`"
    )


def test_extensions_need_an_interpreter_that_can_load_them() -> None:
    conn = sqlite3.connect(":memory:", factory=NoExtensions)
    try:
        with pytest.raises(ExtensionLoadError, match=r"can't load extensions; .*uv python install"):
            load_extension(conn, SqliteExtension("vec0", hello_extension(), "vectors"))
    finally:
        conn.close()


def test_plugin_migrations_run_after_extensions_load(tmp_path: Path) -> None:
    def uses_extension(conn: Connection) -> None:
        conn.execute(text("CREATE TABLE greeter_hello AS SELECT hello() AS greeting"))

    with (
        SQLiteStorage.open(
            tmp_path / "trials.db",
            extensions=[SqliteExtension("hello", hello_extension(), "greeter")],
            plugin_migrations={"greeter": [Migration(1, "hello", uses_extension)]},
        ) as storage,
        storage.engine.connect() as conn,
    ):
        assert conn.execute(text("SELECT greeting FROM greeter_hello")).scalar() == "hi"
