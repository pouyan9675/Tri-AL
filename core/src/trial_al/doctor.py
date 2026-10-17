"""Checks that this install can run (docs/design.md §5.10), used by ``trial-al doctor``."""

import sqlite3
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from trial_al.config import Config, ConfigError, config_path, load_config
from trial_al.plugins import LoadedPlugins, PluginLoadError, load_plugins
from trial_al.storage import (
    MIN_SQLITE_VERSION,
    ExtensionLoadError,
    Migration,
    SqliteExtension,
    StorageError,
    can_load_extensions,
    check_sqlite_version,
    load_extension,
)
from trial_al.storage.core_migrations import APP_MIGRATIONS, COMPONENT, TRIALS_MIGRATIONS
from trial_al.storage.engine import UV_PYTHON_FIX
from trial_al.storage.migrations import current_version
from trial_al.storage.sqlite import BULK_LOAD_KEY

type Status = Literal["ok", "warn", "fail"]


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: Status
    detail: str
    fix: str | None = None


def run_checks() -> list[Check]:
    """Every check, in order. Checks that need config or plugins are skipped if those fail."""
    checks = [check_python(), check_sqlite(), check_full_text_search(), check_extension_support()]
    try:
        config = load_config()
    except ConfigError as exc:
        fix = "fix the file, or the TRIAL_AL_* variable named above"
        return [*checks, Check("config", "fail", str(exc), fix)]
    path = config_path()
    found = "" if path.exists() else " (not found, so defaults apply)"
    checks.append(Check("config", "ok", f"{path}{found}"))

    loaded: LoadedPlugins | None = None
    try:
        loaded = load_plugins(config)
    except PluginLoadError as exc:
        fix = "fix the plugins, or turn them off with `trial-al plugins disable <name>`"
        checks.append(Check("plugins", "fail", "; ".join(exc.problems), fix))
    else:
        names = ", ".join(plugin.name for plugin in loaded.plugins)
        enabled = f"{len(loaded.plugins)} enabled" + (f" ({names})" if names else "")
        checks.append(Check("plugins", "ok", enabled))
        checks += check_extensions(loaded.contributions.sqlite_extensions.values())
    checks += check_databases(config, loaded)
    return checks


def check_python() -> Check:
    version = ".".join(map(str, sys.version_info[:3]))
    return Check("Python", "ok", f"{version} ({sys.executable})")


def check_sqlite(version: tuple[int, int, int] | None = None) -> Check:
    version = sqlite3.sqlite_version_info if version is None else version
    found = ".".join(map(str, version))
    needed = ".".join(map(str, MIN_SQLITE_VERSION[:2]))
    try:
        check_sqlite_version(version)
    except StorageError:
        return Check("SQLite", "fail", f"{found}, but trial-al needs {needed} or newer", _fix())
    return Check("SQLite", "ok", f"{found} (needs {needed} or newer)")


def check_full_text_search() -> Check:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE a USING fts5(x, tokenize = 'porter unicode61')")
        conn.execute(
            "CREATE VIRTUAL TABLE b USING fts5(x, tokenize = 'trigram remove_diacritics 1')"
        )
    except sqlite3.Error as exc:
        return Check("full-text search", "fail", f"SQLite's FTS5 isn't usable: {exc}", _fix())
    finally:
        conn.close()
    return Check("full-text search", "ok", "FTS5 with the porter and trigram tokenizers")


def check_extension_support(
    connect: Callable[[str], sqlite3.Connection] = sqlite3.connect,
) -> Check:
    if not can_load_extensions(connect):
        return Check(
            "extension loading",
            "fail",
            "this Python's sqlite3 module can't load extensions",
            _fix(),
        )
    return Check("extension loading", "ok", "supported")


def check_extensions(extensions: Iterable[SqliteExtension]) -> list[Check]:
    checks = []
    for extension in extensions:
        name = f"extension {extension.name}"
        conn = sqlite3.connect(":memory:")
        try:
            load_extension(conn, extension)
        except ExtensionLoadError as exc:
            checks.append(Check(name, "fail", str(exc)))
        else:
            checks.append(Check(name, "ok", f"loads (from plugin {extension.plugin})"))
        finally:
            conn.close()
    return checks


def check_databases(config: Config, loaded: LoadedPlugins | None) -> list[Check]:
    def plugin_migrations(database: Literal["trials", "app"]) -> dict[str, tuple[Migration, ...]]:
        return {} if loaded is None else loaded.contributions.migrations_for(database)

    return [
        check_database(
            "trials.db",
            config.data.trials_db,
            {COMPONENT: TRIALS_MIGRATIONS, **plugin_migrations("trials")},
        ),
        check_database(
            "app.db", config.data.app_db, {COMPONENT: APP_MIGRATIONS, **plugin_migrations("app")}
        ),
    ]


def check_database(name: str, path: Path, components: dict[str, Sequence[Migration]]) -> Check:
    if not path.exists():
        return Check(name, "ok", f"{path} doesn't exist yet; `trial-al install` creates it")
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return Check(name, "fail", f"{path} can't be opened: {exc}")
    try:
        versions = {component: current_version(conn, component) for component in components}
        unfinished = _bulk_load_started(conn)
    except sqlite3.Error as exc:
        return Check(name, "fail", f"{path} can't be read: {exc}")
    finally:
        conn.close()

    newer = [c for c, version in versions.items() if version > len(components[c])]
    if newer:
        return Check(
            name,
            "fail",
            f"{path} was migrated by a newer version of {', '.join(newer)}",
            "upgrade trial-al and its plugins",
        )
    if unfinished is not None:
        return Check(
            name,
            "warn",
            f"{path}: a bulk load started at {unfinished} didn't finish",
            "run `trial-al rebuild`",
        )
    pending = sum(len(components[c]) - version for c, version in versions.items())
    if pending:
        noun = "migration" if pending == 1 else "migrations"
        return Check(name, "warn", f"{path}: {pending} {noun} will run at the next start")
    return Check(name, "ok", f"{path}, schema up to date")


def _bulk_load_started(conn: sqlite3.Connection) -> str | None:
    if conn.execute("SELECT 1 FROM sqlite_schema WHERE name = 'meta'").fetchone() is None:
        return None
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (BULK_LOAD_KEY,)).fetchone()
    return None if row is None else str(row[0])


def _fix() -> str:
    return UV_PYTHON_FIX[0].upper() + UV_PYTHON_FIX[1:]
