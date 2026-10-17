"""The migrations and the SQLAlchemy tables in ``tri_al.storage.tables`` describe one schema."""

import sqlite3
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import MetaData, Table, UniqueConstraint
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.sql.elements import TextClause

from tri_al.schema import Location, Sponsor
from tri_al.storage import SQLiteStorage, open_app_db
from tri_al.storage.tables import DEFERRED_INDEXES, app_metadata, trials_metadata
from tri_al.testing.fixtures import minimal_trial

DIALECT = sqlite_dialect.dialect()


def open_trials(path: Path) -> None:
    SQLiteStorage.open(path).close()


def open_app(path: Path) -> None:
    open_app_db(path).dispose()


DATABASES = [
    pytest.param(open_trials, trials_metadata, {"trials_fts", "names_fts"}, id="trials"),
    pytest.param(open_app, app_metadata, set(), id="app"),
]


def describe_database(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    def pragma(name: str, arg: str = table) -> list[Any]:
        return conn.execute(f"PRAGMA {name}('{arg}')").fetchall()

    indexes = pragma("index_list")
    return {
        "columns": [
            (name, type_, notnull, default, pk)
            for _, name, type_, notnull, default, pk in pragma("table_info")
        ],
        "with_rowid": not pragma("table_list")[0][4],  # wr: WITHOUT ROWID
        "foreign_keys": sorted(
            (row[2], row[3], row[4], row[6]) for row in pragma("foreign_key_list")
        ),
        "unique": sorted(
            tuple(column[2] for column in pragma("index_info", name))
            for _, name, _, origin, _ in indexes
            if origin == "u"
        ),
        "indexes": sorted(
            (
                name,
                bool(unique),
                tuple(column[2] for column in pragma("index_info", name)),
                bool(partial),
            )
            for _, name, unique, origin, partial in indexes
            if origin == "c"
        ),
    }


def describe_table(table: Table) -> dict[str, Any]:
    primary_key = list(table.primary_key.columns)

    def default(column: Any) -> str | None:
        if column.server_default is None:
            return None
        arg = column.server_default.arg
        return arg.text if isinstance(arg, TextClause) else repr(arg)

    return {
        "columns": [
            (
                column.name,
                column.type.compile(dialect=DIALECT),
                int(not column.nullable),
                default(column),
                primary_key.index(column) + 1 if column in primary_key else 0,
            )
            for column in table.columns
        ],
        "with_rowid": table.dialect_options["sqlite"]["with_rowid"],
        "foreign_keys": sorted(
            (fk.column.table.name, fk.parent.name, fk.column.name, fk.ondelete or "NO ACTION")
            for fk in table.foreign_keys
        ),
        "unique": sorted(
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        ),
        "indexes": sorted(
            (
                str(index.name),
                index.unique,
                tuple(column.name for column in index.columns),
                index.dialect_options["sqlite"]["where"] is not None,
            )
            for index in table.indexes
        ),
    }


@pytest.mark.parametrize(("open_db", "metadata", "virtual"), DATABASES)
def test_migrations_create_exactly_the_tables(
    tmp_path: Path, open_db: Callable[[Path], None], metadata: MetaData, virtual: set[str]
) -> None:
    path = tmp_path / "test.db"
    open_db(path)

    conn = sqlite3.connect(path)
    try:
        names = {
            name
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                " AND name NOT LIKE '%fts_%'"
            )
        }
        assert names == {*metadata.tables, "_migrations", *virtual}
        for table in metadata.tables.values():
            assert describe_database(conn, table.name) == describe_table(table), table.name
    finally:
        conn.close()


def test_link_tables_have_reverse_indexes() -> None:
    reverse = {str(index.name): [c.name for c in index.columns] for index in DEFERRED_INDEXES}

    assert reverse["trial_conditions_by_condition"] == ["condition_id", "trial_id"]
    assert reverse["trial_sponsors_by_sponsor"] == ["sponsor_id", "trial_id"]
    assert all(not index.unique for index in DEFERRED_INDEXES)


def test_record_derived_fields() -> None:
    record = replace(
        minimal_trial(),
        sponsors=[Sponsor("A", "collaborator"), Sponsor("B", "lead", "NIH"), Sponsor("C", "lead")],
        locations=[Location(country_code="US"), Location(country_code="US")],
    )

    assert record.lead_sponsor == Sponsor("B", "lead", "NIH")
    assert record.num_sites == 2
    assert minimal_trial().lead_sponsor is None
    assert minimal_trial().location_scope is None


@pytest.mark.parametrize(
    ("countries", "scope"), [(["US"], "US"), (["DE", "FR"], "NON_US"), (["FR", "US"], "BOTH")]
)
def test_location_scope(countries: list[str], scope: str) -> None:
    assert replace(minimal_trial(), countries=countries).location_scope == scope
