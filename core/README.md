# trial-al

The core of Tri-AL v2: plugin loader, config and the `trial-al` CLI. See
[docs/design.md](../docs/design.md) for the design and milestones.

Development, from the repository root:

```bash
uv sync
uv run trial-al plugins list
uv run pytest
uv run ruff check && uv run ruff format --check
uv run mypy
```
