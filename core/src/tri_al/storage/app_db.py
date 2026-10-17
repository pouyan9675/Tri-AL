"""``app.db``: the state the app changes, such as jobs (docs/design.md §3 and §6)."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlalchemy import Engine

from tri_al.storage.core_migrations import APP_MIGRATIONS
from tri_al.storage.engine import SqliteExtension, create_engine
from tri_al.storage.migrations import Migration, migrate
from tri_al.storage.sqlite import components


def open_app_db(
    path: Path,
    *,
    extensions: Sequence[SqliteExtension] = (),
    plugin_migrations: Mapping[str, Sequence[Migration]] | None = None,
) -> Engine:
    """Open (or create) ``app.db`` at ``path`` and apply pending migrations."""
    engine = create_engine(path, extensions=extensions)
    try:
        migrate(engine, components(APP_MIGRATIONS, plugin_migrations))
    except BaseException:
        engine.dispose()
        raise
    return engine
