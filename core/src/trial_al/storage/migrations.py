"""A small migration runner: ordered migrations per component (docs/design.md §5.2).

The core and each plugin are components. A component's migrations are numbered 1, 2, 3, ...
and ``_migrations(component, version)`` records which have run, so running ``migrate``
again only applies what's new. Each migration runs in its own ``BEGIN IMMEDIATE``
transaction, so a failed one leaves nothing half-done and two processes starting at once
can't both apply it.

Released migrations are frozen: change the schema by adding a migration, never by editing
one.
"""

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, Engine

from trial_al.storage.base import StorageError
from trial_al.storage.engine import BEGIN

MIGRATIONS_TABLE = """\
CREATE TABLE IF NOT EXISTS _migrations (
    component TEXT NOT NULL,
    version INTEGER NOT NULL,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    PRIMARY KEY (component, version)
) WITHOUT ROWID"""


class MigrationError(StorageError):
    """Migrations are malformed, failed, or the database is newer than this code."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One schema change. ``apply`` is a SQL script or a function of the open connection.

    A script may hold several statements. It runs inside the migration's transaction, so it
    must not contain BEGIN, COMMIT or PRAGMAs that can't run in a transaction.
    """

    version: int
    description: str
    apply: str | Callable[[Connection], None]


def check_migrations(component: str, migrations: Sequence[Migration]) -> None:
    """Raise MigrationError unless the versions are 1, 2, ..., n in order."""
    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(
            f"{component}: migration versions must be 1, 2, 3, ... in order; got {versions}"
        )


def migrate(engine: Engine, components: Mapping[str, Sequence[Migration]]) -> dict[str, list[int]]:
    """Apply each component's pending migrations, components in the order given.

    Returns the versions applied per component (empty lists when up to date). Raises
    MigrationError if a migration fails, or if the database has a component at a version
    these migrations don't reach (it was migrated by a newer trial-al or plugin).
    """
    for component, migrations in components.items():
        check_migrations(component, migrations)
    applied: dict[str, list[int]] = {component: [] for component in components}
    with engine.connect() as conn:
        conn.execution_options(**{BEGIN: "IMMEDIATE"})
        with conn.begin():
            conn.exec_driver_sql(MIGRATIONS_TABLE)
        for component, migrations in components.items():
            while (migration := _apply_next(conn, component, migrations)) is not None:
                applied[component].append(migration.version)
    return applied


def run_script(conn: Connection, script: str) -> None:
    """Run each statement of a SQL script on ``conn``, inside its current transaction.

    ``sqlite3.Connection.executescript`` would commit first, so statements run one by one.
    """
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.exec_driver_sql(statement)
            statement = ""
    if statement.strip():
        raise MigrationError(f"incomplete SQL statement at the end of a script: {statement!r}")


def current_version(conn: sqlite3.Connection, component: str) -> int:
    """The component's highest applied migration, or 0. Works on any sqlite3 connection."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = '_migrations'"
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute(
        "SELECT coalesce(max(version), 0) FROM _migrations WHERE component = ?", (component,)
    ).fetchone()
    return int(row[0])


def _apply_next(
    conn: Connection, component: str, migrations: Sequence[Migration]
) -> Migration | None:
    with conn.begin():
        row = conn.exec_driver_sql(
            "SELECT count(*), coalesce(max(version), 0) FROM _migrations WHERE component = ?",
            (component,),
        ).one()
        count, latest = int(row[0]), int(row[1])
        if count != latest:
            raise MigrationError(
                f"{component}: _migrations has gaps ({count} migrations recorded, the latest "
                f"is version {latest}), so the schema state is unknown"
            )
        if latest > len(migrations):
            raise MigrationError(
                f"{component}: the database is at migration {latest}, but this code only has "
                f"{len(migrations)}; it was migrated by a newer version, so upgrade"
            )
        if latest == len(migrations):
            return None
        migration = migrations[latest]
        try:
            if isinstance(migration.apply, str):
                run_script(conn, migration.apply)
            else:
                migration.apply(conn)
        except Exception as exc:
            raise MigrationError(
                f"{component}: migration {migration.version} ({migration.description}) "
                f"failed: {exc}"
            ) from exc
        conn.exec_driver_sql(
            "INSERT INTO _migrations (component, version, description, applied_at) "
            "VALUES (?, ?, ?, ?)",
            (component, migration.version, migration.description, datetime.now(UTC).isoformat()),
        )
        return migration
