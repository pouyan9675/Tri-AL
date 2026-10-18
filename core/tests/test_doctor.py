from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from typer.testing import CliRunner, Result

from tri_al import doctor
from tri_al.cli import create_app
from tri_al.plugins import Registry
from tri_al.storage import Migration, SQLiteStorage, open_app_db
from tri_al.storage.core_migrations import TRIALS_MIGRATIONS

if TYPE_CHECKING:
    from conftest import Install, MakePlugin

runner = CliRunner(env={"COLUMNS": "200"})


def run_doctor() -> Result:
    return runner.invoke(create_app(), ["doctor"])


def lines(result: Result) -> dict[str, str]:
    """``{check name: "status  detail"}``, from the doctor's output."""
    found = {}
    for line in result.stdout.splitlines():
        if match := re.fullmatch(r"(ok|warn|fail) +(.+?): (.*)", line):
            status, name, detail = match.groups()
            found[name] = f"{status}  {detail}"
    return found


def fixes(result: Result) -> list[str]:
    return [
        line.strip().removeprefix("fix: ") for line in result.stdout.splitlines() if "fix:" in line
    ]


def test_passes_on_a_working_install(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("alpha"))

    result = run_doctor()

    assert result.exit_code == 0, result.output
    checks = lines(result)
    assert list(checks) == [
        "Python",
        "SQLite",
        "full-text search",
        "extension loading",
        "config",
        "plugins",
        "server",
        "trials.db",
        "app.db",
    ]
    assert checks["SQLite"].startswith(f"ok  {sqlite3.sqlite_version} (needs 3.45 or newer)")
    assert checks["plugins"] == "ok  1 enabled (alpha)"
    assert (
        checks["trials.db"] == "ok  data/trials.db doesn't exist yet; `tri-al install` creates it"
    )
    assert result.stdout.endswith("All checks passed.\n")


def test_fails_on_old_sqlite(install: Install, monkeypatch: pytest.MonkeyPatch) -> None:
    install()
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 37, 2))

    result = run_doctor()

    assert result.exit_code == 1
    assert lines(result)["SQLite"] == "fail  3.37.2, but tri-al needs 3.45 or newer"
    assert "uv python install 3.13" in fixes(result)[0]
    assert result.stderr == "\n1 check failed.\n"


def test_fails_when_python_cannot_load_extensions(
    install: Install, monkeypatch: pytest.MonkeyPatch
) -> None:
    install()
    monkeypatch.setattr(doctor, "can_load_extensions", lambda connect: False)

    result = run_doctor()

    assert result.exit_code == 1
    assert lines(result)["extension loading"] == (
        "fail  this Python's sqlite3 module can't load extensions"
    )
    assert fixes(result)[0].startswith(
        "Use a Python built by uv, which can: run `uv python install"
    )


def test_checks_plugin_extensions(install: Install, make_plugin: MakePlugin) -> None:
    def broken(conn: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("no such file: vec0")

    def register_good(registry: Registry) -> None:
        registry.add_sqlite_extension("hello", lambda conn: None)

    def register_broken(registry: Registry) -> None:
        registry.add_sqlite_extension("vec0", broken)

    install(
        make_plugin("good", register=register_good),
        make_plugin("vectors", register=register_broken),
    )

    result = run_doctor()

    assert result.exit_code == 1
    checks = lines(result)
    assert checks["extension hello"] == "ok  loads (from plugin good)"
    assert checks["extension vec0"].startswith(
        "fail  SQLite extension 'vec0' from plugin 'vectors' failed to load: no such file: vec0"
    )


def test_fails_when_plugins_do_not_load(install: Install, make_plugin: MakePlugin) -> None:
    install(make_plugin("alpha", api_version=99))

    result = run_doctor()

    assert result.exit_code == 1
    assert lines(result)["plugins"].startswith("fail  alpha: written for plugin API 99")


def test_fails_on_bad_config(install: Install) -> None:
    install()
    Path("tri-al.toml").write_text("[data]\ndri = 'x'\n")

    result = run_doctor()

    assert result.exit_code == 1
    assert lines(result)["config"] == "fail  invalid config (tri-al.toml):"
    assert "\n        data.dri: Extra inputs are not permitted\n" in result.stdout
    assert "trials.db" not in lines(result)


def test_reports_database_state(install: Install, make_plugin: MakePlugin) -> None:
    SQLiteStorage.open(Path("data/trials.db")).close()
    open_app_db(Path("data/app.db")).dispose()

    def register(registry: Registry) -> None:
        registry.add_migrations("app", [Migration(1, "notes", "CREATE TABLE notes_x (x);")])

    install(make_plugin("notes", register=register))

    result = run_doctor()

    assert result.exit_code == 0
    checks = lines(result)
    assert checks["trials.db"] == "ok  data/trials.db, schema up to date"
    assert checks["app.db"] == "warn  data/app.db: 1 migration will run at the next start"


def test_fails_on_a_database_from_a_newer_version(install: Install) -> None:
    install()
    with SQLiteStorage.open(Path("data/trials.db")) as storage, storage.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO _migrations VALUES ('core', :v, 'from the future', '2030-01-01')"),
            {"v": len(TRIALS_MIGRATIONS) + 1},
        )

    result = run_doctor()

    assert result.exit_code == 1
    assert (
        lines(result)["trials.db"] == "fail  data/trials.db was migrated by a newer version of core"
    )


def test_warns_about_an_unfinished_bulk_load(install: Install) -> None:
    install()
    with (
        SQLiteStorage.open(Path("data/trials.db")) as storage,
        pytest.raises(RuntimeError),
        storage.bulk_load(),
    ):
        raise RuntimeError

    result = run_doctor()

    assert result.exit_code == 0
    assert "didn't finish" in lines(result)["trials.db"]
    assert fixes(result) == ["run `tri-al rebuild`"]


def test_warns_when_the_server_listens_beyond_this_machine(
    install: Install, make_plugin: MakePlugin
) -> None:
    install(make_plugin("alpha"))
    Path("tri-al.toml").write_text('[server]\nhost = "0.0.0.0"\n')

    result = run_doctor()

    assert result.exit_code == 0, result.output
    assert lines(result)["server"].startswith("warn  the server listens on 0.0.0.0")
    assert 'set server.host = "127.0.0.1" in tri-al.toml' in fixes(result)


def test_an_access_plugin_silences_the_server_warning(
    install: Install, make_plugin: MakePlugin
) -> None:
    class Everyone:
        def allows(self, request: object, action: str) -> bool:
            return True

    def register(registry: Registry) -> None:
        registry.set_access_policy(Everyone())

    install(make_plugin("auth", register=register))
    Path("tri-al.toml").write_text('[server]\nhost = "0.0.0.0"\n')

    assert lines(run_doctor())["server"] == "ok  0.0.0.0:8000, with an access policy"
