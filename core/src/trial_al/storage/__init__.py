"""Storage: the contract, the SQLite backend, migrations and the extension hook (design §5.2)."""

from trial_al.storage.app_db import open_app_db
from trial_al.storage.base import (
    BulkLoader,
    NameHit,
    NameKind,
    SearchHit,
    Storage,
    StorageError,
    StorageTransaction,
    TrialQuery,
    TrialSummary,
)
from trial_al.storage.engine import (
    MIN_SQLITE_VERSION,
    ExtensionLoadError,
    SqliteExtension,
    can_load_extensions,
    check_sqlite_version,
    create_engine,
    load_extension,
)
from trial_al.storage.migrations import Migration, MigrationError, migrate, run_script
from trial_al.storage.sqlite import SQLiteStorage

__all__ = [
    "MIN_SQLITE_VERSION",
    "BulkLoader",
    "ExtensionLoadError",
    "Migration",
    "MigrationError",
    "NameHit",
    "NameKind",
    "SQLiteStorage",
    "SearchHit",
    "SqliteExtension",
    "Storage",
    "StorageError",
    "StorageTransaction",
    "TrialQuery",
    "TrialSummary",
    "can_load_extensions",
    "check_sqlite_version",
    "create_engine",
    "load_extension",
    "migrate",
    "open_app_db",
    "run_script",
]
