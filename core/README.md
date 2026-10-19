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

## Trial embeddings

Tri-AL keeps one vector per trial in `trial_embeddings` (design §12): the title, official
title, conditions, interventions and brief summary, read by
`sentence-transformers/all-MiniLM-L6-v2` up to 64 tokens in float16 on a GPU, stored as
float16. Each update embeds its new and changed trials; an install leaves them to

```bash
uv run tri-al embeddings generate      # the trials without a current vector, newest first
uv run tri-al embeddings generate --force   # every trial again
```

It runs as a data job (no install or update at the same time), takes about 4 minutes for
607k trials on Apple Silicon, and carries on where it stopped. The first run downloads the
model (87 MB). Settings, in `tri-al.toml`:

```toml
[embeddings]
enabled = true
model = "sentence-transformers/all-MiniLM-L6-v2"
max_tokens = 64       # input the model reads
float16 = true        # on a GPU; a CPU uses float32
batch_size = 256
# device = "mps"      # or "cuda" / "cpu"; default: the best there is
```

Changing the model makes every vector stale; run the command again. Cross-encoders such as
`cross-encoder/ms-marco-TinyBERT-L2-v2` are refused: they score query and document pairs and
make no vectors to store.
