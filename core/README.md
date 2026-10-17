# tri-al

The core of Tri-AL v2: the trial record, SQLite storage with migrations and full-text search,
the plugin loader, config, and the `tri-al` CLI. See [docs/design.md](../docs/design.md)
for the design and milestones.

Development, from the repository root:

```bash
uv sync
uv run tri-al plugins list
uv run tri-al doctor
uv run pytest
uv run ruff check && uv run ruff format --check
uv run mypy
```
