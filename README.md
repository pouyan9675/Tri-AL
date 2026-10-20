# Tri-AL: VisuAL ClinicAL TriALs

Tri-AL keeps a local copy of every study on [ClinicalTrials.gov](https://clinicaltrials.gov) (about 607,000) in SQLite. You explore it in your browser with a dashboard, a trial explorer, full-text and field-by-field search, analyses of conditions, interventions and posted results, and AI annotation of trial text using a model you run yourself. It's built for Alzheimer's research, but it works for any condition.

This is v2, a rewrite that is still in progress. v1, the Django app, is on the `main` branch.

## Run it from a checkout

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 for you) and Node 22 to build the front end. Run everything from the repository root:

```bash
uv sync
npm --prefix web ci
npm --prefix web run build
uv run tri-al install             # downloads about 2.8 GB and builds data/trials.db (about 15 min)
uv run tri-al embeddings generate # trial vectors for the cluster map and analyses (a few minutes)
uv run tri-al serve               # http://127.0.0.1:8000
```

The server keeps the data current with a daily update, and **Settings → Update** runs one at any time. AI annotation is optional: point it at an OpenAI-compatible server such as LM Studio under **Settings → AI**.

## Documentation

- [docs/design.md](docs/design.md): the design and the decisions behind it.
- [CLAUDE.md](CLAUDE.md): commands, tests and architecture for development.
