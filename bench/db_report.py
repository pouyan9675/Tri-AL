"""Size of a Tri-AL database by table, from SQLite's ``dbstat`` (indexes count with their table).

uv run python bench/db_report.py data/trials.db
"""

import argparse
import sqlite3
from pathlib import Path


def table_sizes(path: Path) -> list[tuple[str, int, int]]:
    """``(table, bytes, rows)``, largest first. Full-text shadow tables count as their index."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        owner = dict(conn.execute("SELECT name, tbl_name FROM sqlite_schema WHERE type = 'index'"))
        sizes: dict[str, int] = {}
        for name, size in conn.execute("SELECT name, sum(pgsize) FROM dbstat GROUP BY name"):
            table = owner.get(name, name)
            for fts in ("trials_fts", "names_fts"):
                if table.startswith(f"{fts}_"):
                    table = fts
            sizes[table] = sizes.get(table, 0) + size
        tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_schema")}
        rows = {
            table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for table in sizes
            if table in tables and not table.startswith("sqlite_")
        }
    finally:
        conn.close()
    return sorted(
        ((table, size, rows.get(table, 0)) for table, size in sizes.items()),
        key=lambda item: -item[1],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    sizes = table_sizes(args.database)
    total = sum(size for _, size, _ in sizes)
    print("| Table | Size | Share | Rows |")
    print("|---|---:|---:|---:|")
    for table, size, rows in sizes:
        print(f"| `{table}` | {size / 1e6:,.1f} MB | {size / total:.1%} | {rows:,} |")
    print(f"| **Total** | **{total / 1e6:,.1f} MB** | | |")
    print(f"\nFile: {args.database.stat().st_size / 1e6:,.1f} MB")


if __name__ == "__main__":
    main()
