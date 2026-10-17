"""SQLite engines with the connection settings and extensions from docs/design.md §5.2."""

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy
from sqlalchemy import Connection, Engine, event

from trial_al.storage.base import StorageError

MIN_SQLITE_VERSION = (3, 45, 0)
"""JSONB needs 3.45, ``group_concat(... ORDER BY ...)`` 3.44 and the trigram tokenizer 3.34."""

PRAGMAS = (
    "journal_mode = WAL",
    "synchronous = NORMAL",
    "foreign_keys = ON",
    "busy_timeout = 5000",
    "temp_store = MEMORY",
    "cache_size = -65536",  # 64 MB
    "mmap_size = 1073741824",  # 1 GB
)
"""Set on every new connection."""

BEGIN = "trial_al_begin"
"""Execution option naming the BEGIN mode: ``conn.execution_options(trial_al_begin="IMMEDIATE")``.

Write transactions use IMMEDIATE, so they take the write lock up front and wait for it
(``busy_timeout``) instead of failing when a read turns into a write.
"""

UV_PYTHON_FIX = (
    "use a Python built by uv, which can: run `uv python install 3.13`, then reinstall "
    "trial-al with it (`uv sync` in a checkout, or `uv tool install --python 3.13 trial-al`)"
)


class ExtensionLoadError(StorageError):
    """A plugin's SQLite extension didn't load, so the plugin's tables can't be used."""


@dataclass(frozen=True, slots=True)
class SqliteExtension:
    """A SQLite extension that a plugin registered with ``registry.add_sqlite_extension``.

    ``load`` receives a raw ``sqlite3.Connection`` with extension loading enabled, and is
    called once for every new connection; ``sqlite_vec.load`` is an example.
    """

    name: str
    load: Callable[[sqlite3.Connection], None]
    plugin: str


def check_sqlite_version(version: tuple[int, int, int] | None = None) -> None:
    """Raise StorageError if ``version`` (default: the linked SQLite's) is too old."""
    version = sqlite3.sqlite_version_info if version is None else version
    if version < MIN_SQLITE_VERSION:
        found = ".".join(map(str, version))
        needed = ".".join(map(str, MIN_SQLITE_VERSION))
        raise StorageError(
            f"this Python's sqlite3 module uses SQLite {found}, but trial-al needs {needed} "
            f"or newer; {UV_PYTHON_FIX}"
        )


def can_load_extensions(connect: Callable[[str], sqlite3.Connection] = sqlite3.connect) -> bool:
    """Whether this interpreter's sqlite3 module can load SQLite extensions."""
    conn = connect(":memory:")
    try:
        conn.enable_load_extension(True)
        conn.enable_load_extension(False)
    except (AttributeError, sqlite3.Error):
        return False
    finally:
        conn.close()
    return True


def load_extension(conn: sqlite3.Connection, extension: SqliteExtension) -> None:
    """Load ``extension`` into ``conn``. SQL can't load extensions before or after."""
    try:
        conn.enable_load_extension(True)
    except AttributeError:
        raise ExtensionLoadError(
            f"plugin {extension.plugin!r} needs the SQLite extension {extension.name!r}, but "
            f"this Python's sqlite3 module can't load extensions; {UV_PYTHON_FIX}"
        ) from None
    try:
        extension.load(conn)
    except Exception as exc:
        raise ExtensionLoadError(
            f"SQLite extension {extension.name!r} from plugin {extension.plugin!r} failed to "
            f"load: {exc}; fix or reinstall the plugin, or disable it with "
            f"`trial-al plugins disable {extension.plugin}`"
        ) from exc
    finally:
        conn.enable_load_extension(False)


def create_engine(path: Path, *, extensions: Sequence[SqliteExtension] = ()) -> Engine:
    """An engine for the SQLite file at ``path`` (created if missing, with its directory).

    Every new connection gets PRAGMAS and then each of ``extensions``. One connection is
    opened straight away, so an old SQLite or an extension that doesn't load fails here, at
    startup, rather than at the first query.
    """
    check_sqlite_version()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = sqlalchemy.create_engine(f"sqlite:///{path}")
    extensions = tuple(extensions)

    def configure(dbapi_connection: sqlite3.Connection, _record: Any) -> None:
        # sqlite3 would otherwise decide when transactions begin; _begin does it instead.
        dbapi_connection.isolation_level = None
        for pragma in PRAGMAS:
            dbapi_connection.execute(f"PRAGMA {pragma}")
        for extension in extensions:
            load_extension(dbapi_connection, extension)

    event.listen(engine, "connect", configure)
    event.listen(engine, "begin", _begin)
    try:
        with engine.connect():
            pass
    except BaseException:
        engine.dispose()
        raise
    return engine


def raw_connection(conn: Connection) -> sqlite3.Connection:
    """The sqlite3 connection under ``conn``, for statements that must run outside a transaction."""
    driver = conn.connection.driver_connection
    assert isinstance(driver, sqlite3.Connection)
    return driver


def _begin(conn: Connection) -> None:
    mode = conn.get_execution_options().get(BEGIN, "DEFERRED")
    conn.exec_driver_sql(f"BEGIN {mode}")
