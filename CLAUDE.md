# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Tri-AL mirrors ClinicalTrials.gov into SQLite and lets you explore it in a local dashboard; the domain focus is Alzheimer's trials. The repository holds two versions:

- **v2** (branch `v2`, in progress): a rewrite as a uv workspace in `core/` and `plugins/`, with FastAPI and a React front end still to come. **[docs/design.md](docs/design.md) is the source of truth:** decisions in §15, milestones in §14, speed targets in §10. Milestones 1 (skeleton), 2 (schema and storage), 3 (ClinicalTrials.gov plugin and pipeline) and 4 (jobs, stats and API) are built; 5 (the React front end) is next.
- **v1** (`main`, and still at the repository root on `v2`): the Django 3.2 app described [below](#v1-django). Don't delete or move v1 files; v2 tooling ignores them.

## v2: setup and commands

uv manages Python 3.13 (`.python-version`; `python-preference = "only-managed"`). Run everything from the repository root:

```bash
uv sync                                     # create .venv with core, plugins and dev tools
uv run pytest                               # all tests (core/tests, plugins/*/tests)
uv run pytest core/tests/test_migrations.py # one file
uv run pytest "core/tests/test_storage_sqlite.py::TestSQLiteStorageContract::test_search_follows_updates"
uv run pytest -k search                     # tests whose names match
uv run pytest -m live                       # opt-in tests against the real ClinicalTrials.gov API
uv run ruff check && uv run ruff format --check
uv run mypy                                 # strict; core, plugins and bench
uv run tri-al --help                      # the CLI; also `plugins list|enable|disable`, `doctor`
uv run tri-al install                     # download ~2.8 GB, build data/trials.db (~9 GB, ~15 min)
uv run tri-al install --from-file ctg-studies.json.zip   # or from a downloaded zip
uv run tri-al update                      # fetch studies changed since the last update
uv run tri-al serve                       # API on 127.0.0.1:8000 (docs at /api/docs) + job worker
uv run tri-al worker                      # the job worker alone
uv run python bench/api_bench.py            # §10 API targets on data/trials.db; results in bench/README.md
uv run python bench/storage_bench.py        # storage benchmark; results in bench/README.md
uv run python bench/db_report.py data/trials.db   # database size by table
```

pytest runs with `filterwarnings = error` and `--import-mode=importlib`: an unclosed SQLite connection raises a `ResourceWarning` and fails the test, so close storages and `dispose()` engines (and `StatsEngine.close()`, which waits for an index being built). API tests use Starlette's `TestClient` (it needs `httpx2`, a dev dependency); it waits for whole responses, so event-stream tests run the app in a real uvicorn server (`running()` in `core/tests/test_api.py`). CI is `.github/workflows/v2.yml` (lint, format, mypy, pytest, a CLI smoke test).

## v2 architecture

**Layout.** `core/` is the `tri-al` package (`core/src/tri_al/`): `schema` (`TrialRecord`, `labels`), `filters.py` (`TrialFilter`), `storage`, `pipeline`, `jobs`, `stats`, `search.py`, `access`, `api`, `plugins`, `config`, `cli`, `doctor.py`, and `testing` (contract suites and `FakeSource`, which plugins reuse). `plugins/ctgov/` is the ClinicalTrials.gov source; `plugins/charts/` holds the default dashboard charts (specs only; the front end draws them); `plugins/sample/` is an example plugin. `bench/` holds benchmarks. The root `pyproject.toml` is a virtual workspace and holds the ruff, mypy and pytest config; ruff excludes `docs/` and the v1 paths.

**Plugins** (`tri_al.plugins`). Each plugin is a package with an entry point in the `tri_al.plugins` group that points at a `Plugin` instance. Its `register(registry)` gets a per-plugin `Registry`. Implemented: `add_cli`, `add_sqlite_extension`, `add_migrations`, `add_source`, `on` (pipeline events), `add_chart`, `add_filter_field`, `add_search_provider`, `add_routes` (mounted at `/api/x/<plugin>/`), `add_job` and `set_access_policy`; `add_enricher` raises `NotImplementedError` until enrichers exist. Installed plugins are enabled by default. Enabled state and settings live in `tri-al.toml`, never in a database.

**Config** (`tri_al.config`). It reads `$TRI_AL_CONFIG` or `./tri-al.toml` (a missing file means defaults). `TRI_AL_*` variables override it, with `__` between nested keys (`TRI_AL_SERVER__PORT`). Unknown keys are errors.

**Storage** (`tri_al.storage`, design §5.2 and §6):
- `Storage` (`storage/base.py`) is the contract. `SQLiteStorage` (`storage/sqlite.py`) implements it with SQLAlchemy Core, no ORM. There are two files: `trials.db` (source data, written only by the pipeline) and `app.db` (`open_app_db`: jobs, enricher state).
- `storage/engine.py` sets the PRAGMAs and loads plugin extensions on every connection. It also emits `BEGIN` itself through SQLAlchemy's `begin` event, so write transactions can use `BEGIN IMMEDIATE` (the `tri_al_begin` execution option).
- Schema changes need a **new migration**, with matching changes in two places: the frozen SQL in `storage/core_migrations.py` and the `Table` definitions in `storage/tables.py`. `tests/test_schema.py` fails if the two differ. Never edit a released migration. The runner (`storage/migrations.py`) tracks `_migrations(component, version)` per component: the core and each plugin.
- `trials_fts` is a **contentless** FTS5 table (`contentless_delete=1`, migration 3): it can't be rebuilt or read back, so the writer in `sqlite.py` feeds it each trial's text as it writes (`_fts_row`) and deletes a trial's row by rowid before replacing it, in bulk loads too. Write trials only through the writer. `INSERT INTO trials_fts (trials_fts) VALUES ('integrity-check')` checks only its structure. Snippets come from the hits' text in a per-thread in-memory FTS5 table (`_Snippets`). Search ranks at most `SEARCH_CANDIDATES` (20,000) of the newest matches.
- `trial_text.text` is the trial's summary, description, eligibility and outcomes packed as JSON (`docs.TrialText`) and zstd-compressed against a `doc_dicts` dictionary of kind `text`; `trial_outcomes` is gone.
- Reads that must agree (an API request) use `SQLiteStorage.read()`, a reader in one read transaction. API workers open `trials.db` with `SQLiteStorage.attach` (no migrations); `serve` migrates first.
- `bulk_load()` drops the secondary indexes (`tables.DEFERRED_INDEXES`) and `names_fts`, then rebuilds them and optimizes `trials_fts` when it finishes. If it doesn't finish, `meta.bulk_load_started` blocks ordinary writes.
- `trial_docs.doc` is the raw JSON compressed with zstd (`storage/docs.py`; `backports.zstd` on 3.13), against the dictionary in `doc_dicts` that `dict_id` names. It's no longer JSONB, so SQL JSON functions can't read it.
- SQLAlchemy 2.1: don't call `dict(result)`, because a `Result` has `keys()`; use `dict(result.all())`. `Result.tuples()` is deprecated.

**Pipeline** (`tri_al.pipeline`, design §5.3 and §8): `Pipeline.from_plugins(config, loaded)` then `run_install(progress, from_file=, force=)` or `run_update(progress)`. Install builds `trials.db.new` in bulk-load mode (parse, hash and normalize in a spawned process pool; one writer), checks it and renames it over `trials.db`; stages are checkpointed in `runs`, so a re-run resumes. Update fetches since `cursor.<source> − 1 day` and writes everything, including `trial_changes`, in one `BEGIN IMMEDIATE` transaction. Skipping unchanged studies relies on `content_hash` (BLAKE2b of `Source.hashable(raw)` with sorted keys). Code that runs an install with workers must sit under `if __name__ == "__main__":` (spawn re-imports the main module).

**Jobs** (`tri_al.jobs`, design §5.4): `JobQueue` over `app.db` (`enqueue`, `claim` with `UPDATE … RETURNING`, `start` for shell commands, `report`, `cancel`, `recover`). Only one install/update/rebuild is queued or running at a time (`JobConflict`). `JobProgress` is the pipeline's progress callback: at most one write every 0.5 s plus a heartbeat thread. `Worker` runs jobs one at a time, recovers stale ones and queues scheduled updates (`config/schedule.py`). `tri-al install`/`update` record themselves as jobs.

**Stats** (`tri_al.stats`, design §5.5): charts and facets are written against `Counts`; `SqlCounts` (SQLite) serves the pipeline's precompute into `stats`, and `IndexCounts` serves filtered API requests from `TrialIndex`, numpy arrays of every trial built per data version in each API worker. The two must agree exactly; `core/tests/test_stats.py` compares them over many filters and every sort. `StatsEngine` holds the index, the byte-bounded LRU cache keyed by data version, and trial pages. `TrialFilter` becomes SQL in `storage/filtering.py`.

**API** (`tri_al.api`, design §5.9): `create_app(config, loaded)`; state in `ApiState`. Handlers return orjson bytes (`JSONBytes`) with weak ETags from the data version (`data_json`, `not_modified`) and declare Pydantic `response_model`s only for the OpenAPI schema, so tests validate responses against the models. `/api/events` polls `app.db` and `trials.db` every 0.5 s while anyone listens. Every route depends on `tri_al.access.require(action)`; `BrowserProtection` checks Host on every request and `X-Tri-AL` plus Origin on changing ones, so tests send `X-Tri-AL: 1` and use `base_url="http://127.0.0.1:8000"`.

**ctgov plugin** (`plugins/ctgov`): `CtgovSource` downloads `ctg-studies.json.zip` into `data/downloads/` (no Range support, so no resumed downloads) and reads it without extracting; updates page `/api/v2/studies` with `pageSize=1000`. `normalize.py` maps API v2 JSON to `TrialRecord`; `countries.py` maps all 226 API country names. Tests run offline against real study fixtures and recorded pages in `tests/fixtures/`.

**Contract tests.** A backend passes `tri_al.testing.StorageContract` by subclassing it in a test module and overriding the `storage` fixture (see `core/tests/test_storage_sqlite.py`); a source passes `tri_al.testing.SourceContract` the same way (see `plugins/ctgov/tests/test_source.py`). The fixtures are in `tri_al.testing.fixtures`.

**`doctor`** (`tri_al/doctor.py`) checks the Python and SQLite versions (SQLite ≥ 3.45), FTS5, extension loading, config, plugins, plugin extensions, whether the server listens beyond this machine without an access plugin, and database state. When a fix is needed, it suggests `uv python install`.

## v1 (Django)

Django 3.2 on `main`: it mirrors ClinicalTrials.gov into `db.sqlite3` and shows it in a customized Django admin with Plotly charts. A REST API under `/api/` served a separate front end (`alzwb-front-end`, listed in `.gitmodules` but never committed).

- **Setup:** `visual/settings.py` reads `visual/config.yml` at import, so every command fails until you run `cp visual/sample-config.yml visual/config.yml` and `mkdir -p data/cache/plot staticfiles`. Use Python 3.9 or 3.10 (`import imp`, pinned numpy/pandas). Install with `pip install -r requirements.txt`.
- **Commands:** `python manage.py runserver` (dashboard at `/admin`) and `python manage.py test` (`panels/tests.py` is empty). `./initdb.sh` is destructive: it regenerates migrations and runs `createsuperuser`. On an existing checkout, use `manage.py migrate` and `loaddata panels/fixtures/Country.json`. `data_manager.py` actions: `import -i data/AllPublicXML`, `update`, `export`, `cleardata`, `terminal`, `manual`.
- **Ingestion:**
  - Bulk XML import goes through `XMLFastParser`, then `processor.build_columns`, then `processor.data_mapper`.
  - Incremental updates go through `downloader`, then `processor.generate_data` (20 threads, `FullStudyParser`), then `build_objects`. That step sends new trials to `data_mapper` and existing ones to `TrialComparator`.
  - All parsers return one nested dict shape that `data_mapper` and `TrialComparator` index into directly.
  - **`update` is broken:** its ClinicalTrials.gov endpoints are retired (checked 2026-10-17). Bulk import still works through `/api/legacy/public-xml`.
- **Code:**
  - `panels/` is the only app.
  - Choice fields store short codes; map them with `Trial.get_char`, `get_display` and `Agent.get_type_choice`.
  - The admin is `my_site` (`MyAdminSite` in `panels/admin.py`), not `admin.site`.
  - Charts are pickled to `data/cache/plot/`, and the admin index crashes if that directory is missing.
  - `panels/utils/customize.py` `@column` functions inject fields into `Trial`.
  - `/api/publication/` raises `NameError`.
- **Deploy:** `.github/workflows/deploy.yml` runs on a self-hosted runner for pushes and PRs to `main`: pip install, collectstatic, makemigrations, migrate, test. Cron runs `schedulers/update-db.sh`.
