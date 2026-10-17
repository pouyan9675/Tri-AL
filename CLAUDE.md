# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Tri-AL mirrors ClinicalTrials.gov into SQLite and lets you explore it in a local dashboard; the domain focus is Alzheimer's trials. The repository holds two versions:

- **v2** (branch `v2`, in progress): a rewrite as a uv workspace in `core/` and `plugins/`, with FastAPI and a React front end still to come. **[docs/design.md](docs/design.md) is the source of truth:** decisions in §15, milestones in §14, speed targets in §10. Milestones 1 (skeleton), 2 (schema and storage) and 3 (ClinicalTrials.gov plugin and pipeline) are built.
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
uv run trial-al --help                      # the CLI; also `plugins list|enable|disable`, `doctor`
uv run trial-al install                     # download ~2.8 GB, build data/trials.db (~9 GB, ~15 min)
uv run trial-al install --from-file ctg-studies.json.zip   # or from a downloaded zip
uv run trial-al update                      # fetch studies changed since the last update
uv run python bench/storage_bench.py        # storage benchmark; results in bench/README.md
uv run python bench/db_report.py data/trials.db   # database size by table
```

pytest runs with `filterwarnings = error` and `--import-mode=importlib`: an unclosed SQLite connection raises a `ResourceWarning` and fails the test, so close storages and `dispose()` engines. CI is `.github/workflows/v2.yml` (lint, format, mypy, pytest, a CLI smoke test).

## v2 architecture

**Layout.** `core/` is the `trial-al` package (`core/src/trial_al/`): `schema` (`TrialRecord`), `storage`, `pipeline`, `plugins`, `config`, `cli`, `doctor.py`, and `testing` (contract suites and `FakeSource`, which plugins reuse). `plugins/ctgov/` is the ClinicalTrials.gov source; `plugins/sample/` is an example plugin. `bench/` holds benchmarks. The root `pyproject.toml` is a virtual workspace and holds the ruff, mypy and pytest config; ruff excludes `docs/` and the v1 paths.

**Plugins** (`trial_al.plugins`). Each plugin is a package with an entry point in the `trial_al.plugins` group that points at a `Plugin` instance. Its `register(registry)` gets a per-plugin `Registry`. Implemented so far: `add_cli`, `add_sqlite_extension`, `add_migrations`, `add_source`, `on` (pipeline events); the other methods raise `NotImplementedError` until their milestone. Installed plugins are enabled by default. Enabled state and settings live in `trial-al.toml`, never in a database.

**Config** (`trial_al.config`). It reads `$TRIAL_AL_CONFIG` or `./trial-al.toml` (a missing file means defaults). `TRIAL_AL_*` variables override it, with `__` between nested keys (`TRIAL_AL_SERVER__PORT`). Unknown keys are errors.

**Storage** (`trial_al.storage`, design §5.2 and §6):
- `Storage` (`storage/base.py`) is the contract. `SQLiteStorage` (`storage/sqlite.py`) implements it with SQLAlchemy Core, no ORM. There are two files: `trials.db` (source data, written only by the pipeline) and `app.db` (`open_app_db`: jobs, enricher state).
- `storage/engine.py` sets the PRAGMAs and loads plugin extensions on every connection. It also emits `BEGIN` itself through SQLAlchemy's `begin` event, so write transactions can use `BEGIN IMMEDIATE` (the `trial_al_begin` execution option).
- Schema changes need a **new migration**, with matching changes in two places: the frozen SQL in `storage/core_migrations.py` and the `Table` definitions in `storage/tables.py`. `tests/test_schema.py` fails if the two differ. Never edit a released migration. The runner (`storage/migrations.py`) tracks `_migrations(component, version)` per component: the core and each plugin.
- `trials_fts` is an external-content FTS5 table over the view `trials_fts_content`. Change indexed data only through the writer in `sqlite.py`, which deletes a trial's FTS row before changing its text; anything else corrupts the index. Tests check it with `INSERT INTO trials_fts (trials_fts, rank) VALUES ('integrity-check', 1)`. FTS5 can't read virtual tables such as `json_each` through that view.
- `bulk_load()` drops the secondary indexes (`tables.DEFERRED_INDEXES`) and the FTS contents, then rebuilds both when it finishes. If it doesn't finish, `meta.bulk_load_started` blocks ordinary writes.
- `trial_docs.doc` is the raw JSON compressed with zstd (`storage/docs.py`; `backports.zstd` on 3.13), against the dictionary in `doc_dicts` that `dict_id` names. It's no longer JSONB, so SQL JSON functions can't read it.
- SQLAlchemy 2.1: don't call `dict(result)`, because a `Result` has `keys()`; use `dict(result.all())`. `Result.tuples()` is deprecated.

**Pipeline** (`trial_al.pipeline`, design §5.3 and §8): `Pipeline.from_plugins(config, loaded)` then `run_install(progress, from_file=, force=)` or `run_update(progress)`. Install builds `trials.db.new` in bulk-load mode (parse, hash and normalize in a spawned process pool; one writer), checks it and renames it over `trials.db`; stages are checkpointed in `runs`, so a re-run resumes. Update fetches since `cursor.<source> − 1 day` and writes everything, including `trial_changes`, in one `BEGIN IMMEDIATE` transaction. Skipping unchanged studies relies on `content_hash` (BLAKE2b of `Source.hashable(raw)` with sorted keys). Code that runs an install with workers must sit under `if __name__ == "__main__":` (spawn re-imports the main module).

**ctgov plugin** (`plugins/ctgov`): `CtgovSource` downloads `ctg-studies.json.zip` into `data/downloads/` (no Range support, so no resumed downloads) and reads it without extracting; updates page `/api/v2/studies` with `pageSize=1000`. `normalize.py` maps API v2 JSON to `TrialRecord`; `countries.py` maps all 226 API country names. Tests run offline against real study fixtures and recorded pages in `tests/fixtures/`.

**Contract tests.** A backend passes `trial_al.testing.StorageContract` by subclassing it in a test module and overriding the `storage` fixture (see `core/tests/test_storage_sqlite.py`); a source passes `trial_al.testing.SourceContract` the same way (see `plugins/ctgov/tests/test_source.py`). The fixtures are in `trial_al.testing.fixtures`.

**`doctor`** (`trial_al/doctor.py`) checks the Python and SQLite versions (SQLite ≥ 3.45), FTS5, extension loading, config, plugins, plugin extensions and database state. When a fix is needed, it suggests `uv python install`.

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
